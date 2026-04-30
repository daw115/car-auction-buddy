import os
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "__all__")

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(override=True)

from parser.models import ClientCriteria, AnalyzedLot, SearchResponse

app = FastAPI(title="USA Car Finder", version="1.0.0")

HTML_CACHE_DIR = Path(os.getenv("HTML_CACHE_DIR", "./data/html_cache"))
USE_EXTENSIONS = os.getenv("USE_EXTENSIONS", "false").lower() == "true"
USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "false").lower() == "true"
SEARCH_ARTIFACT_DIR = Path(os.getenv("SEARCH_ARTIFACT_DIR", "./data/client_searches"))

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def has_usable_openai_key() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").startswith("sk-"))


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


class ClientContext(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class SearchRequest(BaseModel):
    criteria: ClientCriteria
    demo: bool = False
    auction_min_hours: Optional[int] = None
    auction_max_hours: Optional[int] = None
    client: Optional[ClientContext] = None


def build_search_slug(criteria: ClientCriteria, timestamp: str) -> str:
    return "_".join(
        part
        for part in [
            criteria.make.lower().replace(" ", "_"),
            (criteria.model or "").lower().replace(" ", "_"),
            "insurance",
            timestamp,
        ]
        if part
    )


def search_title(criteria: ClientCriteria) -> str:
    parts = [
        criteria.make,
        criteria.model or "",
        f"od {criteria.year_from}" if criteria.year_from else "",
        f"do ${criteria.budget_usd:,.0f}",
    ]
    return " ".join(part for part in parts if part).replace("  ", " ")


def artifact_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"/artifacts/{Path(path).name}"


def analysis_notice(force_local: bool = False) -> str:
    mode = os.getenv("AI_ANALYSIS_MODE", "auto").lower()
    if force_local or mode == "local":
        return "Analiza lokalna"
    if mode in {"openai", "gpt"}:
        if has_usable_openai_key():
            return f"OpenAI {os.getenv('OPENAI_MODEL', 'gpt-5.2')}"
        return "OpenAI skonfigurowany, ale brak poprawnego OPENAI_API_KEY; użyto scoringu lokalnego"
    if mode == "anthropic":
        if os.getenv("ANTHROPIC_API_KEY"):
            return "Claude/Anthropic"
        return "Anthropic skonfigurowany, ale brak ANTHROPIC_API_KEY; użyto scoringu lokalnego"
    if has_usable_openai_key():
        return f"Auto: OpenAI {os.getenv('OPENAI_MODEL', 'gpt-5.2')}"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "Auto: Claude/Anthropic"
    return "Auto: brak kluczy AI; użyto scoringu lokalnego"


def write_ai_artifacts(
    *,
    criteria: ClientCriteria,
    lots,
    auction_min_hours: Optional[int],
    auction_max_hours: Optional[int],
) -> tuple[str, str, str]:
    SEARCH_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = build_search_slug(criteria, timestamp)

    lots_data = [lot.model_dump(mode="json") for lot in lots]
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "criteria": criteria.model_dump(mode="json"),
        "selection_pipeline": [
            f"auction window: {auction_min_hours}h do {auction_max_hours}h",
            "seller_type: insurance",
            "damage priority: najmniejsze widoczne uszkodzenia przed otwarciem detali",
            "details: otwierane tylko dla kandydatów po filtrach listy",
        ],
        "lots": lots_data,
    }

    input_path = (SEARCH_ARTIFACT_DIR / f"{slug}_ai_input.json").resolve()
    input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    prompt = {
        "task": (
            "Przeanalizuj auta z aukcji USA dla klienta importowego. "
            "Wybierz najlepsze propozycje, uzasadnij ranking, koszty, ryzyka i czerwone flagi."
        ),
        "output_language": "pl",
        "output_format": "JSON array",
        "required_fields": [
            "lot_id",
            "score",
            "recommendation",
            "why_selected",
            "risk_flags",
            "estimated_repair_usd",
            "estimated_total_cost_usd",
            "client_summary",
            "broker_notes",
        ],
        "input": payload,
    }
    prompt_path = (SEARCH_ARTIFACT_DIR / f"{slug}_ai_prompt.md").resolve()
    prompt_path.write_text(json.dumps(prompt, ensure_ascii=False, indent=2), encoding="utf-8")

    return str(input_path), str(prompt_path), slug


@app.get("/artifacts/{filename}")
async def download_artifact(filename: str):
    base_dir = SEARCH_ARTIFACT_DIR.resolve()
    path = (base_dir / filename).resolve()
    if path.parent != base_dir or not path.is_file():
        raise HTTPException(status_code=404, detail="Nie znaleziono artefaktu")

    media_types = {
        ".json": "application/json",
        ".md": "text/markdown; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }
    return FileResponse(
        path=str(path),
        media_type=media_types.get(path.suffix.lower(), "application/octet-stream"),
        filename=path.name,
    )


@app.post("/search", response_model=SearchResponse)
async def search_cars(request: SearchRequest):
    criteria = request.criteria

    if request.demo or USE_MOCK_DATA:
        from scraper.mock_data import get_mock_lots

        all_lots = get_mock_lots(criteria)
    else:
        from scraper.automated_scraper import AutomatedScraper

        scraper = AutomatedScraper()
        all_lots = await scraper.search_cars(
            criteria,
            auction_window_hours=request.auction_max_hours,
            min_auction_window_hours=request.auction_min_hours,
        )

    if not all_lots:
        raise HTTPException(status_code=404, detail="Brak wyników — sprawdź kryteria lub logi scrapera")

    ai_input_file, ai_prompt_file, slug = write_ai_artifacts(
        criteria=criteria,
        lots=all_lots,
        auction_min_hours=request.auction_min_hours,
        auction_max_hours=request.auction_max_hours,
    )

    from ai.analyzer import analyze_lots

    top_recommendations, ranked_results = analyze_lots(
        all_lots,
        criteria,
        top_n=5,
        force_local=request.demo,
    )
    top_recommendations = top_recommendations[:5]
    remaining_results = [r for r in ranked_results if not r.is_top_recommendation][:5]
    all_results = top_recommendations + remaining_results

    from report.client_artifacts import write_client_artifacts

    analysis_file, client_report_file = write_client_artifacts(
        criteria=criteria,
        top_recommendations=top_recommendations,
        ranked_results=ranked_results,
        output_dir=SEARCH_ARTIFACT_DIR,
        slug=slug,
    )

    artifact_urls = {
        "ai_input": artifact_url(ai_input_file),
        "ai_prompt": artifact_url(ai_prompt_file),
        "analysis_json": artifact_url(analysis_file),
        "client_report": artifact_url(client_report_file),
    }

    response_payload = SearchResponse(
        top_recommendations=top_recommendations,
        all_results=all_results,
        ai_input_file=ai_input_file,
        ai_prompt_file=ai_prompt_file,
        analysis_file=analysis_file,
        client_report_file=client_report_file,
        artifact_urls={key: value for key, value in artifact_urls.items() if value},
        analysis_notice=analysis_notice(force_local=request.demo),
        collected_count=len(all_lots),
    )

    from api.client_database import init_db, save_search_record, upsert_client

    init_db()
    client_payload = request.client.model_dump(mode="json") if request.client else None
    client_id = upsert_client(client_payload)
    response_dict = response_payload.model_dump(mode="json")
    request_dict = request.model_dump(mode="json")
    record_id = save_search_record(
        client_id=client_id,
        title=search_title(criteria),
        criteria=criteria.model_dump(mode="json"),
        request_data=request_dict,
        response_data=response_dict,
        artifact_urls=response_payload.artifact_urls,
        collected_count=response_payload.collected_count,
        analysis_notice=response_payload.analysis_notice,
        notes=(client_payload or {}).get("notes") if client_payload else None,
    )
    response_payload.record_id = record_id
    response_payload.client_id = client_id

    return response_payload


@app.get("/records")
async def list_client_records(query: Optional[str] = None, limit: int = 50):
    from api.client_database import list_records

    return {"records": list_records(query=query, limit=limit)}


@app.get("/records/{record_id}")
async def get_client_record(record_id: int):
    from api.client_database import get_record

    record = get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekordu")
    return record


class ApproveReportRequest(BaseModel):
    """Zatwierdzony raport - tylko wybrane loty"""
    approved_lots: list[AnalyzedLot]
    criteria: Optional[ClientCriteria] = None
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    tracking_url: Optional[str] = None


@app.post("/report")
async def generate_report(request: ApproveReportRequest):
    """Generuje PDF tylko dla zatwierdzonych lotów."""
    from report.generator import generate_pdf_report

    # Filtruj tylko loty oznaczone jako included_in_report
    lots_for_report = [lot for lot in request.approved_lots if lot.included_in_report]

    if not lots_for_report:
        raise HTTPException(status_code=400, detail="Brak lotów do raportu - wszystkie zostały usunięte")

    output_path = generate_pdf_report(lots_for_report)
    return FileResponse(
        path=str(output_path),
        media_type="application/pdf",
        filename=output_path.name,
    )


@app.post("/report/offer-email-html")
async def generate_offer_email_html_report(request: ApproveReportRequest):
    """Generuje mail HTML z ofertą tylko dla zatwierdzonych lotów."""
    from report.html_generator import write_offer_email_html

    lots_for_report = [lot for lot in request.approved_lots if lot.included_in_report]

    if not lots_for_report:
        raise HTTPException(status_code=400, detail="Brak lotów do raportu - wszystkie zostały usunięte")

    output_path = write_offer_email_html(
        lots_for_report,
        criteria=request.criteria,
        client_name=request.client_name,
        client_email=request.client_email,
        tracking_url=request.tracking_url,
    )
    return FileResponse(
        path=str(output_path),
        media_type="text/html; charset=utf-8",
        filename=output_path.name,
    )


@app.post("/report/client-html")
async def generate_client_html_report(request: ApproveReportRequest):
    """Generuje raport HTML dla klienta (storytelling, bez surowych cen) dla pierwszego zatwierdzonego lota."""
    from report.html_reports import render_client_report
    from fastapi.responses import HTMLResponse

    lots_for_report = [lot for lot in request.approved_lots if lot.included_in_report]

    if not lots_for_report:
        raise HTTPException(status_code=400, detail="Brak lotów do raportu - wszystkie zostały usunięte")

    html = render_client_report(lots_for_report[0], criteria=request.criteria)
    return HTMLResponse(content=html)


@app.post("/report/broker-html")
async def generate_broker_html_report(request: ApproveReportRequest):
    """Generuje wewnętrzny raport brokera (pełne dane, koszty, strategia bid) dla pierwszego zatwierdzonego lota."""
    from report.html_reports import render_broker_report
    from fastapi.responses import HTMLResponse

    lots_for_report = [lot for lot in request.approved_lots if lot.included_in_report]

    if not lots_for_report:
        raise HTTPException(status_code=400, detail="Brak lotów do raportu - wszystkie zostały usunięte")

    html = render_broker_report(
        lots_for_report[0],
        criteria=request.criteria,
        lots_scanned=len(request.approved_lots),
    )
    return HTMLResponse(content=html)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "use_extensions": USE_EXTENSIONS,
        "use_mock_data": USE_MOCK_DATA,
        "ai_analysis_mode": os.getenv("AI_ANALYSIS_MODE", "auto"),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-5.2"),
        "anthropic_base_url": os.getenv("ANTHROPIC_BASE_URL", ""),
        "anthropic_model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "has_openai_key": has_usable_openai_key(),
        "has_anthropic_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        "cache_dir": str(HTML_CACHE_DIR),
        "auction_min_hours": os.getenv("MIN_AUCTION_WINDOW_HOURS", "12"),
        "auction_max_hours": os.getenv("MAX_AUCTION_WINDOW_HOURS", "120"),
        "open_all_prefiltered_details": os.getenv("OPEN_ALL_PREFILTERED_DETAILS", "true"),
        "collect_all_prefiltered_results": os.getenv("COLLECT_ALL_PREFILTERED_RESULTS", "true"),
        "keep_browser_open": os.getenv("KEEP_BROWSER_OPEN", "true"),
        "browser_channel": os.getenv("BROWSER_CHANNEL", "chrome"),
    }


@app.get("/config")
async def config():
    return {
        "use_extensions": USE_EXTENSIONS,
        "use_mock_data": USE_MOCK_DATA,
        "ai_analysis_mode": os.getenv("AI_ANALYSIS_MODE", "auto"),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-5.2"),
        "anthropic_base_url": os.getenv("ANTHROPIC_BASE_URL", ""),
        "anthropic_model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "has_openai_key": has_usable_openai_key(),
        "has_anthropic_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        "auction_min_hours": os.getenv("MIN_AUCTION_WINDOW_HOURS", "12"),
        "auction_max_hours": os.getenv("MAX_AUCTION_WINDOW_HOURS", "120"),
        "open_all_prefiltered_details": os.getenv("OPEN_ALL_PREFILTERED_DETAILS", "true"),
        "collect_all_prefiltered_results": os.getenv("COLLECT_ALL_PREFILTERED_RESULTS", "true"),
        "keep_browser_open": os.getenv("KEEP_BROWSER_OPEN", "true"),
        "browser_channel": os.getenv("BROWSER_CHANNEL", "chrome"),
    }


@app.post("/browser/close")
async def close_scraper_browser():
    """Zamyka stały Chrome/Chromium używany do scrapingu z rozszerzeniami."""
    from scraper.browser_context import close_shared_extension_context

    await close_shared_extension_context()
    return {"status": "closed"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
