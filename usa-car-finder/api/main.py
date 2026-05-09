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

        # Zapis search_records dla wszystkich terminalnych jobow (cancelled/error/interrupted)
        # ktore jeszcze go nie maja. Dedupping przez job_id. Idempotentne — dziala przy
        # kazdym starcie, no-op gdy wszystko juz zapisane.
        try:
            from api.client_database import (
                init_db as _init_app_db, save_search_record, search_record_exists_for_job,
            )
            _init_app_db()
            all_rows = job_db.load_all_rows()
            backfilled = 0
            for row in all_rows:
                status = row.get("status")
                if status not in ("interrupted", "cancelled", "error"):
                    continue
                job_id = row.get("id")
                if not job_id or search_record_exists_for_job(job_id):
                    continue
                request_data = json.loads(row.get("request_json") or "{}")
                crit = request_data.get("criteria") or {}
                if not crit.get("make"):
                    continue
                parts = [crit.get("make", "?"), crit.get("model") or ""]
                if crit.get("year_from"):
                    parts.append(f"od {crit['year_from']}")
                title = " ".join(p for p in parts if p).strip()
                notice_map = {
                    "interrupted": "Zadanie zostało przerwane (uvicorn restart przed ukończeniem)",
                    "cancelled": "Zadanie zostało anulowane przez użytkownika",
                    "error": row.get("error") or "Nieznany błąd",
                }
                save_search_record(
                    client_id=None,
                    title=title or "?",
                    criteria=crit,
                    request_data=request_data,
                    response_data={"job_id": job_id, "status": status, "error": row.get("error")},
                    artifact_urls={},
                    collected_count=0,
                    analysis_notice=notice_map.get(status, status),
                    status=status,
                    job_id=job_id,
                )
                backfilled += 1
            if backfilled:
                logger.info("[lifespan] Backfill: zapisano %d brakujacych terminalnych records", backfilled)
        except Exception:
            logger.exception("[lifespan] Backfill terminalnych records nieudany")

        loaded = jobs_store.hydrate_jobs_from_db()
        if loaded:
            logger.info("[lifespan] Wczytano %d persystowanych jobów z DB", loaded)
    except Exception:
        logger.exception("[lifespan] Inicjalizacja job_db nieudana")

    # Startup: init LLM report cache (24h TTL, drugi klik tego samego lota = $0)
    try:
        from report import llm_cache
        llm_cache.init_db()
        purged = llm_cache.purge_expired()
        if purged:
            logger.info("[lifespan] LLM cache: usunięto %d starych wpisów", purged)
    except Exception:
        logger.exception("[lifespan] Inicjalizacja llm_cache nieudana")

    # Startup: init model normalization cache (BMW M440i -> 4 Series itp.)
    try:
        from ai import model_normalization
        model_normalization.init_db()
        st = model_normalization.stats()
        logger.info("[lifespan] Model normalization cache: %d wpisów", st.get("total", 0))
    except Exception:
        logger.exception("[lifespan] Inicjalizacja model_normalization nieudana")

    # Startup: Telegram bot polling (multi-user broadcast notifications)
    telegram_task = None
    try:
        from notify import telegram as _tg
        from notify.telegram_bot import polling_loop as _tg_polling
        from api import telegram_database as _tdb
        _tdb.init_db()
        if _tg.is_configured():
            telegram_task = asyncio.create_task(_tg_polling(), name="telegram-bot-polling")
            stats_t = _tdb.stats()
            logger.info(
                "[lifespan] Telegram bot polling uruchomiony (subskrybentów: %d aktywnych / %d total)",
                stats_t.get("active", 0), stats_t.get("total", 0),
            )
        else:
            logger.info("[lifespan] TELEGRAM_BOT_TOKEN nie ustawiony — bot disabled")
    except Exception:
        logger.exception("[lifespan] Telegram polling startup nieudany")

    yield

    # Shutdown: stop Telegram polling task
    if telegram_task is not None:
        telegram_task.cancel()
        try:
            await telegram_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("[lifespan] Telegram polling stopped")

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
    """Lokalny statyczny UI Pythona (dev/legacy fallback).
    Pełne profesjonalne UI dostępne na https://car-auction-buddy.lovable.app/"""
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
        f"do ${criteria.budget_usd:,.0f}" if criteria.budget_usd else "bez limitu budżetu",
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
        # PRE-RANK heurystyczny: zbieramy WSZYSTKIE loty z scrape'a, ale do AI
        # przekazujemy tylko top N (default 10) najbardziej obiecujących.
        # Oszczędność: 36 lotów -> AI ocenia 10 = 3.6× mniej tokenów.
        ai_top_n = int(os.getenv("AI_ANALYSIS_TOP_N", "10"))
        progress_cb("pre_rank", {
            "input": len(all_lots),
            "top_n": ai_top_n,
            "_status": "running",
        })
        lots_for_ai = _pre_rank_lots_for_ai(all_lots, top_n=ai_top_n)
        progress_cb("pre_rank", {
            "input": len(all_lots),
            "output": len(lots_for_ai),
            "_status": "done",
        })

        ai_input_file, ai_prompt_file, slug = write_ai_artifacts(
            criteria=criteria,
            lots=lots_for_ai,  # tylko top N (zgodne z tym co AI faktycznie analizuje)
            auction_min_hours=request.auction_min_hours,
            auction_max_hours=request.auction_max_hours,
        )

        progress_cb("ai_analyze", {"lots": len(lots_for_ai), "from_total": len(all_lots)})
        try:
            from ai.analyzer import analyze_lots

            # AI analizuje TYLKO top N (heurystycznie wybrane)
            top_recommendations, ranked_results = await asyncio.to_thread(
                analyze_lots,
                lots_for_ai,
                criteria,
                5,  # top_n dla _rank_results (legacy, nadpiszemy showcase'em)
                request.demo,
            )
            progress_cb("ai_analyze", {"_status": "done", "ranked": len(ranked_results)})
        except Exception as exc:
            logger.exception("AI analysis failed; falling back to heuristic ordering")
            progress_cb("ai_analyze", {"_status": "error", "reason": str(exc)})
            notice_extra.append(f"AI niedostępne ({exc.__class__.__name__}); ranking heurystyczny.")
            top_recommendations, ranked_results = _heuristic_rank(lots_for_ai)

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

    # Auto-generuj raporty HTML po analizie AI — SHOWCASE = WSZYSTKIE POLECAM + 2 najlepsze RYZYKO:
    # User wybiera wśród wszystkich lotów polecanych przez AI, plus 2 alternatywy ryzykowne.
    # Sortowanie po auction_date ASC — najbliższe aukcje pierwsze (klient powinien decydować szybko).
    client_html_files: list[str] = []
    broker_html_files: list[str] = []
    # Auto-raport krótki klienta (template Jinja2 — szybki, bez LLM, bez Otomoto)
    client_short_html_files: list[str] = []
    client_short_urls_by_lot_id: dict[str, str] = {}
    index_file: Optional[str] = None
    # Auto-zbiorcze bundle (klient pełny + klient krótki + broker dla wszystkich showcase)
    client_bundle_file: Optional[str] = None
    client_short_bundle_file: Optional[str] = None
    broker_bundle_file: Optional[str] = None

    polecam_lots = [r for r in ranked_results if r.analysis.recommendation == "POLECAM"]
    ryzyko_lots = sorted(
        [r for r in ranked_results if r.analysis.recommendation == "RYZYKO"],
        key=lambda r: -r.analysis.score,
    )

    # Cap RYZYKO: zawsze 2 pierwsze (najlepsze score). POLECAM bez capa.
    SHOWCASE_RYZYKO_LIMIT = int(os.getenv("SHOWCASE_RYZYKO_LIMIT", "2"))

    showcase: list = list(polecam_lots) + list(ryzyko_lots[:SHOWCASE_RYZYKO_LIMIT])

    # Sort showcase po auction_date ASC (najbliższa aukcja pierwsza)
    showcase.sort(key=lambda r: r.lot.auction_date or "9999-12-31 23:59:59")

    polecane = showcase
    logger.info(
        "Showcase: %d POLECAM + %d RYZYKO (sort: auction_date ASC, RYZYKO limit %d)",
        sum(1 for r in showcase if r.analysis.recommendation == "POLECAM"),
        sum(1 for r in showcase if r.analysis.recommendation == "RYZYKO"),
        SHOWCASE_RYZYKO_LIMIT,
    )

    # Nadpisz is_top_recommendation żeby odpowiadało showcase'owi (a nie default top_n=5
    # z _rank_results po score). UI używa is_top_recommendation do filtrowania showcase tabeli.
    showcase_lot_ids = {r.lot.lot_id for r in showcase}
    for r in ranked_results:
        r.is_top_recommendation = r.lot.lot_id in showcase_lot_ids

    # MAX_FINAL_RESULTS: cap ostatecznej listy zwracanej do UI po scoringu (default 10).
    # Showcase (auto-raporty) zawsze idzie pierwszy, potem dopełniamy najlepszymi z reszty.
    max_final = int(os.getenv("MAX_FINAL_RESULTS", "10"))
    top_recommendations = showcase[:max_final]
    remaining_capacity = max_final - len(top_recommendations)
    remaining_results = [r for r in ranked_results if r.lot.lot_id not in showcase_lot_ids][:remaining_capacity] if remaining_capacity > 0 else []
    all_results = top_recommendations + remaining_results

    logger.info(
        "Cap MAX_FINAL_RESULTS=%d: zwracam %d showcase + %d additional = %d total",
        max_final, len(top_recommendations), len(remaining_results), len(all_results),
    )

    if polecane and slug:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        budget_str = f"budżet ${criteria.budget_usd:,.0f}" if criteria.budget_usd else "bez limitu budżetu"
        search_query_str = (
            f"{criteria.make} {criteria.model or ''} "
            f"{criteria.year_from or ''}-{criteria.year_to or ''}, "
            f"{budget_str}"
        ).strip()

        # Mode: 'hybrid' (Gemini darmowy + Otomoto, default), 'template' (Jinja2 zero LLM,
        # bez tłumaczenia/cen PL), 'llm' (full Claude rich, ~$4/scrape — drogie).
        # Hybrid generuje per-lot raporty z polską terminologią + Otomoto market price.
        reports_mode = os.getenv("REPORTS_MODE", "hybrid").lower()
        # render_pair_fn = item -> (client_html, broker_html). Faza 3F: w hybrid
        # mode 1 LLM call zamiast 2 (50% redukcja calli + RPM oszczędność).
        render_pair_fn = None
        try:
            if reports_mode == "hybrid":
                from report.hybrid_reports import render_client_hybrid, render_broker_hybrid, render_pair_hybrid
                render_client_fn = lambda it: render_client_hybrid(it, criteria=criteria)
                render_broker_fn = lambda it: render_broker_hybrid(it, criteria=criteria, lots_scanned=len(all_lots))
                render_pair_fn = lambda it: render_pair_hybrid(it, criteria=criteria, lots_scanned=len(all_lots))

                # Faza 3E: Pre-warm Otomoto cache batch — w 1 wątku każde unique (make,model,year_range)
                # zamiast 2× per-lot (raz dla client, raz dla broker) sekwencyjnie. Eliminuje cold-miss
                # penalty (8-15s × N unique lookups) z critical path LLM fan-out.
                if os.getenv("OTOMOTO_LOOKUP_ENABLED", "true").lower() == "true":
                    try:
                        from scraper.otomoto import lookup_market_price
                        unique_lookups = {
                            (p.lot.make, p.lot.model,
                             (p.lot.year - 1) if p.lot.year else None,
                             (p.lot.year + 1) if p.lot.year else None)
                            for p in polecane if p.lot.make and p.lot.model
                        }
                        if unique_lookups:
                            from concurrent.futures import ThreadPoolExecutor as _TPE
                            logger.info("[otomoto_prewarm] %d unique lookups, fan-out parallel", len(unique_lookups))
                            def _warm(args):
                                try:
                                    lookup_market_price(*args)
                                except Exception:
                                    pass  # non-fatal — hybrid_reports ma try/except wewnątrz
                            await asyncio.to_thread(
                                lambda: list(_TPE(max_workers=4).map(_warm, unique_lookups))
                            )
                            logger.info("[otomoto_prewarm] done")
                    except Exception:
                        logger.exception("[otomoto_prewarm] failed (non-fatal)")
            elif reports_mode == "llm":
                from report.llm_html_reports import render_client_report_llm, render_broker_report_llm
                render_client_fn = lambda it: render_client_report_llm(it, criteria=criteria)
                render_broker_fn = lambda it: render_broker_report_llm(it, criteria=criteria, lots_scanned=len(all_lots))
            else:
                from report.html_reports import render_client_report, render_broker_report
                render_client_fn = lambda it: render_client_report(it, criteria=criteria)
                render_broker_fn = lambda it: render_broker_report(it, criteria=criteria, lots_scanned=len(all_lots))

            # Generuj raporty z limitem concurrency — RouteAI ma per-user concurrent limit
            # (zwykle 2-3), więc 10 calli równoległych = większość pada na 429.
            # LLM_REPORTS_CONCURRENCY=2 znaczy max 2 LLM calle naraz, kolejne czekają.
            llm_concurrency = int(os.getenv("LLM_REPORTS_CONCURRENCY", "2"))
            llm_semaphore = asyncio.Semaphore(llm_concurrency)

            async def _gen_with_semaphore(fn, item):
                async with llm_semaphore:
                    return await asyncio.to_thread(fn, item)

            total_reports = len(polecane)

            async def gen_one(idx: int, item: AnalyzedLot) -> dict:
                lot_id_safe = (item.lot.lot_id or f"lot{idx}").replace("/", "_")
                title = f"{item.lot.year or ''} {item.lot.make or ''} {item.lot.model or ''} {item.lot.trim or ''}".strip()
                links = {
                    "lot_id": item.lot.lot_id,
                    "title": title,
                    "badge": f"score {item.analysis.score:.1f} {item.analysis.recommendation}",
                    "client": None,
                    "broker": None,
                }

                # Live progress: który lot aktualnie generujemy
                progress_cb("reports_generate", {
                    "current": idx,
                    "total": total_reports,
                    "lot": title,
                    "lot_id": item.lot.lot_id,
                    "step": "generating",
                })

                # Faza 3F: w hybrid mode 1 LLM call zwraca (client, broker). W innych
                # trybach (template/llm) zostają 2 osobne calle.
                if render_pair_fn is not None:
                    try:
                        async with llm_semaphore:
                            pair = await asyncio.to_thread(render_pair_fn, item)
                        results = list(pair)  # [client_html, broker_html]
                    except Exception as exc:
                        results = [exc, exc]
                else:
                    client_task = _gen_with_semaphore(render_client_fn, item)
                    broker_task = _gen_with_semaphore(render_broker_fn, item)
                    results = await asyncio.gather(client_task, broker_task, return_exceptions=True)

                if not isinstance(results[0], Exception):
                    fname = f"{slug}_{ts}_top{idx}_{lot_id_safe}_klient.html"
                    (SEARCH_ARTIFACT_DIR / fname).write_text(results[0], encoding="utf-8")
                    client_html_files.append(str(SEARCH_ARTIFACT_DIR / fname))
                    links["client"] = fname
                else:
                    logger.exception("Client report failed lot %s: %s", item.lot.lot_id, results[0])

                if not isinstance(results[1], Exception):
                    fname = f"{slug}_{ts}_top{idx}_{lot_id_safe}_broker.html"
                    (SEARCH_ARTIFACT_DIR / fname).write_text(results[1], encoding="utf-8")
                    broker_html_files.append(str(SEARCH_ARTIFACT_DIR / fname))
                    links["broker"] = fname
                else:
                    logger.exception("Broker report failed lot %s: %s", item.lot.lot_id, results[1])
                return links

            logger.info("Generuję %d raportów (klient+broker) w mode=%s, parallel...", len(polecane), reports_mode)
            progress_cb("reports_generate", {
                "total": len(polecane),
                "mode": reports_mode,
                "_status": "running",
            })
            lot_links_all = await asyncio.gather(*[gen_one(i + 1, it) for i, it in enumerate(polecane)])
            lot_links: list[dict] = [ll for ll in lot_links_all if ll.get("client") or ll.get("broker")]
            progress_cb("reports_generate", {
                "total": len(polecane),
                "generated": len(lot_links),
                "_status": "done",
            })

            # AUTO-RAPORT KRÓTKI KLIENT (template Jinja2 — bez LLM, ~50ms/lot)
            # Dla kazdego showcase lota generujemy 'krotka' wersje raportu klienta
            # — uzywa render_client_report (template) zamiast hybrid (Gemini+Otomoto).
            # Klient/broker moze otworzyc szybsza wersje gdy nie ma czasu na rich.
            try:
                from report.html_reports import render_client_report
                for idx, item in enumerate(polecane, 1):
                    try:
                        lot_id_safe = (item.lot.lot_id or f"lot{idx}").replace("/", "_")
                        html = render_client_report(item, criteria=criteria)
                        fname = f"{slug}_{ts}_top{idx}_{lot_id_safe}_klient_krotki.html"
                        fpath = SEARCH_ARTIFACT_DIR / fname
                        fpath.write_text(html, encoding="utf-8")
                        client_short_html_files.append(str(fpath))
                        if item.lot.lot_id:
                            client_short_urls_by_lot_id[item.lot.lot_id] = artifact_url(str(fpath))
                    except Exception:
                        logger.exception("Short client report failed for lot %s", item.lot.lot_id)
                logger.info("Generated %d short client reports (template, ~%dms/lot)",
                            len(client_short_html_files), 50)
            except Exception:
                logger.exception("Short client reports generation failed")

            # AUTO-BUNDLE: 1 plik klient + 1 plik broker dla wszystkich showcase
            # Skleja juz wygenerowane per-lot HTMLs przez _bundle_html() helper.
            if client_html_files or broker_html_files:
                progress_cb("bundle_generate", {"_status": "running"})
                try:
                    title_meta = f"{criteria.make}"
                    if criteria.model:
                        title_meta += f" {criteria.model}"

                    # Zbuduj mapę lot_id -> AnalyzedLot (do meta: recommendation, score)
                    showcase_by_lot_id = {al.lot.lot_id: al for al in polecane}

                    if client_html_files:
                        # ZBIORCZY KLIENT: tylko POLECAM (klient nie powinien widziec RYZYKO/ODRZUC)
                        client_htmls = []
                        for fp in client_html_files:
                            try:
                                fp_path = Path(fp)
                                content = fp_path.read_text(encoding="utf-8")
                                ll = next((l for l in lot_links if l.get("lot_id") and l["lot_id"] in fp_path.stem), None)
                                label = ll["title"] if ll else fp_path.stem
                                lot_id = (ll or {}).get("lot_id")
                                al = showcase_by_lot_id.get(lot_id) if lot_id else None

                                # FILTR: pomijamy nie-POLECAM dla zbiorczego klienta
                                if al and al.analysis.recommendation != "POLECAM":
                                    continue

                                meta = {}
                                if al:
                                    meta = {
                                        "recommendation": al.analysis.recommendation,
                                        "score": al.analysis.score,
                                        "lot_id": al.lot.lot_id,
                                    }
                                client_htmls.append((label, content, meta))
                            except Exception:
                                logger.exception("Failed to read client HTML %s", fp)
                        if client_htmls:
                            # Sortuj po score desc (najlepsze POLECAM pierwsze)
                            client_htmls.sort(key=lambda x: -(x[2].get("score") or 0))
                            bundle_title = f"Raport zbiorczy klienta — {len(client_htmls)} aut POLECAM ({title_meta})"
                            bundle_html = _bundle_html(client_htmls, bundle_title)
                            bundle_path = SEARCH_ARTIFACT_DIR / f"{slug}_{ts}_zbiorczy_klient.html"
                            bundle_path.write_text(bundle_html, encoding="utf-8")
                            client_bundle_file = str(bundle_path)
                            logger.info("Auto-bundle klient (POLECAM only): %s (%d KB, %d lotów)",
                                        bundle_path.name, len(bundle_html) // 1024, len(client_htmls))

                    # ZBIORCZY KRÓTKI KLIENT (sklejka per-lot template, też tylko POLECAM)
                    if client_short_html_files:
                        client_short_htmls = []
                        for fp in client_short_html_files:
                            try:
                                fp_path = Path(fp)
                                content = fp_path.read_text(encoding="utf-8")
                                # nazwa: {slug}_{ts}_top{idx}_{lot_id}_klient_krotki.html
                                # wyciągnij lot_id ze stem
                                stem_parts = fp_path.stem.split("_")
                                lot_id = None
                                for part in stem_parts:
                                    if part in showcase_by_lot_id:
                                        lot_id = part
                                        break
                                al = showcase_by_lot_id.get(lot_id) if lot_id else None
                                # Filtr: tylko POLECAM (analogicznie do pełnego)
                                if al and al.analysis.recommendation != "POLECAM":
                                    continue
                                label = (
                                    f"{al.lot.year or '?'} {al.lot.make or ''} {al.lot.model or ''} (#{al.lot.lot_id})".strip()
                                    if al else fp_path.stem
                                )
                                meta = {}
                                if al:
                                    meta = {
                                        "recommendation": al.analysis.recommendation,
                                        "score": al.analysis.score,
                                        "lot_id": al.lot.lot_id,
                                    }
                                client_short_htmls.append((label, content, meta))
                            except Exception:
                                logger.exception("Failed to read client_short HTML %s", fp)
                        if client_short_htmls:
                            client_short_htmls.sort(key=lambda x: -(x[2].get("score") or 0))
                            bundle_title = f"Raport krótki zbiorczy klienta — {len(client_short_htmls)} aut POLECAM ({title_meta})"
                            bundle_html = _bundle_html(client_short_htmls, bundle_title)
                            bundle_path = SEARCH_ARTIFACT_DIR / f"{slug}_{ts}_zbiorczy_klient_krotki.html"
                            bundle_path.write_text(bundle_html, encoding="utf-8")
                            client_short_bundle_file = str(bundle_path)
                            logger.info("Auto-bundle klient KRÓTKI (POLECAM only): %s (%d KB, %d lotów)",
                                        bundle_path.name, len(bundle_html) // 1024, len(client_short_htmls))

                    if broker_html_files:
                        broker_htmls = []
                        for fp in broker_html_files:
                            try:
                                fp_path = Path(fp)
                                content = fp_path.read_text(encoding="utf-8")
                                ll = next((l for l in lot_links if l.get("lot_id") and l["lot_id"] in fp_path.stem), None)
                                label = ll["title"] if ll else fp_path.stem
                                lot_id = (ll or {}).get("lot_id")
                                al = showcase_by_lot_id.get(lot_id) if lot_id else None
                                meta = {}
                                if al:
                                    meta = {
                                        "recommendation": al.analysis.recommendation,
                                        "score": al.analysis.score,
                                        "lot_id": al.lot.lot_id,
                                    }
                                broker_htmls.append((label, content, meta))
                            except Exception:
                                logger.exception("Failed to read broker HTML %s", fp)
                        if broker_htmls:
                            order = {"POLECAM": 0, "RYZYKO": 1, "ODRZUĆ": 2}
                            broker_htmls.sort(key=lambda x: (order.get(x[2].get("recommendation", ""), 99), -(x[2].get("score") or 0)))
                            bundle_title = f"Raport brokerski zbiorczy — {len(broker_htmls)} aut ({title_meta})"
                            bundle_html = _bundle_html(broker_htmls, bundle_title)
                            bundle_path = SEARCH_ARTIFACT_DIR / f"{slug}_{ts}_zbiorczy_broker.html"
                            bundle_path.write_text(bundle_html, encoding="utf-8")
                            broker_bundle_file = str(bundle_path)
                            logger.info("Auto-bundle broker: %s (%d KB)", bundle_path.name, len(bundle_html) // 1024)

                    progress_cb("bundle_generate", {
                        "_status": "done",
                        "client_bundle": bool(client_bundle_file),
                        "broker_bundle": bool(broker_bundle_file),
                    })
                except Exception:
                    logger.exception("Auto-bundle generation failed")
                    progress_cb("bundle_generate", {"_status": "error"})

            # INDEX — jedna strona z buttonami "Klient" / "Broker" per polecony lot
            if lot_links:
                index_html = (
                    "<!DOCTYPE html><html lang='pl'><head><meta charset='UTF-8'>"
                    f"<title>Polecane oferty — {criteria.make} {criteria.model or ''}</title>"
                    "<style>body{font-family:'DM Sans',Arial,sans-serif;background:#f5f7fb;padding:32px;color:#1a1f36;margin:0}"
                    ".wrap{max-width:980px;margin:0 auto;background:white;border-radius:12px;padding:32px;box-shadow:0 8px 32px rgba(0,0,0,0.08)}"
                    "h1{margin:0 0 8px;color:#0d2855;font-size:24px}.sub{color:#6b7280;margin-bottom:24px;font-size:14px}"
                    ".lot{padding:18px 20px;border:1px solid #e5e9f2;border-radius:10px;margin-bottom:14px;transition:border-color .2s}"
                    ".lot:hover{border-color:#0066ff}.lot-title{font-weight:700;font-size:16px;color:#0d2855;margin-bottom:4px}"
                    ".lot-badge{display:inline-block;padding:2px 10px;border-radius:12px;background:#dcfce7;color:#166534;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;margin-left:8px}"
                    ".lot-actions{margin-top:10px;display:flex;gap:10px;flex-wrap:wrap}"
                    ".btn{padding:8px 14px;border:1px solid #e5e9f2;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600;background:white;transition:all .15s}"
                    ".btn-client{border-color:#16a34a;color:#16a34a}.btn-client:hover{background:#16a34a;color:white}"
                    ".btn-broker{border-color:#0066ff;color:#0066ff}.btn-broker:hover{background:#0066ff;color:white}</style></head>"
                    "<body><div class='wrap'>"
                    f"<h1>🎯 Wyselekcjonowane oferty ({len(lot_links)})</h1>"
                    f"<div class='sub'>Zapytanie: <em>{search_query_str}</em> · Zeskanowano: {len(all_lots)} lotów (filtr: insurance only) · TOP 4 + 1 alternatywa</div>"
                )
                for ll in lot_links:
                    index_html += f"<div class='lot'><div class='lot-title'>{ll['title']}<span class='lot-badge'>POLECAM · {ll['badge']}</span></div><div class='lot-actions'>"
                    if ll["client"]:
                        index_html += f"<a class='btn btn-client' href='{ll['client']}' target='_blank'>📄 Raport dla klienta</a>"
                    if ll["broker"]:
                        index_html += f"<a class='btn btn-broker' href='{ll['broker']}' target='_blank'>📊 Raport brokerski</a>"
                    index_html += "</div></div>"
                index_html += "</div></body></html>"

                idx_path = SEARCH_ARTIFACT_DIR / f"{slug}_{ts}_polecane_index.html"
                idx_path.write_text(index_html, encoding="utf-8")
                index_file = str(idx_path)
                logger.info("Auto-generated %d polecanych raportów (klient+broker) + index", len(lot_links))
        except Exception:
            logger.exception("Auto-generate POLECAM reports failed")

    # SearchResponse.artifact_urls wymaga dict[str, str], więc tylko same stringi
    artifact_urls = {
        "ai_input": artifact_url(ai_input_file),
        "ai_prompt": artifact_url(ai_prompt_file),
        "analysis_json": artifact_url(analysis_file),
        "client_report": artifact_url(client_report_file),
        # Index linkujący wszystkie POLECANE oferty (klient + broker per lot)
        "polecane_index": artifact_url(index_file),
        # Auto-zbiorcze bundle: 1 plik klient (pełny) + 1 klient krótki + 1 broker
        "client_bundle": artifact_url(client_bundle_file),
        "client_short_bundle": artifact_url(client_short_bundle_file),
        "broker_bundle": artifact_url(broker_bundle_file),
    }
    client_reports_html_urls = [artifact_url(f) for f in client_html_files if f]
    broker_reports_html_urls = [artifact_url(f) for f in broker_html_files if f]

    # Per-lot mapping (lot_id -> {client_url, client_short_url, broker_url})
    # UI dla per-row download buttons. 3 typy raportów per lot:
    #   - client_url        = pełny (hybrid Gemini + Otomoto + storytelling)
    #   - client_short_url  = krótki (template Jinja2, szybki, podstawowy)
    #   - broker_url        = pełny brokerski (hybrid)
    auto_reports_by_lot_id: dict[str, dict[str, str]] = {}
    try:
        for ll in (lot_links if 'lot_links' in dir() else []):
            lot_id = ll.get("lot_id")
            if not lot_id:
                continue
            entry: dict[str, str] = {}
            if ll.get("client"):
                entry["client_url"] = artifact_url(str(SEARCH_ARTIFACT_DIR / ll["client"])) or ""
            if ll.get("broker"):
                entry["broker_url"] = artifact_url(str(SEARCH_ARTIFACT_DIR / ll["broker"])) or ""
            # Krótka wersja klienta (template, niezależna od gen_one)
            short_url = client_short_urls_by_lot_id.get(lot_id)
            if short_url:
                entry["client_short_url"] = short_url
            if entry:
                auto_reports_by_lot_id[lot_id] = entry

        # Loty które miały TYLKO client_short (np. gdy gen_one padł dla nich)
        for lot_id, short_url in client_short_urls_by_lot_id.items():
            if lot_id not in auto_reports_by_lot_id:
                auto_reports_by_lot_id[lot_id] = {"client_short_url": short_url}
    except Exception:
        logger.exception("Building auto_reports_by_lot_id failed")

    notice = analysis_notice(force_local=request.demo)
    if notice_extra:
        notice = (notice + " | " if notice else "") + " ".join(notice_extra)

    # Zero / mało lotów — pomóż userowi zdiagnozować dlaczego.
    if len(all_lots) == 0:
        diag_hints = [
            f"⚠️ 0 lotów dla {criteria.make} {criteria.model or ''}.",
            "Możliwe przyczyny:",
            f"(a) Nazwa modelu nietypowa — Copart/IAAI używa nazw bazowych. "
            f"Spróbuj alternatyw (np. dla BMW: '4 Series' zamiast 'M440i', '8 Series' zamiast 'M850i').",
            f"(b) Okno aukcji {request.auction_min_hours or 12}-{request.auction_max_hours or 120}h "
            f"nie zawiera teraz tego modelu — rozszerz okno (env MAX_AUCTION_WINDOW_HOURS).",
            "(c) Filtr seller_type=insurance ogranicza — wyłącz w env FILTER_SELLER_INSURANCE_ONLY=false.",
        ]
        notice = (notice + " | " if notice else "") + " ".join(diag_hints)
    elif len(all_lots) <= 2:
        notice = (notice + " | " if notice else "") + (
            f"ℹ️ Tylko {len(all_lots)} loty/lotów dla {criteria.make} {criteria.model or ''}. "
            "Sprawdź czy nazwa modelu jest poprawna (Copart/IAAI używa nazw bazowych — "
            "np. '4 Series' zamiast 'M440i')."
        )

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
        client_reports_html=client_reports_html_urls,
        broker_reports_html=broker_reports_html_urls,
        auto_reports_by_lot_id=auto_reports_by_lot_id,
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
            status="done",
            job_id=job.id,  # link do joba dla traceability
        )
        response_payload.record_id = record_id
        response_payload.client_id = client_id
    except Exception:
        logger.exception("Persisting search record failed")
        record_id = None

    # Telegram broadcast — powiadom wszystkich aktywnych subskrybentów
    try:
        from notify.telegram import notify_job_completion, is_configured as _tg_configured
        if _tg_configured():
            polecam_count = sum(
                1 for r in (response_payload.all_results or [])
                if (getattr(r.analysis, "recommendation", "") == "POLECAM")
            )
            ryzyko_count = sum(
                1 for r in (response_payload.all_results or [])
                if (getattr(r.analysis, "recommendation", "") == "RYZYKO")
            )
            duration_s: Optional[float] = None
            try:
                if getattr(job, "created_at", None):
                    created = datetime.fromisoformat(job.created_at)
                    duration_s = max(0.0, (datetime.now() - created).total_seconds())
            except Exception:
                duration_s = None

            bundle_paths = {
                "client_short_bundle": client_short_bundle_file,
                "client_bundle": client_bundle_file,
                "broker_bundle": broker_bundle_file,
            }
            await asyncio.to_thread(
                notify_job_completion,
                status="done",
                title=search_title(criteria),
                record_id=record_id,
                job_id=job.id,
                collected_count=response_payload.collected_count,
                polecam_count=polecam_count,
                ryzyko_count=ryzyko_count,
                duration_seconds=duration_s,
                bundle_paths={k: v for k, v in bundle_paths.items() if v},
            )
    except Exception:
        logger.exception("Telegram broadcast (done) failed — pominięte")

    return response_payload


def _pre_rank_lots_for_ai(lots: list, top_n: int = 10) -> list:
    """Heurystyczny pre-ranking PRZED AI — wybiera top N najbardziej obiecujących lotów.

    Cel: oszczędność tokenów AI. Zamiast wysyłać do Claude'a wszystkie 36 lotów,
    dajemy mu tylko 10 najlepszych po heurystycznym scoringu (damage type, title,
    location, mileage, seller). AI robi pogłębioną analizę tylko tych 10.

    Heuristic NIE używa repair_cost (per user request — auction estimates są nierealne).
    Bazuje na: damage_primary, title_type, location_state, mileage/year, seller_type,
    keys, airbags_deployed.

    Zwraca: posortowana lista CarLot[] (najlepsze pierwsze), maks top_n elementów.
    """
    from parser.models import CarLot

    EASTERN = {"NY", "NJ", "PA", "CT", "MA", "RI", "VT", "NH", "ME", "MD", "DE",
               "VA", "NC", "SC", "GA", "FL"}
    WESTERN = {"CA", "OR", "WA", "NV", "AZ", "UT", "CO", "NM"}

    def lot_score(lot: CarLot) -> float:
        s = 5.0  # base
        damage = (lot.damage_primary or "").lower()
        damage_sec = (lot.damage_secondary or "").lower()
        title = (lot.title_type or "").lower()

        # Damage primary — Flood/Fire = auto-reject (very low score, never in top)
        if "flood" in damage or "water" in damage or "flood" in title:
            return -1000
        if "fire" in damage:
            return -1000

        # Damage severity
        if "frame" in damage or "structural" in damage:
            s -= 2.0
        elif "mechanical" in damage:
            s -= 1.5
        elif "front" in damage:
            s -= 0.3
        elif "rear" in damage:
            s -= 0.2
        elif "side" in damage:
            s -= 0.3
        elif "hail" in damage:
            s += 0.5  # hail is cheap to fix
        elif "minor" in damage or "scratch" in damage or "dent" in damage:
            s += 0.8
        elif "vandalism" in damage:
            s -= 0.4

        # Secondary damage = additional penalty
        if damage_sec and "no" not in damage_sec[:10]:
            s -= 0.2

        # Title type
        if "parts" in title:
            return -1000  # parts only — reject
        elif "clean" in title:
            s += 1.5
        elif "salvage" in title:
            s -= 0.5
        elif "rebuilt" in title:
            s -= 1.5

        # Location (transport cost proxy)
        state = (lot.location_state or "").upper()
        if state in EASTERN:
            s += 1.5
        elif state in WESTERN:
            s -= 1.0

        # Seller type — insurance preferowany (lepsze ceny i dokumentacja)
        if lot.seller_type == "insurance":
            s += 0.5
        elif lot.seller_type == "dealer":
            s -= 0.3

        # Year vs mileage (low mileage = plus)
        if lot.year and lot.odometer_mi:
            age = max(1, 2026 - lot.year)
            avg_per_year = lot.odometer_mi / age
            if avg_per_year < 8000:
                s += 1.0
            elif avg_per_year < 12000:
                s += 0.3
            elif avg_per_year > 20000:
                s -= 0.5

        # Keys + airbags
        if lot.keys is True:
            s += 0.3
        elif lot.keys is False:
            s -= 0.4
        if lot.airbags_deployed is True:
            s -= 0.5

        return s

    scored = [(lot_score(l), l) for l in lots]
    scored.sort(key=lambda x: -x[0])  # desc — najlepsze pierwsze
    top = [l for s, l in scored[:top_n] if s > -100]  # filtr out auto-reject

    logger.info(
        "[pre_rank] %d lots -> top %d (best score: %.1f, worst: %.1f)",
        len(lots), len(top),
        scored[0][0] if scored else 0,
        scored[len(top) - 1][0] if top else 0,
    )
    return top


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


def _save_job_terminal_record(
    request: SearchRequest,
    job: jobs_store.Job,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Zapisuje rekord w app.db.search_records dla joba ktory NIE doszedl do done.

    Dla cancelled/error/interrupted: zapisujemy criteria + status + error,
    bez wynikow scrape (request_data jako request_json, pusty response).

    Dedupping: jesli rekord dla tego job_id juz istnieje, pomijamy (idempotent).
    """
    try:
        from api.client_database import init_db, save_search_record, upsert_client, search_record_exists_for_job
        init_db()
        if search_record_exists_for_job(job.id):
            logger.info("[record] Skip — rekord dla job %s juz istnieje", job.id)
            return
        client_payload = request.client.model_dump(mode="json") if request.client else None
        client_id = upsert_client(client_payload)
        request_dict = request.model_dump(mode="json")
        save_search_record(
            client_id=client_id,
            title=search_title(request.criteria),
            criteria=request.criteria.model_dump(mode="json"),
            request_data=request_dict,
            response_data={"job_id": job.id, "status": status, "error": error},
            artifact_urls={},
            collected_count=0,
            analysis_notice=error,
            notes=(client_payload or {}).get("notes") if client_payload else None,
            status=status,
            job_id=job.id,
        )
        logger.info("[record] Zapisano %s record dla joba %s (criteria: %s)",
                    status, job.id, search_title(request.criteria))
    except Exception:
        logger.exception("[record] Failed to save terminal record for job %s", job.id)

    # Telegram broadcast (cancelled/error/interrupted) — best-effort
    try:
        from notify.telegram import notify_job_completion, is_configured as _tg_configured
        if _tg_configured():
            notify_job_completion(
                status=status,
                title=search_title(request.criteria),
                job_id=job.id,
                error=error,
            )
    except Exception:
        logger.exception("[record] Telegram broadcast (%s) failed", status)


async def _run_job(request: SearchRequest, job: jobs_store.Job) -> None:
    try:
        await jobs_store.mark_running(job)
        response = await _execute_search(request, job)
        await jobs_store.mark_done(job, response.model_dump(mode="json"))
    except asyncio.CancelledError:
        logger.info("Search job %s cancelled", job.id)
        await jobs_store.mark_cancelled(job)
        # Zapisz rekord nawet dla anulowanego joba — user musi widziec w Rekordach
        await asyncio.to_thread(_save_job_terminal_record, request, job, "cancelled", "Anulowane przez uzytkownika")
        # nie podnosimy dalej — task ma się skończyć cicho
    except Exception as exc:
        logger.exception("Search job %s failed", job.id)
        error_msg = f"{exc.__class__.__name__}: {exc}"
        await jobs_store.mark_error(job, error_msg)
        await asyncio.to_thread(_save_job_terminal_record, request, job, "error", error_msg)


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
        # Sync /api/search też przechodzi przez kolejkę — czekaj jeśli inny scrape leci
        job.task = asyncio.create_task(_run_job_with_queue(request, job))
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


PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL", "https://moneybitches.organof.org") or "").rstrip("/")


def _absolute_artifact_url(rel: Optional[str]) -> Optional[str]:
    """Zamienia /artifacts/foo.md -> https://moneybitches.organof.org/artifacts/foo.md"""
    if not rel:
        return None
    if rel.startswith("http"):
        return rel
    if not rel.startswith("/"):
        rel = "/" + rel
    return f"{PUBLIC_BASE_URL}{rel}"


def _job_to_dashboard_dict(job: "jobs_store.Job") -> dict:
    """Spłaszcza Job do shape'u oczekiwanego przez car-auction-buddy frontend.

    TS oczekuje: { status, listings?, error?, progress?, step?, message?, current?, total?, phase? }
    Dodatkowo: artifact_urls + reports z linkami do gotowych raportów wygenerowanych
    przez Pythonowy generator (Markdown + JSON), oraz link do pełnego HTML raportu klient/broker.
    """
    listings: list = []
    analyzed_lots: list = []  # CarLot + AIAnalysis razem (zamiast TS robiło drugą AI analizę)
    auto_reports_by_lot_id: dict = (job.result or {}).get("auto_reports_by_lot_id") or {}
    if job.result:
        for item in (job.result.get("all_results") or []):
            if not isinstance(item, dict):
                continue
            lot = item.get("lot")
            if lot:
                listings.append(lot)
                lot_id = lot.get("lot_id")
                # Pełen AnalyzedLot (lot + analysis + is_top_recommendation)
                analyzed_entry = {
                    "lot": lot,
                    "analysis": item.get("analysis"),
                    "is_top_recommendation": bool(item.get("is_top_recommendation")),
                }
                # Per-lot URLe auto-wygenerowanych raportów (klient + broker hybrid)
                auto_reports = auto_reports_by_lot_id.get(lot_id) or {}
                if auto_reports:
                    # Przepisz na absolute URLs (client_url, broker_url)
                    converted: dict = {}
                    if auto_reports.get("client_url"):
                        converted["client_hybrid_url"] = _absolute_artifact_url(auto_reports["client_url"])
                    if auto_reports.get("broker_url"):
                        converted["broker_hybrid_url"] = _absolute_artifact_url(auto_reports["broker_url"])
                    analyzed_entry["auto_reports"] = converted
                analyzed_lots.append(analyzed_entry)

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

    # Linki do raportów wygenerowanych przy /search
    result = job.result or {}
    raw_artifact_urls = result.get("artifact_urls") or {}
    artifact_urls = {
        k: _absolute_artifact_url(v) for k, v in raw_artifact_urls.items() if v
    }

    # Pełna lista faz dla live progress UI (queue, current step, count per source itp.)
    # Każda faza ma: name, status, info{}, started_at, finished_at
    all_phases = [p.to_dict() for p in job.phases]

    return {
        "status": job.status,
        "listings": listings if job.status == "done" else None,
        # Pełna analiza AI (POLECAM/RYZYKO/ODRZUĆ + score + red_flags + descriptions)
        # już zrobiona po stronie Pythona — TS NIE musi wołać runAnalysis (dublować tokens)
        "analyzed_lots": analyzed_lots if job.status == "done" else None,
        "error": job.error,
        "progress": progress,
        "phase": phase_name,
        "phases": all_phases,  # pełna historia faz (UI może wyświetlać live log)
        "step": phase_info.get("step"),
        "message": phase_info.get("message"),
        "current": current,
        "total": total,
        # Linki do raportów (gotowe pliki Markdown/JSON wygenerowane podczas /search)
        "artifact_urls": artifact_urls,
        # Convenience: główne raporty (auto-generowane po analizie AI dla lotów POLECAM)
        "client_report_url": artifact_urls.get("client_report"),       # Markdown summary
        "polecane_index_url": artifact_urls.get("polecane_index"),     # INDEX wszystkich polecanych (1 plik)
        "client_reports_html": [_absolute_artifact_url(u) for u in (result.get("client_reports_html") or [])],
        "broker_reports_html": [_absolute_artifact_url(u) for u in (result.get("broker_reports_html") or [])],
        # Endpointy do generowania pełnych HTML raportów na żądanie (POST z listą lotów)
        "report_endpoints": {
            "client_html": f"{PUBLIC_BASE_URL}/report/client-html",       # Jinja2 template (zero kosztów)
            "broker_html": f"{PUBLIC_BASE_URL}/report/broker-html",       # Jinja2 template (zero kosztów)
            "client_llm": f"{PUBLIC_BASE_URL}/report/client-llm",         # 🔥 Claude rich (~$0.50/call)
            "broker_llm": f"{PUBLIC_BASE_URL}/report/broker-llm",         # 🔥 Claude rich (~$1/call)
            "offer_email_html": f"{PUBLIC_BASE_URL}/report/offer-email-html",
            "pdf": f"{PUBLIC_BASE_URL}/report",
        },
        "analysis_notice": result.get("analysis_notice"),
        "vin_coverage": result.get("vin_coverage") or {},
    }


@app.get("/api/jobs")
async def list_jobs(
    active_only: bool = True,
    limit: int = 20,
    _auth: None = Depends(_require_bearer),
):
    """Lista aktywnych zadań (lub wszystkich ostatnich) — dla panelu w UI.

    active_only=True (default): tylko running + queued
    active_only=false: ostatnie N jobów (wszystkie statusy)
    """
    if active_only:
        jobs = jobs_store.list_active_jobs()
    else:
        jobs = jobs_store.list_recent_jobs(limit=limit)

    items = []
    for job in jobs:
        # Wyciągnij kryteria z request_snapshot dla czytelnego label
        crit = (job.request_snapshot or {}).get("criteria", {}) if job.request_snapshot else {}
        label_parts = [str(crit.get("make", "?")), str(crit.get("model") or "")]
        budget = crit.get("budget_usd")
        if budget:
            label_parts.append(f"${int(budget):,}")
        label = " ".join(p for p in label_parts if p).strip()

        # Najnowsza faza dla statusu / progressu
        latest_phase = job.phases[-1] if job.phases else None
        is_queued = (latest_phase and latest_phase.name == "queued")
        items.append({
            "id": job.id,
            "status": "queued" if is_queued and job.status == "running" else job.status,
            "label": label or "?",
            "criteria": crit,
            "created_at": job.created_at,
            "finished_at": job.finished_at,
            "phase": latest_phase.name if latest_phase else None,
            "phase_status": latest_phase.status if latest_phase else None,
            "phase_info": latest_phase.info if latest_phase else {},
            # Pełna lista faz — UI renderuje live timeline w panelu Aktywnych Zadań
            "phases": [p.to_dict() for p in job.phases],
            "cancel_requested": job.cancel_requested,
            "error": job.error,
            "listings_count": len((job.result or {}).get("all_results") or []) if job.status == "done" else 0,
        })
    return {"jobs": items, "total": len(items)}


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


# Kolejkowanie scrape jobów: max 1 jednocześnie (Playwright + Chrome to ciężki proces,
# multiple = OOM, slow downloads, race conditions na sesji). Każdy job czeka w kolejce
# aż poprzedni skończy. Override przez SEARCH_MAX_CONCURRENT.
_SEARCH_MAX_CONCURRENT = int(os.getenv("SEARCH_MAX_CONCURRENT", "1"))
_search_semaphore: Optional[asyncio.Semaphore] = None


def _get_search_semaphore() -> asyncio.Semaphore:
    """Lazy init semafora — asyncio.Semaphore() musi być w event loop."""
    global _search_semaphore
    if _search_semaphore is None:
        _search_semaphore = asyncio.Semaphore(_SEARCH_MAX_CONCURRENT)
    return _search_semaphore


async def _run_job_with_queue(request: SearchRequest, job: jobs_store.Job) -> None:
    """Wrapper na _run_job z semaforem — kolejkuje gdy inny job leci."""
    semaphore = _get_search_semaphore()
    if semaphore.locked():
        logger.info("[/search] Job %s czeka w kolejce (max %d concurrent)", job.id, _SEARCH_MAX_CONCURRENT)
        try:
            from api.jobs import Phase
            from datetime import datetime as _dt
            # Job status = "queued", oddzielna faza pokazuje to w panelu
            job.status = "queued"
            queue_phase = Phase(name="queued", status="running", info={"reason": "max_concurrent_reached"})
            job.phases.append(queue_phase)
        except Exception:
            pass
    async with semaphore:
        # Po zwolnieniu semafora — oznacz fazę queued jako done, status=running idzie ze _run_job
        try:
            for ph in job.phases:
                if ph.name == "queued" and ph.status == "running":
                    ph.status = "done"
        except Exception:
            pass
        await _run_job(request, job)


class BatchSearchRequest(BaseModel):
    """Lista wyszukiwań do wykonania sekwencyjnie (Python kolejkuje przez Semaphore)."""
    searches: list[SearchRequest]


@app.post("/api/search/batch", status_code=202)
async def dashboard_batch_search(
    request: BatchSearchRequest,
    _auth: None = Depends(_require_bearer),
):
    """Multi-car batch: tworzy N jobów na raz, Python kolejkuje przez Semaphore=1.

    Body: { "searches": [SearchRequest, SearchRequest, ...] }
    Response 202: {
      "jobs": [
        { "job_id": "abc", "status_url": "/search/jobs/abc", "stream_url": "/search/stream/abc",
          "label": "BMW M5 2018-2020", "idempotent": false },
        ...
      ],
      "queued_count": 4
    }

    Każdy element listy:
    - Idempotency check: jeśli identyczny scrape leci/leciał w TTL → zwraca ten sam job_id (idempotent: true)
    - Inaczej: tworzy nowy job, dodaje do kolejki Pythona

    UI po otrzymaniu N jobIds poll'uje każdy osobno przez /api/jobs/{id}
    (lub całość przez /api/jobs?active_only=true) i wyświetla live timeline.
    """
    if not request.searches:
        raise HTTPException(status_code=400, detail="Lista searches nie może być pusta")
    if len(request.searches) > 20:
        raise HTTPException(status_code=400, detail="Maks. 20 wyszukiwań w batchu")

    results = []
    for sub_request in request.searches:
        criteria = sub_request.criteria
        label_parts = [criteria.make, criteria.model or ""]
        if criteria.year_from:
            label_parts.append(f"{criteria.year_from}-{criteria.year_to or '?'}")
        label = " ".join(p for p in label_parts if p).strip()

        criteria_hash = _compute_criteria_hash(sub_request)
        reused = jobs_store.find_reusable_job(criteria_hash, IDEMPOTENCY_TTL_SECONDS)

        if reused is not None and reused.status in ("running", "done"):
            results.append({
                "job_id": reused.id,
                "status_url": f"/search/jobs/{reused.id}",
                "stream_url": f"/search/stream/{reused.id}",
                "cancel_url": f"/search/jobs/{reused.id}",
                "label": label,
                "idempotent": True,
                "reused_status": reused.status,
            })
            continue

        job = jobs_store.create_job(
            criteria_hash=criteria_hash,
            request_snapshot=sub_request.model_dump(mode="json"),
        )
        job.task = asyncio.create_task(_run_job_with_queue(sub_request, job))
        results.append({
            "job_id": job.id,
            "status_url": f"/search/jobs/{job.id}",
            "stream_url": f"/search/stream/{job.id}",
            "cancel_url": f"/search/jobs/{job.id}",
            "label": label,
            "idempotent": False,
        })

    logger.info("Batch search: zakolejkowano %d jobów (z %d zaplanowanych)", len(results), len(request.searches))
    return {"jobs": results, "queued_count": len(results)}


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
    # _run_job_with_queue: kolejkuje gdy inny scrape już leci (max SEARCH_MAX_CONCURRENT=1)
    job.task = asyncio.create_task(_run_job_with_queue(request, job))
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


def _make_artifact_urls_absolute(record: dict) -> dict:
    """Konwertuje relatywne /artifacts/... URLe w rekordzie na absolutne.

    Backend zapisuje URLe jako '/artifacts/<filename>' w bazie. UI Lovable
    klei to do SWOJEJ domeny → 404. Po stronie API zwracamy absolutne URLe
    (tak jak robi _absolute_artifact_url() w /api/jobs/).
    """
    if not record:
        return record
    # Top-level artifact_urls
    aurls = record.get("artifact_urls")
    if isinstance(aurls, dict):
        record["artifact_urls"] = {
            k: _absolute_artifact_url(v) if v else v for k, v in aurls.items()
        }
    # response.artifact_urls (jeśli zagnieżdżone)
    resp = record.get("response")
    if isinstance(resp, dict):
        nested = resp.get("artifact_urls")
        if isinstance(nested, dict):
            resp["artifact_urls"] = {
                k: _absolute_artifact_url(v) if v else v for k, v in nested.items()
            }
        # client_reports_html / broker_reports_html (listy URLi per lot)
        for key in ("client_reports_html", "broker_reports_html"):
            urls = resp.get(key)
            if isinstance(urls, list):
                resp[key] = [_absolute_artifact_url(u) for u in urls if u]
        # auto_reports_by_lot_id (dict {lot_id: {client_url, broker_url}})
        auto = resp.get("auto_reports_by_lot_id")
        if isinstance(auto, dict):
            for lot_id, urls in auto.items():
                if isinstance(urls, dict):
                    auto[lot_id] = {
                        k: _absolute_artifact_url(v) if v else v for k, v in urls.items()
                    }
    return record


@app.get("/records")
async def list_client_records(
    query: Optional[str] = None,
    limit: int = 50,
    status: Optional[str] = None,
):
    """Lista rekordów wyszukiwań (legacy alias bez auth dla starych klientów)."""
    from api.client_database import list_records
    records = list_records(query=query, limit=limit)
    if status:
        records = [r for r in records if (r.get("status") or "").lower() == status.lower()]
    records = [_make_artifact_urls_absolute(r) for r in records]
    return {"records": records}


@app.get("/api/records")
async def api_list_client_records(
    query: Optional[str] = None,
    limit: int = 50,
    status: Optional[str] = None,
    _auth: None = Depends(_require_bearer),
):
    """Główny endpoint dla UI dashboardu (Bearer auth).

    Zwraca rekordy WSZYSTKICH wyszukiwań z ABSOLUTNYMI URLami artifacts.
    """
    from api.client_database import list_records
    records = list_records(query=query, limit=limit)
    if status:
        records = [r for r in records if (r.get("status") or "").lower() == status.lower()]
    records = [_make_artifact_urls_absolute(r) for r in records]
    return {"records": records, "total": len(records)}


@app.get("/records/{record_id}")
async def get_client_record(record_id: int):
    from api.client_database import get_record

    record = get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekordu")
    return _make_artifact_urls_absolute(record)


@app.get("/api/records/{record_id}")
async def api_get_client_record(record_id: int, _auth: None = Depends(_require_bearer)):
    """Szczegóły pojedynczego rekordu (Bearer auth) z absolutnymi URLami."""
    from api.client_database import get_record
    record = get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekordu")
    return _make_artifact_urls_absolute(record)


@app.delete("/api/records/{record_id}")
async def delete_client_record(
    record_id: int,
    delete_files: bool = True,
    _auth: None = Depends(_require_bearer),
):
    """Usuwa rekord wyszukiwania z bazy + powiązane artefakty z dysku.

    Query:
        ?delete_files=true (default) — usuwa też pliki bundle/raporty z client_searches/
                          false — zostawia pliki na dysku (tylko DB cleanup)

    Pliki do usunięcia są wyznaczane na podstawie:
    1. artifact_urls (bundle, polecane_index, ai_input/prompt/analysis)
    2. response.auto_reports_by_lot_id (per-lot URL-e)
    3. wszystkie pliki w SEARCH_ARTIFACT_DIR które dzielą wspólny prefix slug
       (np. `bmw_m5_insurance_20260509_164356`) — to chwyta per-lot raporty
       generowane podczas scrape (top1_*, top2_*, etc.)

    NIE usuwa wpisów llm_cache (skeletony są reusable dla innych rekordów z
    tym samym lot_id i mają TTL 24h).

    Returns: { deleted: true, record_id, files_removed, bytes_freed }
    """
    import re
    from api.client_database import delete_record

    deleted = delete_record(record_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekordu")

    files_removed = 0
    bytes_freed = 0
    skipped: list[str] = []

    if delete_files:
        artifact_urls = deleted.get("artifact_urls") or {}
        response = deleted.get("response") or {}

        # 1. Bezpośrednie filenames z artifact_urls
        filenames: set[str] = set()
        for url in artifact_urls.values():
            if url and isinstance(url, str) and "/artifacts/" in url:
                filenames.add(url.split("/artifacts/")[-1].split("?")[0])

        # 2. Per-lot URL-e z auto_reports_by_lot_id
        auto_reports = (response.get("auto_reports_by_lot_id") or {})
        for lot_reports in auto_reports.values():
            if not isinstance(lot_reports, dict):
                continue
            for url in lot_reports.values():
                if url and isinstance(url, str) and "/artifacts/" in url:
                    filenames.add(url.split("/artifacts/")[-1].split("?")[0])

        # 3. Wykryj slug prefix (np. "bmw_m5_insurance_20260509_164356") z artifact_urls
        # i dorzuć wszystkie pliki w katalogu pasujące do tego prefiksu (per-lot raporty
        # nie zawsze są w artifact_urls, np. top1_lotid_klient_krotki.html).
        prefixes: set[str] = set()
        for url in artifact_urls.values():
            if url and isinstance(url, str) and "/artifacts/" in url:
                fname = url.split("/artifacts/")[-1].split("?")[0]
                # Pattern: {slug}_{ts}_{kind}.{ext} albo {slug}_{ts1}_{ts2}_{kind}.{ext}
                # Slug = make_model_insurance_TS  (TS to YYYYMMDD_HHMMSS = 15 znaków)
                m = re.match(r'^([a-z0-9_]+_insurance_\d{8}_\d{6})', fname)
                if m:
                    prefixes.add(m.group(1))
                # Też: regen pattern → "audi_regen_65_..."
                m2 = re.match(r'^([a-z0-9_]+_regen_\d+)_', fname)
                if m2:
                    prefixes.add(m2.group(1))

        for prefix in prefixes:
            for fname in os.listdir(SEARCH_ARTIFACT_DIR):
                if fname.startswith(prefix):
                    filenames.add(fname)

        # 4. Usuń pliki (only z SEARCH_ARTIFACT_DIR — defensywnie ignoruj absolute paths)
        for fname in filenames:
            # Sanityzacja: tylko nazwa pliku, bez ../../ etc.
            if "/" in fname or "\\" in fname or fname.startswith("."):
                skipped.append(fname)
                continue
            fpath = SEARCH_ARTIFACT_DIR / fname
            if fpath.exists() and fpath.is_file():
                try:
                    bytes_freed += fpath.stat().st_size
                    fpath.unlink()
                    files_removed += 1
                except Exception:
                    logger.exception("Failed to delete %s", fpath)
                    skipped.append(fname)

    logger.info("[delete_record] #%d → DB row removed, %d files removed (%d bytes)",
                record_id, files_removed, bytes_freed)
    return {
        "deleted": True,
        "record_id": record_id,
        "files_removed": files_removed,
        "bytes_freed": bytes_freed,
        "skipped": skipped if skipped else None,
    }


@app.post("/api/records/{record_id}/regenerate-bundles")
async def regenerate_record_bundles(
    record_id: int,
    engine: str = "template",
    kinds: Optional[str] = None,
    _auth: None = Depends(_require_bearer),
):
    """Re-renderuje zbiorcze bundle (klient + broker) dla istniejącego rekordu.

    Przydatne gdy zmieniliśmy layout `_bundle_html` (np. dodaliśmy sidebar)
    i chcemy przebudować bundle dla starych rekordów BEZ ponownego scrape'a.

    Query:
        ?engine=template (default — szybki Jinja2 ~1s)
              =hybrid (Gemini+Otomoto, ~30s/lot lub cache HIT)
        ?kinds=client,broker (default oba)

    Process:
    1. Pobiera rekord z app.db.search_records
    2. Wyciąga showcase loty (is_top_recommendation=true) z response_json
    3. Per kind (client/broker): renderuje per-lot przez engine + buduje bundle
       z nowym _bundle_html() (sidebar layout)
    4. Nadpisuje istniejące pliki bundle na dysku (lub tworzy nowe)
    5. Aktualizuje artifact_urls w bazie

    Returns: { client_bundle: url, broker_bundle: url, generated: [...] }
    """
    from api.client_database import get_record, update_artifact_urls
    from parser.models import AnalyzedLot, ClientCriteria

    record = get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekordu")

    response = record.get("response") or {}
    all_results_raw = response.get("all_results") or []
    showcase_raw = [al for al in all_results_raw if al.get("is_top_recommendation")]
    if not showcase_raw:
        raise HTTPException(status_code=400, detail="Rekord nie ma showcase'ów (is_top_recommendation=true)")

    # Zrekonstruuj AnalyzedLot z dict
    try:
        showcase = [AnalyzedLot(**al) for al in showcase_raw]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Niepoprawny showcase data: {exc}") from exc

    criteria_dict = record.get("criteria") or {}
    try:
        criteria = ClientCriteria(**criteria_dict) if criteria_dict.get("make") else None
    except Exception:
        criteria = None

    eng = (engine or "template").lower()
    requested_kinds = set((kinds or "client,broker").lower().split(","))

    title_meta = (criteria.make if criteria else "")
    if criteria and criteria.model:
        title_meta += f" {criteria.model}"

    result_urls: dict[str, str] = {}
    generated: list[str] = []

    # Wyznacz slug + ts dla nazwy pliku — z istniejących artifact_urls jeśli są
    existing_urls = record.get("artifact_urls") or {}
    existing_client = existing_urls.get("client_bundle") or ""
    existing_client_short = existing_urls.get("client_short_bundle") or ""
    existing_broker = existing_urls.get("broker_bundle") or ""

    def _filename_from_url(url: str, kind: str) -> str:
        """Wyciąga nazwę pliku z URL (jeśli była). Else generuje nową."""
        if url:
            try:
                return url.split("/artifacts/")[-1].split("?")[0]
            except Exception:
                pass
        # Fallback: nowa nazwa
        slug = (criteria.make.lower() if criteria else "rec") + "_regen"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{slug}_{record_id}_{ts}_zbiorczy_{kind}.html"

    # ─── PARALLEL FAN-OUT ─────────────────────────────────────────────────
    # Zamiast 4 sekwencyjnych pętli (klient_bundle, klient_short_bundle, broker_bundle,
    # per-lot klient_short) puszczamy wszystkie tasks naraz. LLM calls są bramkowane
    # semaforem (LLM_REPORTS_CONCURRENCY), template renderery (klient_short) idą bez bramki.
    # Wzorzec analogiczny do scrape pipeline (api/main.py:530+) — eliminuje 50-60% wall-clock.
    llm_concurrency = int(os.getenv("LLM_REPORTS_CONCURRENCY", "2"))
    llm_sem = asyncio.Semaphore(llm_concurrency)

    async def _render_llm(fn, item):
        async with llm_sem:
            return await asyncio.to_thread(fn, item)

    async def _render_template(fn, item):
        return await asyncio.to_thread(fn, item)

    showcase_polecam = [item for item in showcase if item.analysis.recommendation == "POLECAM"]

    # Wybór rendererów per kind
    client_renderer = None
    broker_renderer = None
    client_uses_llm = False
    broker_uses_llm = False
    if "client" in requested_kinds:
        if eng == "hybrid":
            from report.hybrid_reports import render_client_hybrid
            client_renderer = lambda it: render_client_hybrid(it, criteria)
            client_uses_llm = True
        else:
            from report.html_reports import render_client_report as _rcr
            client_renderer = lambda it: _rcr(it, criteria)
            client_uses_llm = False
    if "broker" in requested_kinds:
        lots_scanned = response.get("collected_count") or len(all_results_raw)
        if eng == "hybrid":
            from report.hybrid_reports import render_broker_hybrid
            broker_renderer = lambda it: render_broker_hybrid(it, criteria, lots_scanned=lots_scanned)
            broker_uses_llm = True
        else:
            from report.html_reports import render_broker_report as _rbr
            broker_renderer = lambda it: _rbr(it, criteria, lots_scanned=lots_scanned)
            broker_uses_llm = False
    # Template renderer dla zbiorczego krótkiego klienta + per-lot krótkiego (zawsze Jinja2, no LLM)
    from report.html_reports import render_client_report as _render_client_template
    short_renderer = lambda it: _render_client_template(it, criteria)

    # Build coroutines
    client_coros: list = []
    short_bundle_coros: list = []
    broker_coros: list = []
    per_lot_short_coros: list = []

    if client_renderer is not None:
        for it in showcase_polecam:
            client_coros.append(_render_llm(client_renderer, it) if client_uses_llm else _render_template(client_renderer, it))
        for it in showcase_polecam:
            short_bundle_coros.append(_render_template(short_renderer, it))
    if broker_renderer is not None:
        for it in showcase:
            broker_coros.append(_render_llm(broker_renderer, it) if broker_uses_llm else _render_template(broker_renderer, it))
    # Per-lot client_short (zawsze, dla całego showcase — niezależne od kinds, bo ma osobny URL per-lot)
    for it in showcase:
        per_lot_short_coros.append(_render_template(short_renderer, it))

    # Run all in parallel — semaphore bramkuje tylko LLM calls
    all_coros = client_coros + short_bundle_coros + broker_coros + per_lot_short_coros
    all_results = await asyncio.gather(*all_coros, return_exceptions=True) if all_coros else []
    nC = len(client_coros)
    nS = len(short_bundle_coros)
    nB = len(broker_coros)
    client_results = all_results[:nC]
    short_results = all_results[nC:nC + nS]
    broker_results = all_results[nC + nS:nC + nS + nB]
    per_lot_results = all_results[nC + nS + nB:]

    def _meta(item):
        return {
            "recommendation": item.analysis.recommendation,
            "score": item.analysis.score,
            "lot_id": item.lot.lot_id,
        }

    def _label(item):
        return f"{item.lot.year or '?'} {item.lot.make or ''} {item.lot.model or ''} (#{item.lot.lot_id})".strip()

    # ── Bundle: KLIENT pełny ──
    if client_renderer is not None:
        htmls = []
        for it, res in zip(showcase_polecam, client_results):
            if isinstance(res, Exception):
                logger.exception("Regen client failed for lot %s: %s", it.lot.lot_id, res)
                continue
            htmls.append((_label(it), res, _meta(it)))
        if htmls:
            htmls.sort(key=lambda x: -(x[2].get("score") or 0))
            bundle_title = f"Raport zbiorczy klienta — {len(htmls)} aut POLECAM ({title_meta})"
            bundle = _bundle_html(htmls, bundle_title)
            fname = _filename_from_url(existing_client, "klient")
            fpath = SEARCH_ARTIFACT_DIR / fname
            fpath.write_text(bundle, encoding="utf-8")
            result_urls["client_bundle"] = _absolute_artifact_url(f"/artifacts/{fname}")
            generated.append(f"client ({len(htmls)} lotów POLECAM, {len(bundle)//1024} KB)")
            logger.info("[regen] client bundle (POLECAM only) for record #%d -> %s", record_id, fname)

        # ── Bundle: KLIENT krótki zbiorczy ──
        short_htmls = []
        for it, res in zip(showcase_polecam, short_results):
            if isinstance(res, Exception):
                logger.exception("Regen client_short bundle failed for lot %s: %s", it.lot.lot_id, res)
                continue
            short_htmls.append((_label(it), res, _meta(it)))
        if short_htmls:
            short_htmls.sort(key=lambda x: -(x[2].get("score") or 0))
            bundle_title = f"Raport krótki zbiorczy klienta — {len(short_htmls)} aut POLECAM ({title_meta})"
            bundle = _bundle_html(short_htmls, bundle_title)
            fname = _filename_from_url(existing_client_short, "klient_krotki")
            fpath = SEARCH_ARTIFACT_DIR / fname
            fpath.write_text(bundle, encoding="utf-8")
            result_urls["client_short_bundle"] = _absolute_artifact_url(f"/artifacts/{fname}")
            generated.append(f"client_short_bundle ({len(short_htmls)} lotów POLECAM, {len(bundle)//1024} KB)")
            logger.info("[regen] client_short_bundle for record #%d -> %s", record_id, fname)

    # ── Bundle: BROKER ──
    if broker_renderer is not None:
        htmls_b = []
        for it, res in zip(showcase, broker_results):
            if isinstance(res, Exception):
                logger.exception("Regen broker failed for lot %s: %s", it.lot.lot_id, res)
                continue
            htmls_b.append((_label(it), res, _meta(it)))
        if htmls_b:
            order = {"POLECAM": 0, "RYZYKO": 1, "ODRZUĆ": 2}
            htmls_b.sort(key=lambda x: (order.get(x[2].get("recommendation", ""), 99), -(x[2].get("score") or 0)))
            bundle_title = f"Raport brokerski zbiorczy — {len(htmls_b)} aut ({title_meta})"
            bundle = _bundle_html(htmls_b, bundle_title)
            fname = _filename_from_url(existing_broker, "broker")
            fpath = SEARCH_ARTIFACT_DIR / fname
            fpath.write_text(bundle, encoding="utf-8")
            result_urls["broker_bundle"] = _absolute_artifact_url(f"/artifacts/{fname}")
            generated.append(f"broker ({len(htmls_b)} lotów, {len(bundle)//1024} KB)")
            logger.info("[regen] broker bundle for record #%d -> %s", record_id, fname)

    # ── PER-LOT KRÓTKI KLIENT (template Jinja2, ~13ms/lot) ──
    try:
        from api.client_database import get_record as _get_record
        rec = _get_record(record_id)
        existing_auto = (rec.get("response") or {}).get("auto_reports_by_lot_id") or {}
        short_count = 0
        for idx, (it, res) in enumerate(zip(showcase, per_lot_results), 1):
            if isinstance(res, Exception):
                logger.exception("Regen short client report failed for lot %s: %s", it.lot.lot_id, res)
                continue
            try:
                lot_id_safe = (it.lot.lot_id or f"lot{idx}").replace("/", "_")
                fname = f"{(criteria.make or 'rec').lower()}_regen_{record_id}_top{idx}_{lot_id_safe}_klient_krotki.html"
                fpath = SEARCH_ARTIFACT_DIR / fname
                fpath.write_text(res, encoding="utf-8")
                if it.lot.lot_id:
                    if it.lot.lot_id not in existing_auto:
                        existing_auto[it.lot.lot_id] = {}
                    existing_auto[it.lot.lot_id]["client_short_url"] = "/artifacts/" + fname
                short_count += 1
            except Exception:
                logger.exception("Regen short client write failed for lot %s", it.lot.lot_id)
        if short_count:
            generated.append(f"client_short ({short_count} lotów, template)")
            logger.info("[regen] client_short for record #%d: %d lotów", record_id, short_count)
            try:
                from api.client_database import _connect, _now
                import json as _j
                with _connect() as conn:
                    row = conn.execute("SELECT response_json FROM search_records WHERE id = ?", (record_id,)).fetchone()
                    if row:
                        resp = _j.loads(row["response_json"] or "{}")
                        resp["auto_reports_by_lot_id"] = existing_auto
                        conn.execute(
                            "UPDATE search_records SET response_json = ?, updated_at = ? WHERE id = ?",
                            (_j.dumps(resp, ensure_ascii=False), _now(), record_id),
                        )
            except Exception:
                logger.exception("Failed to update auto_reports_by_lot_id in DB")
    except Exception:
        logger.exception("Regen client_short batch failed")

    if not result_urls and not generated:
        raise HTTPException(status_code=502, detail="Re-render się nie udał (nie wygenerowano żadnego bundle ani short)")

    # Update artifact_urls w bazie (relatywne URLe — _make_artifact_urls_absolute zrobi z nich abs przy GET)
    relative_urls = {}
    for k, v in result_urls.items():
        relative_urls[k] = "/artifacts/" + v.split("/artifacts/")[-1] if v else None
    if relative_urls:
        update_artifact_urls(record_id, relative_urls)

    return {
        "record_id": record_id,
        "engine": eng,
        "generated": generated,
        **result_urls,  # client_bundle / broker_bundle (absolute URLs)
    }


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


def _bundle_html(htmls: list[tuple], title: str) -> str:
    """Skleja N raportów HTML w jeden zbiorczy z LEFT SIDEBAR (sticky) + TAB view.

    Layout:
    - Lewy sidebar (sticky, scrollable) — lista aut z badge'em recommendation
    - Prawy panel — pokazuje TYLKO 1 raport na raz (klik w sidebar = przełącza)
    - POLECAM = zielony badge, RYZYKO = żółty, ODRZUĆ = czerwony, ? = szary
    - Print: wszystkie sekcje na osobnych stronach (page-break)

    Args:
        htmls: lista tuples (label, html, meta_dict_optional)
            - label: str — wyświetlana nazwa np. "2024 Honda CR-V EX (#45069439)"
            - html: str — pełny HTML raportu (z <html>...<body>...)
            - meta: dict (opcjonalnie) — {recommendation: 'POLECAM'|..., score: float, lot_id: str}
        title: tytuł całego bundla

    Returns:
        Pełny HTML z layoutem aplikacyjnym (sidebar + main content).
    """
    import re as _re

    # Normalizacja: wszystkie elementy do tuple (label, html, meta)
    normalized = []
    for entry in htmls:
        if len(entry) == 2:
            normalized.append((entry[0], entry[1], {}))
        elif len(entry) >= 3:
            normalized.append((entry[0], entry[1], entry[2] or {}))

    def _badge_color(rec: str) -> tuple[str, str]:
        """Zwraca (background-color, label) dla recommendation."""
        rec_low = (rec or "").upper()
        if "POLECAM" in rec_low:
            return ("#22c55e", "✅ POLECAM")
        if "RYZYKO" in rec_low:
            return ("#eab308", "⚠️ RYZYKO")
        if "ODRZUĆ" in rec_low or "ODRZUC" in rec_low:
            return ("#ef4444", "❌ ODRZUĆ")
        return ("#6b7280", "?")

    parts = [
        "<!DOCTYPE html>",
        "<html lang='pl'>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        f"<title>{title}</title>",
        "<style>",
        # Reset + globalne
        "  * { box-sizing: border-box; }",
        "  body { margin: 0; font-family: 'Segoe UI',-apple-system,BlinkMacSystemFont,sans-serif; background: #0d1117; }",
        # Layout: flex sidebar + main
        "  .bundle-app { display: flex; min-height: 100vh; }",
        # Sidebar
        "  .bundle-sidebar { width: 320px; flex-shrink: 0; background: #161b22; color: #e6edf3;",
        "    border-right: 1px solid #30363d; height: 100vh; position: sticky; top: 0;",
        "    overflow-y: auto; padding: 24px 18px; }",
        "  .bundle-sidebar h1 { font-size: 18px; margin: 0 0 6px; color: #fff; line-height: 1.3; }",
        "  .bundle-sidebar .meta { font-size: 11px; color: #7d8590; margin-bottom: 20px; }",
        "  .bundle-sidebar .nav-list { list-style: none; padding: 0; margin: 0; }",
        "  .bundle-sidebar .nav-item { padding: 10px 12px; border-radius: 8px; cursor: pointer;",
        "    margin-bottom: 6px; transition: background 0.15s; border: 1px solid transparent; }",
        "  .bundle-sidebar .nav-item:hover { background: #1f2937; }",
        "  .bundle-sidebar .nav-item.active { background: rgba(88,166,255,0.15); border-color: #58a6ff; }",
        "  .bundle-sidebar .nav-num { font-size: 10px; color: #7d8590; margin-bottom: 2px; }",
        "  .bundle-sidebar .nav-label { font-size: 13px; color: #e6edf3; line-height: 1.35; }",
        "  .bundle-sidebar .nav-badge { display: inline-block; padding: 2px 8px; border-radius: 99px;",
        "    font-size: 10px; font-weight: 700; color: #fff; margin-top: 4px; letter-spacing: 0.5px; }",
        # Main content
        "  .bundle-main { flex: 1; min-width: 0; }",
        "  .lot-section { display: none; }",
        "  .lot-section.active { display: block; }",
        # Print mode — pokazuj wszystko, ukryj sidebar
        "  @media print {",
        "    .bundle-sidebar { display: none !important; }",
        "    .lot-section { display: block !important; page-break-before: always; }",
        "    .lot-section:first-of-type { page-break-before: auto; }",
        "    .bundle-app { display: block; }",
        "  }",
        "</style>",
        "</head>",
        "<body>",
        "<div class='bundle-app'>",
        # Sidebar
        "<aside class='bundle-sidebar'>",
        f"<h1>📋 {title}</h1>",
        f"<div class='meta'>Wygenerowano: {datetime.now().strftime('%Y-%m-%d %H:%M')} · {len(normalized)} aut</div>",
        "<ul class='nav-list'>",
    ]

    for idx, (label, _html, meta) in enumerate(normalized, 1):
        rec = meta.get("recommendation", "")
        score = meta.get("score")
        bg_color, badge_label = _badge_color(rec)
        score_str = f" · {score:.1f}/10" if score is not None else ""
        active_cls = " active" if idx == 1 else ""

        parts.append(
            f"<li class='nav-item{active_cls}' data-lot-idx='{idx}' onclick=\"showLot({idx})\">"
            f"<div class='nav-num'>#{idx}</div>"
            f"<div class='nav-label'>{label}</div>"
            f"<span class='nav-badge' style='background:{bg_color}'>{badge_label}{score_str}</span>"
            f"</li>"
        )

    parts.append("</ul></aside>")

    # Main content area
    parts.append("<main class='bundle-main'>")
    for idx, (label, html, _meta) in enumerate(normalized, 1):
        body_match = _re.search(r"<body[^>]*>(.*?)</body>", html, _re.DOTALL | _re.IGNORECASE)
        body_content = body_match.group(1) if body_match else html

        style_match = _re.search(r"<style[^>]*>(.*?)</style>", html, _re.DOTALL | _re.IGNORECASE)
        scoped_style = f"<style>\n{style_match.group(1)}\n</style>" if style_match else ""

        active_cls = " active" if idx == 1 else ""
        parts.append(
            f"<section id='lot-{idx}' class='lot-section{active_cls}'>{scoped_style}{body_content}</section>"
        )
    parts.append("</main>")
    parts.append("</div>")  # bundle-app

    # JavaScript do przełączania
    parts.append("""
<script>
function showLot(idx) {
  document.querySelectorAll('.lot-section').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  const target = document.getElementById('lot-' + idx);
  const nav = document.querySelector(`.nav-item[data-lot-idx="${idx}"]`);
  if (target) target.classList.add('active');
  if (nav) nav.classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
  // Update URL hash dla bookmarkable links
  history.replaceState(null, '', '#lot-' + idx);
}
// Init: jeśli URL ma #lot-N, otwórz tę sekcję
window.addEventListener('DOMContentLoaded', () => {
  const m = (window.location.hash || '').match(/^#lot-(\\d+)$/);
  if (m) showLot(parseInt(m[1], 10));
});
</script>""")

    parts.append("</body></html>")
    return "\n".join(parts)


# USUNIETE w 2026-05-07: /report/client-bundle i /report/broker-bundle (Rich on-demand)
# Per user decision — broker dostaje zbiorczy auto (zawiera wszystkie showcase),
# nie trzeba on-demand z wybranych. Klient dostaje zbiorczy auto z TYLKO POLECAM.
# Workflow: scrape -> auto-bundle -> broker przegląda -> wysyła klientowi link
# do auto-bundle klienta (już wyfiltrowany do POLECAM).


def _llm_engine() -> str:
    """'hybrid' (domyślne, ~30× taniej) lub 'legacy' (full HTML LLM)."""
    return (os.getenv("LLM_REPORTS_ENGINE", "hybrid") or "hybrid").lower()


@app.post("/report/client-llm")
async def generate_client_llm_report(request: ApproveReportRequest):
    """Rich raport klienta. Engine: 'hybrid' (default, ~$0.014) lub 'legacy' (~$0.50)."""
    from fastapi.responses import HTMLResponse

    lots_for_report = [lot for lot in request.approved_lots if lot.included_in_report]
    if not lots_for_report:
        raise HTTPException(status_code=400, detail="Brak lotów")

    if _llm_engine() == "hybrid":
        from report.hybrid_reports import render_client_hybrid
        html = await asyncio.to_thread(render_client_hybrid, lots_for_report[0], request.criteria)
    else:
        from report.llm_html_reports import render_client_report_llm
        html = await asyncio.to_thread(render_client_report_llm, lots_for_report[0], request.criteria)
    return HTMLResponse(content=html)


@app.post("/report/broker-llm")
async def generate_broker_llm_report(request: ApproveReportRequest):
    """Rich raport brokerski. Engine: 'hybrid' (default, ~$0.027) lub 'legacy' (~$1)."""
    from fastapi.responses import HTMLResponse

    lots_for_report = [lot for lot in request.approved_lots if lot.included_in_report]
    if not lots_for_report:
        raise HTTPException(status_code=400, detail="Brak lotów")

    if _llm_engine() == "hybrid":
        from report.hybrid_reports import render_broker_hybrid
        html = await asyncio.to_thread(
            render_broker_hybrid, lots_for_report[0], request.criteria, len(request.approved_lots),
        )
    else:
        from report.llm_html_reports import render_broker_report_llm
        html = await asyncio.to_thread(
            render_broker_report_llm, lots_for_report[0], request.criteria, len(request.approved_lots),
        )
    return HTMLResponse(content=html)


class ParseClientMessageRequest(BaseModel):
    """Wiadomość od klienta do sparsowania na ClientCriteria."""
    message: str


@app.post("/api/parse-client-message")
async def parse_client_message_endpoint(
    request: ParseClientMessageRequest,
    _auth: None = Depends(_require_bearer),
):
    """LLM parser wiadomości klienta -> lista ClientCriteria + summary + warnings.

    Body: {message: "Szukam BMW M5 z 2018-2020 lub Audi S5 2019-2023..."}
    Response: {
        criteria_list: [{...}, {...}],   # 1+ aut z wiadomości
        criteria: {...},                  # backwards compat: criteria_list[0]
        count: 2,
        summary: "Klient wymienił 2 auta: BMW M5, Audi S5",
        warnings: ["Brak budżetu dla wszystkich aut"]
    }

    Errors:
        400 — pusta wiadomość lub żadnego auta nie wyłapano
        422 — sparsowane criteria nie przeszły walidacji Pydantic
        503 — wszyscy LLM providery padli
    """
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Wiadomość nie może być pusta")

    from ai.message_parser import parse_client_message

    try:
        parsed = await asyncio.to_thread(parse_client_message, request.message)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"LLM niedostępny: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    summary = parsed.pop("_summary", "")
    warnings = parsed.pop("_warnings", []) or []

    # Multi-cars: parser zwraca {cars: [...], _summary, _warnings}
    cars_raw = parsed.get("cars")
    if not cars_raw:
        # Backwards-compat: parser zwrocil flat criteria (stara wersja)
        if parsed.get("make"):
            cars_raw = [parsed]
        else:
            raise HTTPException(
                status_code=400,
                detail="Nie udało się wyłapać żadnego auta z wiadomości. Klient musi podać markę.",
            )

    # Validate each car przez ClientCriteria (wyciągnij original_text przed walidacją —
    # Pydantic je odrzuci jako extra field). Plus weryfikacja przez cache normalizacji.
    from ai import model_normalization

    criteria_list: list[dict] = []
    validation_errors: list[str] = []
    auto_warnings: list[str] = []
    for idx, car in enumerate(cars_raw):
        if not car.get("make") or not str(car.get("make", "")).strip():
            validation_errors.append(f"Auto #{idx+1}: brak marki — pominięte")
            continue

        original_text = (car.pop("original_text", None) or "").strip()
        llm_model = str(car.get("model", "") or "").strip()
        make_raw = str(car.get("make", "")).strip()

        # CACHE LOOKUP / VERIFY: dla każdej pary (make, original_text), sprawdzamy
        # czy mamy zapisany mapping. Jeśli tak — używamy cache (deterministic, $0).
        # Jeśli nie — Anthropic weryfikuje + zapisuje.
        if original_text:
            try:
                norm_result = await asyncio.to_thread(
                    model_normalization.normalize_with_cache,
                    make_raw,
                    original_text,
                    llm_model,
                )
                if norm_result and norm_result.get("normalized_model"):
                    # Override LLM-output cache'em jeśli się różnią (cache jest source of truth)
                    cached_model = norm_result["normalized_model"]
                    if cached_model.lower() != llm_model.lower():
                        auto_warnings.append(
                            f"Auto #{idx+1}: '{original_text}' → "
                            f"'{make_raw} {cached_model}' (źródło: {norm_result['source']}; "
                            f"LLM podał '{llm_model}', cache potwierdza '{cached_model}')"
                        )
                        car["model"] = cached_model
                    elif norm_result.get("is_normalized"):
                        auto_warnings.append(
                            f"Auto #{idx+1}: '{original_text}' znormalizowano do "
                            f"'{make_raw} {cached_model}' (źródło: {norm_result['source']}, "
                            f"verified ×{norm_result.get('verified_count', 1)})"
                        )
            except Exception:
                logger.exception("model_normalization.normalize_with_cache failed for %s", original_text)

        try:
            obj = ClientCriteria(**car)
            criteria_dict = obj.model_dump(mode="json")
            if original_text:
                criteria_dict["_original_text"] = original_text
            criteria_list.append(criteria_dict)
        except Exception as exc:
            validation_errors.append(f"Auto #{idx+1} ({car.get('make')}): {exc}")

    if not criteria_list:
        raise HTTPException(
            status_code=422,
            detail=f"Żadne auto nie przeszło walidacji: {'; '.join(validation_errors)}",
        )

    if validation_errors:
        warnings = list(warnings) + validation_errors
    if auto_warnings:
        warnings = list(warnings) + auto_warnings

    return {
        "criteria_list": criteria_list,
        "criteria": criteria_list[0],  # backwards compat dla single-car UI
        "count": len(criteria_list),
        "summary": summary,
        "warnings": warnings,
    }


@app.get("/api/model-normalizations")
async def model_normalizations_list(
    make: Optional[str] = None,
    limit: int = 100,
    _auth: None = Depends(_require_bearer),
):
    """Lista wszystkich znanych normalizacji modeli (cache do nauki)."""
    from ai import model_normalization
    return {
        "items": model_normalization.list_all(make=make, limit=limit),
        "stats": model_normalization.stats(),
    }


@app.delete("/api/model-normalizations/{entry_id}")
async def model_normalizations_delete(entry_id: int, _auth: None = Depends(_require_bearer)):
    """Usuwa pojedynczy wpis cache (force re-verification przy następnym wystąpieniu)."""
    from ai import model_normalization
    ok = model_normalization.delete_entry(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} nie znaleziony")
    return {"removed": True, "id": entry_id}


@app.post("/api/model-normalizations/verify")
async def model_normalizations_verify(
    request: dict,
    _auth: None = Depends(_require_bearer),
):
    """Manual verify endpoint — body: {make, original_text, raw_model?}.

    Force-wywoluje Anthropic Claude do weryfikacji modelu, niezależnie od cache.
    Wynik zapisywany w bazie. Przydatne gdy user chce wymusic re-check.
    """
    from ai import model_normalization
    make = (request.get("make") or "").strip()
    original_text = (request.get("original_text") or "").strip()
    raw_model = (request.get("raw_model") or "").strip() or None

    if not make or not original_text:
        raise HTTPException(status_code=400, detail="Wymagane pola: make, original_text")

    verified = await asyncio.to_thread(
        model_normalization.verify_with_anthropic, make, original_text, raw_model,
    )
    if not verified:
        raise HTTPException(status_code=503, detail="LLM verify niedostępny")

    if verified.get("normalized_model"):
        await asyncio.to_thread(
            model_normalization.store,
            make=make,
            original_text=original_text,
            normalized_model=verified["normalized_model"],
            reason=verified.get("reason"),
            provider=verified.get("provider"),
            llm_model=verified.get("llm_model"),
        )
    return {**verified, "make": make, "original_text": original_text}


@app.get("/api/llm-cache/stats")
async def llm_cache_stats(_auth: None = Depends(_require_bearer)):
    """Statystyki cache wygenerowanych raportów LLM (rich klient/broker)."""
    from report import llm_cache
    return llm_cache.stats()


@app.get("/api/llm-cache/list")
async def llm_cache_list(limit: int = 50, _auth: None = Depends(_require_bearer)):
    """Lista wpisów cache LLM (bez full HTML — tylko meta)."""
    import sqlite3
    from pathlib import Path
    db_path = Path(os.getenv("LLM_CACHE_DB_PATH", "./data/llm_cache.db")).resolve()
    if not db_path.exists():
        return {"items": []}
    limit = max(1, min(int(limit or 50), 500))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT cache_key, lot_id, source, kind, fingerprint, provider, model, "
        "input_tokens, output_tokens, length(html) AS html_size, generated_at "
        "FROM llm_reports ORDER BY generated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return {"items": [dict(r) for r in rows]}


@app.get("/api/llm-cache/entry/{cache_key}")
async def llm_cache_entry(cache_key: str, _auth: None = Depends(_require_bearer)):
    """Zwraca pojedynczy zapisany HTML z cache (do podglądu w UI)."""
    import sqlite3
    from pathlib import Path
    from fastapi.responses import HTMLResponse
    db_path = Path(os.getenv("LLM_CACHE_DB_PATH", "./data/llm_cache.db")).resolve()
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Brak cache DB")
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT html FROM llm_reports WHERE cache_key=?", (cache_key,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Brak wpisu")
    return HTMLResponse(content=row[0])


@app.delete("/api/llm-cache")
async def llm_cache_clear(_auth: None = Depends(_require_bearer)):
    """Czyści cały cache LLM raportów (force regenerate przy następnym kliku)."""
    from report import llm_cache
    removed = llm_cache.clear_all()
    return {"removed": removed}


@app.delete("/api/llm-cache/entry/{cache_key}")
async def llm_cache_delete_entry(cache_key: str, _auth: None = Depends(_require_bearer)):
    """Usuwa pojedynczy wpis cache (force regenerate tylko dla tego lota/kind)."""
    import sqlite3
    from pathlib import Path
    db_path = Path(os.getenv("LLM_CACHE_DB_PATH", "./data/llm_cache.db")).resolve()
    if not db_path.exists():
        return {"removed": 0}
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute("DELETE FROM llm_reports WHERE cache_key=?", (cache_key,))
    conn.commit()
    return {"removed": cur.rowcount or 0}


@app.delete("/api/llm-cache/html-only")
async def llm_cache_clear_html_only(_auth: None = Depends(_require_bearer)):
    """Czyści tylko rendered HTML (zostawia json_skeleton z LLM).

    Po CSS/template change używaj zamiast `DELETE /api/llm-cache`:
    - następny render przejdzie przez Jinja2 z cached JSON skeleton (~50ms/lot)
    - bez kosztu LLM call ($0)
    - całkowity regen rekordu z 6 lotami: ~5s zamiast ~42s

    Pełen `clear_all` używaj tylko gdy zmieniłeś prompts (CLIENT_USER_TEMPLATE,
    BROKER_USER_TEMPLATE) — wtedy JSON skeleton też jest stale.
    """
    from report import llm_cache
    cleared = llm_cache.clear_html_only()
    return {"html_cleared": cleared, "json_skeleton_preserved": True}


@app.get("/api/telegram/status")
async def telegram_status(_auth: None = Depends(_require_bearer)):
    """Status bota + lista subskrybentów (admin)."""
    from notify import telegram as _tg
    from api import telegram_database as _tdb
    info: dict = {
        "configured": _tg.is_configured(),
        "invite_code_set": bool(os.getenv("TELEGRAM_INVITE_CODE", "").strip()),
        "ui_base_url": os.getenv("TELEGRAM_UI_BASE_URL", "").strip() or None,
        "stats": _tdb.stats(),
    }
    if _tg.is_configured():
        try:
            me = _tg.get_me()
            info["bot"] = {
                "id": me.get("id"),
                "username": me.get("username"),
                "first_name": me.get("first_name"),
            }
        except Exception as exc:
            info["bot_error"] = str(exc)
    info["subscribers"] = _tdb.list_all_subscribers()
    return info


@app.post("/api/telegram/test")
async def telegram_test(payload: dict, _auth: None = Depends(_require_bearer)):
    """Wysyła testowe powiadomienie do wszystkich aktywnych subskrybentów (admin)."""
    from notify.telegram import notify_job_completion, is_configured as _tg_configured
    if not _tg_configured():
        raise HTTPException(503, "TELEGRAM_BOT_TOKEN nie ustawiony")
    title = (payload or {}).get("title") or "Test BMW M5 (2020-2022)"
    res = await asyncio.to_thread(
        notify_job_completion,
        status="done",
        title=title,
        record_id=(payload or {}).get("record_id"),
        collected_count=int((payload or {}).get("collected_count") or 47),
        polecam_count=int((payload or {}).get("polecam_count") or 5),
        ryzyko_count=int((payload or {}).get("ryzyko_count") or 2),
        duration_seconds=float((payload or {}).get("duration_seconds") or 272),
        bundle_paths=(payload or {}).get("bundle_paths") or {},
    )
    return {"broadcast_result": res}


@app.delete("/api/telegram/subscribers/{chat_id}")
async def telegram_unsubscribe(chat_id: int, _auth: None = Depends(_require_bearer)):
    """Admin może wymusić deaktywację subskrybenta."""
    from api import telegram_database as _tdb
    ok = _tdb.deactivate(chat_id)
    if not ok:
        raise HTTPException(404, f"Subscriber {chat_id} not found")
    return {"deactivated": chat_id}


@app.get("/api/clients")
async def list_clients(_auth: None = Depends(_require_bearer)):
    """Lista klientów zapisanych w app.db."""
    from api.client_database import init_db, _connect
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT c.id, c.name, c.email, c.phone, c.notes, c.created_at, c.updated_at, "
            "(SELECT COUNT(*) FROM search_records sr WHERE sr.client_id=c.id) AS records_count "
            "FROM clients c ORDER BY c.created_at DESC"
        ).fetchall()
    return {"clients": [dict(r) for r in rows]}


@app.get("/api/db/overview")
async def db_overview(_auth: None = Depends(_require_bearer)):
    """Podsumowanie wszystkich zapisanych danych — dla dashboardu."""
    import sqlite3
    from pathlib import Path
    out: dict = {}

    # app.db
    app_path = Path(os.getenv("APP_DATABASE_PATH", "./data/app.db")).resolve()
    if app_path.exists():
        c = sqlite3.connect(str(app_path))
        clients = c.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        records = c.execute("SELECT COUNT(*) FROM search_records").fetchone()[0]
        latest = c.execute("SELECT created_at FROM search_records ORDER BY created_at DESC LIMIT 1").fetchone()
        out["app_db"] = {
            "path": str(app_path), "size_kb": app_path.stat().st_size // 1024,
            "clients": clients, "search_records": records,
            "latest_record_at": latest[0] if latest else None,
        }

    # jobs.db
    jobs_path = Path(os.getenv("JOB_DB_PATH", "./data/jobs.db")).resolve()
    if jobs_path.exists():
        c = sqlite3.connect(str(jobs_path))
        c.row_factory = sqlite3.Row
        total = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        by_status = {r["status"]: r["c"] for r in c.execute(
            "SELECT status, COUNT(*) AS c FROM jobs GROUP BY status"
        ).fetchall()}
        latest = c.execute("SELECT created_at FROM jobs ORDER BY created_at DESC LIMIT 1").fetchone()
        out["jobs_db"] = {
            "path": str(jobs_path), "size_kb": jobs_path.stat().st_size // 1024,
            "total": total, "by_status": by_status,
            "latest_at": latest["created_at"] if latest else None,
        }

    # llm_cache.db
    from report import llm_cache
    out["llm_cache"] = llm_cache.stats()

    # html_cache (folder)
    html_dir = Path(os.getenv("HTML_CACHE_DIR", "./data/html_cache")).resolve()
    if html_dir.exists():
        sources = {}
        total_files = 0
        total_bytes = 0
        for src_dir in html_dir.iterdir():
            if src_dir.is_dir():
                files = list(src_dir.glob("*.html"))
                size = sum(f.stat().st_size for f in files)
                sources[src_dir.name] = {"count": len(files), "size_kb": size // 1024}
                total_files += len(files)
                total_bytes += size
        out["html_cache"] = {
            "path": str(html_dir), "total_files": total_files,
            "total_size_kb": total_bytes // 1024, "by_source": sources,
        }

    return out


@app.get("/api/html-cache")
async def html_cache_list(source: Optional[str] = None, limit: int = 100, _auth: None = Depends(_require_bearer)):
    """Lista cached HTML scraperowych (Copart/IAAI)."""
    from pathlib import Path
    html_dir = Path(os.getenv("HTML_CACHE_DIR", "./data/html_cache")).resolve()
    if not html_dir.exists():
        return {"items": []}

    items = []
    sources = [source] if source else [d.name for d in html_dir.iterdir() if d.is_dir()]
    for src in sources:
        src_dir = html_dir / src
        if not src_dir.exists():
            continue
        for f in sorted(src_dir.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            stat = f.stat()
            items.append({
                "source": src,
                "filename": f.name,
                "size_kb": stat.st_size // 1024,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "url": f"/api/html-cache/{src}/{f.name}",
            })
    items.sort(key=lambda i: i["modified_at"], reverse=True)
    return {"items": items[:limit]}


@app.get("/api/html-cache/{source}/{filename}")
async def html_cache_serve(source: str, filename: str, _auth: None = Depends(_require_bearer)):
    """Serwuje pojedynczy zapisany HTML z scrapera (do podglądu)."""
    from pathlib import Path
    from fastapi.responses import HTMLResponse
    if "/" in source or "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid path")
    html_dir = Path(os.getenv("HTML_CACHE_DIR", "./data/html_cache")).resolve()
    target = html_dir / source / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Brak pliku")
    # Bezpiecznik: nie wychodź poza html_dir
    try:
        target.resolve().relative_to(html_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal blocked")
    return HTMLResponse(content=target.read_text(encoding="utf-8", errors="ignore"))


def _resolve_log_file() -> Optional[Path]:
    """Znajduje aktualny plik loga uvicorn.

    Searches:
    1. env LOG_FILE_PATH (jeśli ustawione)
    2. /tmp/uvicorn-restart*.log (najnowszy)
    3. data/logs/api.log (jeśli istnieje)
    """
    custom = os.getenv("LOG_FILE_PATH", "").strip()
    if custom:
        p = Path(custom).expanduser()
        if p.exists():
            return p

    # Auto-detect: najnowszy /tmp/uvicorn-restart*.log
    tmp = Path("/tmp")
    candidates = sorted(tmp.glob("uvicorn-restart*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]

    # Fallback: data/logs/api.log
    data_log = Path("./data/logs/api.log").resolve()
    if data_log.exists():
        return data_log

    return None


@app.get("/api/logs/tail")
async def logs_tail(
    lines: int = 200,
    grep: Optional[str] = None,
    _auth: None = Depends(_require_bearer),
):
    """Zwraca ostatnie N linii z logu serwera.

    Query:
        ?lines=200       — ile ostatnich linii (max 5000)
        ?grep=pattern    — filtruj tylko linie zawierające pattern (case-insensitive)
    """
    log_file = _resolve_log_file()
    if not log_file:
        raise HTTPException(status_code=404, detail="Brak pliku loga (LOG_FILE_PATH lub /tmp/uvicorn-restart*.log)")

    lines = max(1, min(int(lines), 5000))
    try:
        # Efektywnie: czytaj ostatnie N linii (deque)
        from collections import deque
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            tail = deque(f, maxlen=lines)
        result_lines = list(tail)
        if grep:
            grep_low = grep.lower()
            result_lines = [l for l in result_lines if grep_low in l.lower()]
        return {
            "log_file": str(log_file),
            "size_kb": log_file.stat().st_size // 1024,
            "lines": result_lines,
            "count": len(result_lines),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read log: {exc}") from exc


@app.get("/api/logs/stream")
async def logs_stream(
    grep: Optional[str] = None,
    _auth: None = Depends(_require_bearer),
):
    """SSE stream — live tail logu (tail -f equivalent).

    Query:
        ?grep=pattern    — tylko linie zawierające pattern

    Klient (przeglądarka) używa EventSource:
        const es = new EventSource('/api/logs/stream?token=...');
        es.addEventListener('line', e => console.log(e.data));

    Backend ma keep-alive co 15s żeby Cloudflare nie zerwało połączenia.
    """
    log_file = _resolve_log_file()
    if not log_file:
        raise HTTPException(status_code=404, detail="Brak pliku loga")

    from fastapi.responses import StreamingResponse

    async def event_generator():
        # Pokaż ostatnie 50 linii na start
        try:
            from collections import deque
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                last_50 = deque(f, maxlen=50)
            for line in last_50:
                line = line.rstrip("\n")
                if grep and grep.lower() not in line.lower():
                    continue
                yield f"event: line\ndata: {line}\n\n"
        except Exception:
            logger.exception("Initial tail read failed")

        # Tail -f loop
        last_size = log_file.stat().st_size
        keep_alive_counter = 0
        try:
            while True:
                await asyncio.sleep(0.5)
                keep_alive_counter += 1

                try:
                    current_size = log_file.stat().st_size
                except FileNotFoundError:
                    yield f"event: error\ndata: log_file_disappeared\n\n"
                    break

                if current_size < last_size:
                    # Rotacja albo truncate — re-open od początku
                    last_size = 0

                if current_size > last_size:
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(last_size)
                        new_data = f.read()
                    last_size = current_size
                    for line in new_data.splitlines():
                        if grep and grep.lower() not in line.lower():
                            continue
                        yield f"event: line\ndata: {line}\n\n"

                # Keep-alive co ~15s
                if keep_alive_counter >= 30:
                    yield ": keep-alive\n\n"
                    keep_alive_counter = 0
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/logs/viewer", response_class=None)
async def logs_viewer(_auth: None = Depends(_require_bearer)):
    """Prosty HTML viewer — otwórz w przeglądarce żeby oglądać logi live.

    Konwencja URL z auth: dla SSE Bearer auth nie działa w EventSource (browser
    nie pozwala custom headers). Zamiast tego viewer wbudowuje token w fetch.
    """
    from fastapi.responses import HTMLResponse
    token = SCRAPER_API_TOKEN or ""
    public_base = PUBLIC_BASE_URL or ""

    # HTML viewer z fetch + ReadableStream
    html = """<!DOCTYPE html>
<html lang='pl'><head>
<meta charset='UTF-8'><title>📡 Logi serwera (live)</title>
<style>
  body{margin:0;background:#0a0e14;color:#c9d1d9;font-family:'SF Mono',Menlo,monospace;font-size:12px}
  .header{padding:10px 16px;background:#161b22;border-bottom:1px solid #30363d;display:flex;gap:12px;align-items:center}
  .header h1{margin:0;font-size:14px;color:#a5b4fc}
  .header input{flex:1;padding:6px 10px;background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:4px;font-family:inherit;font-size:12px}
  .header button{padding:6px 12px;background:#1f2937;color:#e6edf3;border:1px solid #30363d;border-radius:4px;cursor:pointer;font-size:12px}
  .header button:hover{background:#374151}
  .header button.active{background:#22c55e;border-color:#22c55e;color:#0a0e14}
  .status{padding:4px 10px;border-radius:99px;background:#0d3a1f;color:#56d364;font-size:11px}
  .status.disconnected{background:#3d0c0c;color:#ff7b72}
  #logs{padding:8px 16px;overflow-y:auto;max-height:calc(100vh - 60px);white-space:pre-wrap;word-break:break-all}
  .line{padding:2px 0;border-bottom:1px solid rgba(48,54,61,0.3)}
  .line.error{color:#ff7b72}
  .line.warning{color:#e3b341}
  .line.info{color:#56d364}
  .line.http{color:#7d8590}
</style>
</head><body>
<div class='header'>
  <h1>📡 Logi serwera</h1>
  <span class='status' id='status'>Łączę...</span>
  <input id='filter' placeholder='Filtr (regex, np. error|429)' value=''>
  <button onclick='clearLogs()'>Wyczyść</button>
  <button id='autoscroll' class='active' onclick='toggleAutoscroll()'>Auto-scroll</button>
  <button id='pause' onclick='togglePause()'>Pauza</button>
</div>
<div id='logs'></div>
<script>
const TOKEN = '__TOKEN__';
const BASE = '__BASE__';
let autoscroll = true;
let paused = false;
let abortCtl = null;
const logsEl = document.getElementById('logs');
const statusEl = document.getElementById('status');
const filterEl = document.getElementById('filter');

function classifyLine(line) {
  const low = line.toLowerCase();
  if (/\\b(error|exception|traceback|fail|critical)\\b/i.test(line)) return 'error';
  if (/\\b(warn|warning|deprecat)\\b/i.test(line)) return 'warning';
  if (/\\b(GET|POST|PUT|DELETE|PATCH) \\//i.test(line)) return 'http';
  if (/\\b(info|done|ok)\\b/i.test(line)) return 'info';
  return '';
}

function appendLine(text) {
  if (paused) return;
  const filter = filterEl.value;
  if (filter) {
    try {
      if (!new RegExp(filter, 'i').test(text)) return;
    } catch(e) { /* invalid regex — show all */ }
  }
  const div = document.createElement('div');
  div.className = 'line ' + classifyLine(text);
  div.textContent = text;
  logsEl.appendChild(div);
  // Limit do 5000 linii (FIFO)
  while (logsEl.children.length > 5000) logsEl.removeChild(logsEl.firstChild);
  if (autoscroll) logsEl.scrollTop = logsEl.scrollHeight;
}

async function connect() {
  if (abortCtl) abortCtl.abort();
  abortCtl = new AbortController();
  statusEl.textContent = 'Łączę...';
  statusEl.classList.add('disconnected');
  try {
    const res = await fetch(BASE + '/api/logs/stream', {
      headers: { 'Authorization': 'Bearer ' + TOKEN },
      signal: abortCtl.signal,
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    statusEl.textContent = '🟢 Połączono';
    statusEl.classList.remove('disconnected');
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // Parsuj SSE events: blok kończy się \\n\\n
      let idx;
      while ((idx = buf.indexOf('\\n\\n')) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        // Każdy event może mieć "event: X" + "data: Y"
        const dataLines = block.split('\\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).trimStart());
        if (dataLines.length) appendLine(dataLines.join('\\n'));
      }
    }
    statusEl.textContent = '🔌 Rozłączono';
    statusEl.classList.add('disconnected');
  } catch (e) {
    if (e.name !== 'AbortError') {
      console.error(e);
      statusEl.textContent = '❌ ' + e.message;
      statusEl.classList.add('disconnected');
      setTimeout(connect, 3000);  // auto-reconnect
    }
  }
}

function clearLogs() { logsEl.innerHTML = ''; }
function toggleAutoscroll() {
  autoscroll = !autoscroll;
  document.getElementById('autoscroll').classList.toggle('active', autoscroll);
}
function togglePause() {
  paused = !paused;
  document.getElementById('pause').classList.toggle('active', paused);
}
filterEl.addEventListener('input', () => {});  // dynamiczny filtr działa od następnej linii

connect();
</script>
</body></html>"""
    html = html.replace("__TOKEN__", token).replace("__BASE__", public_base or "")
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
