import os
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from datetime import datetime

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "__all__")

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

from parser.models import ClientCriteria, AnalyzedLot, SearchResponse
from api import jobs as jobs_store

logger = logging.getLogger("api.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init persistent job store + recover state
    try:
        from api import job_db
        job_db.init_db()
        orphans = job_db.mark_orphaned_running_as_interrupted()
        if orphans:
            logger.warning("[lifespan] Oznaczono %d zombi-jobów jako interrupted", orphans)
        loaded = jobs_store.hydrate_jobs_from_db()
        if loaded:
            logger.info("[lifespan] Wczytano %d persystowanych jobów z DB", loaded)
    except Exception:
        logger.exception("[lifespan] Inicjalizacja job_db nieudana")

    yield

    try:
        from scraper.browser_context import close_shared_extension_context

        await close_shared_extension_context()
        logger.info("[lifespan] Shared extension context closed")
    except Exception:
        logger.exception("[lifespan] Failed to close shared extension context")


app = FastAPI(title="USA Car Finder", version="1.0.0", lifespan=lifespan)

# CORS dla zdalnego dashboardu (np. Cloudflare Workers / Pages).
# DASHBOARD_ORIGINS = lista originów przecinkiem; "*" aby otworzyć wszystkim (NIE w produkcji).
_dashboard_origins_raw = os.getenv("DASHBOARD_ORIGINS", "").strip()
if _dashboard_origins_raw:
    _origins = [o.strip() for o in _dashboard_origins_raw.split(",") if o.strip()]
    _allow_credentials = "*" not in _origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=_allow_credentials,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    logger.info("[CORS] dozwolone originy: %s (credentials=%s)", _origins, _allow_credentials)

HTML_CACHE_DIR = Path(os.getenv("HTML_CACHE_DIR", "./data/html_cache"))
USE_EXTENSIONS = os.getenv("USE_EXTENSIONS", "false").lower() == "true"


def _extensions_disabled_reason_safe() -> Optional[str]:
    """Bezpieczny wrapper — nie ładujemy scrapera, gdy nie jest potrzebny."""
    if not USE_EXTENSIONS:
        return None
    try:
        from scraper.browser_context import extensions_enabled, extensions_disabled_reason
        extensions_enabled()  # compute reason eagerly
        return extensions_disabled_reason()
    except Exception:
        return None
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
    if mode == "gemini":
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            return f"Gemini {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}"
        return "Gemini skonfigurowany, ale brak GEMINI_API_KEY; użyto scoringu lokalnego"
    if has_usable_openai_key():
        return f"Auto: OpenAI {os.getenv('OPENAI_MODEL', 'gpt-5.2')}"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "Auto: Claude/Anthropic"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return f"Auto: Gemini {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}"
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


async def _execute_search(request: SearchRequest, job: jobs_store.Job) -> SearchResponse:
    criteria = request.criteria
    progress_cb = jobs_store.progress_callback(job)

    if request.demo or USE_MOCK_DATA:
        from scraper.mock_data import get_mock_lots

        progress_cb("scrape", {"source": "mock"})
        # Knob testowy: pozwala anulować mock job mid-flight (cancel propaguje na await).
        mock_delay = float(os.getenv("MOCK_PROGRESS_DELAY_S", "0"))
        if mock_delay > 0:
            await asyncio.sleep(mock_delay)
        all_lots = get_mock_lots(criteria)
        progress_cb("scrape", {"source": "mock", "count": len(all_lots), "_status": "done"})
    else:
        from scraper.automated_scraper import AutomatedScraper

        scraper = AutomatedScraper()
        all_lots = await scraper.search_cars(
            criteria,
            auction_window_hours=request.auction_max_hours,
            min_auction_window_hours=request.auction_min_hours,
            progress_cb=progress_cb,
        )

    notice_extra: list[str] = []
    if not all_lots:
        notice_extra.append("Brak wyników z aukcji — zwracam pustą odpowiedź.")

    if USE_EXTENSIONS and not request.demo and not USE_MOCK_DATA:
        try:
            from scraper.browser_context import extensions_disabled_reason
            ext_reason = extensions_disabled_reason()
        except Exception:
            ext_reason = None
        if ext_reason:
            notice_extra.append(ext_reason)

    if not all_lots:
        progress_cb("ai_analyze", {"_status": "skipped", "reason": "no_lots"})
        top_recommendations: list = []
        ranked_results: list = []
        ai_input_file = ai_prompt_file = analysis_file = client_report_file = None
    else:
        ai_input_file, ai_prompt_file, slug = write_ai_artifacts(
            criteria=criteria,
            lots=all_lots,
            auction_min_hours=request.auction_min_hours,
            auction_max_hours=request.auction_max_hours,
        )

        progress_cb("ai_analyze", {"lots": len(all_lots)})
        try:
            from ai.analyzer import analyze_lots

            # asyncio.to_thread bo analyze_lots jest sync z time.sleep w retry
            # (Gemini 429 backoff może 60s) — bez tego blokuje cały event loop
            top_recommendations, ranked_results = await asyncio.to_thread(
                analyze_lots,
                all_lots,
                criteria,
                5,  # top_n
                request.demo,  # force_local
            )
            progress_cb("ai_analyze", {"_status": "done", "ranked": len(ranked_results)})
        except Exception as exc:
            logger.exception("AI analysis failed; falling back to heuristic ordering")
            progress_cb("ai_analyze", {"_status": "error", "reason": str(exc)})
            notice_extra.append(f"AI niedostępne ({exc.__class__.__name__}); ranking heurystyczny.")
            top_recommendations, ranked_results = _heuristic_rank(all_lots)

        from report.client_artifacts import write_client_artifacts

        analysis_file, client_report_file = write_client_artifacts(
            criteria=criteria,
            top_recommendations=top_recommendations,
            ranked_results=ranked_results,
            output_dir=SEARCH_ARTIFACT_DIR,
            slug=slug,
        )

    top_recommendations = top_recommendations[:5]
    remaining_results = [r for r in ranked_results if not r.is_top_recommendation][:5]
    all_results = top_recommendations + remaining_results

    artifact_urls = {
        "ai_input": artifact_url(ai_input_file),
        "ai_prompt": artifact_url(ai_prompt_file),
        "analysis_json": artifact_url(analysis_file),
        "client_report": artifact_url(client_report_file),
    }

    notice = analysis_notice(force_local=request.demo)
    if notice_extra:
        notice = (notice + " | " if notice else "") + " ".join(notice_extra)

    with_full_vin = sum(1 for lot in all_lots if lot.full_vin)
    vin_coverage = {"with_full_vin": with_full_vin, "total": len(all_lots)}
    if USE_EXTENSIONS and all_lots and with_full_vin < len(all_lots):
        missing = len(all_lots) - with_full_vin
        logger.warning(
            "VIN coverage: %d/%d lotów bez full_vin po enrichmencie (USE_EXTENSIONS=true)",
            missing,
            len(all_lots),
        )

    response_payload = SearchResponse(
        top_recommendations=top_recommendations,
        all_results=all_results,
        ai_input_file=ai_input_file,
        ai_prompt_file=ai_prompt_file,
        analysis_file=analysis_file,
        client_report_file=client_report_file,
        artifact_urls={key: value for key, value in artifact_urls.items() if value},
        analysis_notice=notice,
        collected_count=len(all_lots),
        vin_coverage=vin_coverage,
    )

    try:
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
    except Exception:
        logger.exception("Persisting search record failed")

    return response_payload


def _heuristic_rank(lots):
    """Fallback ranking gdy AI padło — używa istniejącego sortowania damage+auction."""
    from scraper.automated_scraper import AutomatedScraper
    from parser.models import AIAnalysis, AnalyzedLot

    sorted_lots = sorted(lots, key=AutomatedScraper._damage_then_auction_sort_key)
    ranked: list[AnalyzedLot] = []
    for idx, lot in enumerate(sorted_lots):
        analysis = AIAnalysis(
            lot_id=lot.lot_id,
            score=max(0.0, 7.0 - idx * 0.2),
            recommendation="POLECAM" if idx < 5 else "RYZYKO",
            red_flags=["Ranking heurystyczny — AI niedostępne"],
            estimated_repair_usd=None,
            estimated_total_cost_usd=None,
            client_description_pl="Automatyczne uszeregowanie po typie szkody i dacie aukcji.",
            ai_notes="heuristic_fallback",
        )
        ranked.append(
            AnalyzedLot(
                lot=lot,
                analysis=analysis,
                is_top_recommendation=idx < 5,
                included_in_report=idx < 5,
            )
        )
    top = [r for r in ranked if r.is_top_recommendation]
    return top, ranked


async def _run_job(request: SearchRequest, job: jobs_store.Job) -> None:
    try:
        await jobs_store.mark_running(job)
        response = await _execute_search(request, job)
        await jobs_store.mark_done(job, response.model_dump(mode="json"))
    except asyncio.CancelledError:
        logger.info("Search job %s cancelled", job.id)
        await jobs_store.mark_cancelled(job)
        # nie podnosimy dalej — task ma się skończyć cicho
    except Exception as exc:
        logger.exception("Search job %s failed", job.id)
        await jobs_store.mark_error(job, f"{exc.__class__.__name__}: {exc}")


def _compute_criteria_hash(request: SearchRequest) -> str:
    import hashlib
    payload = {
        "criteria": request.criteria.model_dump(mode="json"),
        "demo": bool(request.demo),
        "auction_min_hours": request.auction_min_hours,
        "auction_max_hours": request.auction_max_hours,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_MIN", "30")) * 60


SCRAPER_API_TOKEN = os.getenv("SCRAPER_API_TOKEN", "").strip()


def _require_bearer(authorization: Optional[str] = Header(default=None)) -> None:
    """Sprawdza Bearer token gdy SCRAPER_API_TOKEN jest ustawiony.
    Pusty SCRAPER_API_TOKEN → endpoint otwarty (lokalne dev).
    """
    if not SCRAPER_API_TOKEN:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Brak Bearer tokena")
    token = authorization[7:].strip()
    if token != SCRAPER_API_TOKEN:
        raise HTTPException(status_code=403, detail="Nieprawidłowy token")


@app.post("/api/search")
async def dashboard_search(request: SearchRequest, _auth: None = Depends(_require_bearer)):
    """Synchroniczny adapter dla zewnętrznych dashboardów (np. car-auction-buddy).

    Wewnętrznie używa async pipeline + idempotency (jak POST /search).
    Czeka na zakończenie i zwraca płaską listę lotów — to czego oczekuje
    dashboard: { listings: CarLot[], source, job_id }.
    """
    criteria_hash = _compute_criteria_hash(request)
    reused = jobs_store.find_reusable_job(criteria_hash, IDEMPOTENCY_TTL_SECONDS)

    job = None
    if reused is not None and reused.status in ("running", "done"):
        job = reused
        if job.status == "running" and job.task is not None:
            try:
                await job.task
            except asyncio.CancelledError:
                raise HTTPException(status_code=503, detail="Job anulowany w trakcie wykonania")
    else:
        job = jobs_store.create_job(
            criteria_hash=criteria_hash,
            request_snapshot=request.model_dump(mode="json"),
        )
        job.task = asyncio.create_task(_run_job(request, job))
        try:
            await job.task
        except asyncio.CancelledError:
            raise HTTPException(status_code=503, detail="Job anulowany w trakcie wykonania")

    if job.status == "error":
        raise HTTPException(status_code=502, detail=f"Scraper failed: {job.error}")
    if job.status not in ("done",) or not job.result:
        raise HTTPException(status_code=500, detail=f"Job zakończony statusem {job.status}")

    result = job.result
    all_results = result.get("all_results", []) or []
    # all_results to AnalyzedLot — dashboard chce CarLot pod listings
    listings = [item.get("lot") for item in all_results if item.get("lot")]

    source = "mock" if (request.demo or USE_MOCK_DATA) else "live"
    return {
        "listings": listings,
        "source": source,
        "job_id": job.id,
        "criteria": request.criteria.model_dump(mode="json"),
        "vin_coverage": result.get("vin_coverage") or {},
        "analysis_notice": result.get("analysis_notice"),
    }


def _job_to_dashboard_dict(job: "jobs_store.Job") -> dict:
    """Spłaszcza Job do shape'u oczekiwanego przez car-auction-buddy frontend.

    TS oczekuje: { status, listings?, error?, progress?, step?, message?, current?, total?, phase? }
    """
    listings: list = []
    if job.result:
        for item in (job.result.get("all_results") or []):
            lot = item.get("lot") if isinstance(item, dict) else None
            if lot:
                listings.append(lot)

    latest_phase = job.phases[-1] if job.phases else None
    phase_name = latest_phase.name if latest_phase else None
    phase_info = latest_phase.info if latest_phase else {}
    current = phase_info.get("current")
    total = phase_info.get("total")
    progress: Optional[float] = None
    if isinstance(current, (int, float)) and isinstance(total, (int, float)) and total:
        progress = max(0.0, min(1.0, current / total))
    elif job.status == "done":
        progress = 1.0

    return {
        "status": job.status,
        "listings": listings if job.status == "done" else None,
        "error": job.error,
        "progress": progress,
        "phase": phase_name,
        "step": phase_info.get("step"),
        "message": phase_info.get("message"),
        "current": current,
        "total": total,
    }


@app.get("/api/jobs/{job_id}")
async def dashboard_get_job(job_id: str, _auth: None = Depends(_require_bearer)):
    """Adapter dla zewnętrznych dashboardów — alias do GET /search/jobs/{id}
    z reshapingiem odpowiedzi do shape'u car-auction-buddy."""
    job = jobs_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono zadania")
    return _job_to_dashboard_dict(job)


@app.delete("/api/jobs/{job_id}")
async def dashboard_cancel_job(job_id: str, _auth: None = Depends(_require_bearer)):
    """Adapter dla zewnętrznych dashboardów — alias do DELETE /search/jobs/{id}."""
    job = jobs_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono zadania")
    requested = jobs_store.request_cancel(job)
    return {
        "job_id": job.id,
        "status": job.status,
        "cancel_requested": requested,
    }


@app.post("/search", status_code=202)
async def search_cars(request: SearchRequest):
    criteria_hash = _compute_criteria_hash(request)
    reused = jobs_store.find_reusable_job(criteria_hash, IDEMPOTENCY_TTL_SECONDS)
    if reused is not None:
        logger.info("[/search] Idempotent reuse job %s (status=%s)", reused.id, reused.status)
        return {
            "job_id": reused.id,
            "status_url": f"/search/jobs/{reused.id}",
            "stream_url": f"/search/stream/{reused.id}",
            "cancel_url": f"/search/jobs/{reused.id}",
            "idempotent": True,
            "reused_status": reused.status,
        }

    job = jobs_store.create_job(
        criteria_hash=criteria_hash,
        request_snapshot=request.model_dump(mode="json"),
    )
    job.task = asyncio.create_task(_run_job(request, job))
    return {
        "job_id": job.id,
        "status_url": f"/search/jobs/{job.id}",
        "stream_url": f"/search/stream/{job.id}",
        "cancel_url": f"/search/jobs/{job.id}",
        "idempotent": False,
    }


@app.get("/search/jobs/{job_id}")
async def get_search_job(job_id: str):
    job = jobs_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono zadania")
    return job.to_dict()


@app.delete("/search/jobs/{job_id}")
async def cancel_search_job(job_id: str):
    job = jobs_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono zadania")
    requested = jobs_store.request_cancel(job)
    return {
        "job_id": job.id,
        "status": job.status,
        "cancel_requested": requested,
    }


@app.get("/search/stream/{job_id}")
async def stream_search_job(job_id: str):
    job = jobs_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono zadania")

    async def event_source():
        async for event in jobs_store.stream_events(job):
            event_type = event.get("type", "message")
            if event_type == "__end__":
                yield "event: end\ndata: {}\n\n"
                break
            yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        "extensions_disabled_reason": _extensions_disabled_reason_safe(),
        "use_mock_data": USE_MOCK_DATA,
        "ai_analysis_mode": os.getenv("AI_ANALYSIS_MODE", "auto"),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-5.2"),
        "anthropic_base_url": os.getenv("ANTHROPIC_BASE_URL", ""),
        "anthropic_model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "has_openai_key": has_usable_openai_key(),
        "has_anthropic_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        "has_gemini_key": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
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
        "extensions_disabled_reason": _extensions_disabled_reason_safe(),
        "extensions_disabled_reason": _extensions_disabled_reason_safe(),
        "use_mock_data": USE_MOCK_DATA,
        "ai_analysis_mode": os.getenv("AI_ANALYSIS_MODE", "auto"),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-5.2"),
        "anthropic_base_url": os.getenv("ANTHROPIC_BASE_URL", ""),
        "anthropic_model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "has_openai_key": has_usable_openai_key(),
        "has_anthropic_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        "has_gemini_key": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
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
