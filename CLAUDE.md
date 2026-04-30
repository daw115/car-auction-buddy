# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo is a workspace for the **USA Car Finder** project — a tool that scrapes Copart/IAAI auctions, scores lots with AI, and produces client-ready offers.

- `usa-car-finder/` — the actual application (FastAPI + Playwright + AI pipeline). All commands below run from inside this directory.
- `backend/services/scrapers/` — standalone Playwright-with-extensions experiments, **not** wired into `usa-car-finder`. Treat as reference/sandbox.
- `chrome_extensions/{auctiongate,autohelperbot}/` — unpacked Chromium extensions loaded by the scraper when `USE_EXTENSIONS=true`. The scraper expects them at this exact path (see `usa-car-finder/extensions/`).
- `playwright_profiles/`, `usa-car-finder/playwright_profiles/` — saved login state for Copart/IAAI used by the scraper.
- Top-level `*.md` files (`ZALOZENIA_APLIKACJI.md`, `PLAYWRIGHT_ARCHITECTURE.md`, `KALKULATOR_ZALOZENIA.md`, `agent-oferta-auto-usa.md`, `przyklady_maili_README.md`, `usa_car_finder_prompt.md`) are the **product/architecture spec** in Polish — they are the source of truth for business logic (scoring rules, import-cost calculator, mail/PDF templates, agent prompts).
- `*` and `* 2.py` duplicates exist in several directories (e.g. `analyzer.py` / `analyzer 2.py`). The `* 2.py` files are macOS Finder/iCloud copies — edit the un-suffixed file.

## Common commands

All commands run from `usa-car-finder/`. The repo ships a `venv/` — use it (the existing `start_autoscout.sh` does).

```bash
# Install
pip install -r requirements.txt
playwright install chromium

# Run the API + UI (http://localhost:8000)
python -m api.main
# or, matching start_autoscout.sh:
venv/bin/python3 -m uvicorn api.main:app --host 127.0.0.1 --port 8000

# Local-only mode (no scraping, no AI keys needed)
USE_MOCK_DATA=true AI_ANALYSIS_MODE=local python -m api.main

# Full email→scrape→AI→Telegram→mail pipeline
python main_automation.py

# Scraper smoke test (Copart + IAAI completeness check)
python test_scrapers.py

# One-off targeted search script
python search_audi_a5_report.py
```

There is **no test runner, linter, or formatter configured**. The `test_*.py` files are runnable scripts (`python test_scrapers.py`), not pytest suites.

## Architecture

The pipeline is linear and the orchestration lives in two places depending on entry point:

```
ClientCriteria → AutomatedScraper (Playwright) → HTML cache + parsed CarLot[]
              → ai.analyzer.analyze_lots → AnalyzedLot[] (score + reasoning)
              → report.* → PDF / HTML mail / Markdown / client artifacts
```

- **Entry points**
  - `api/main.py` — FastAPI app. Key routes: `POST /search`, `POST /report`, `POST /report/offer-email-html`, `GET /artifacts/{filename}`, `GET /config`, `POST /browser/close`, `GET /health`. Serves the UI from `api/static/`.
  - `main_automation.py` — `AutomationOrchestrator` that wires Gmail → `email_parser` → scraper → analyzer → `offer_agent` → Telegram approval → outbound mail. Used for the unattended flow.

- **Scraping (`scraper/`)** — `AutomatedScraper` is the facade over `copart.py` and `iaai.py`, both built on `base.py` + `browser_context.py`. When `USE_EXTENSIONS=true`, `extension_enricher.py` reads the AuctionGate/AutoHelperBot iframes directly from the detail page (full VIN, reserve price, seller type) — the extensions only work in Playwright's bundled Chromium, not Google Chrome. `storage_state.py` and `*_login_helper.py` persist auth in `data/chrome_profile/` and the `playwright_profiles/*.json` files.

- **Parsing (`parser/`)** — `models.py` defines the canonical Pydantic types: `ClientCriteria`, `CarLot`, `AIAnalysis`, `AnalyzedLot`, `SearchResponse`. `copart_parser.py` / `iaai_parser.py` turn cached HTML into `CarLot`s. All downstream code consumes these models — when extending fields, change `models.py` first.

- **AI scoring (`ai/analyzer.py`)** — `analyze_lots(lots, criteria)` is the single entry. Behavior is driven by env vars:
  - `AI_ANALYSIS_MODE` ∈ `auto` (default; OpenAI → Anthropic → local), `openai`/`gpt`, `anthropic`, `local`
  - `AI_ANALYSIS_STRICT=true` → no fallback to local on missing keys / API errors
  - The system prompt encodes business rules: Eastern-US states get +1.5 score, Western −1.0, Flood/Fire damage auto-rejected. Edits to scoring rules live in this prompt, not in the analyzer code.

- **Pricing (`pricing/import_calculator.py`)** — landed-cost calculation for PL import (transport, customs, VAT, akcyza, homologacja). The assumptions are documented in `KALKULATOR_ZALOZENIA.md` — keep that file in sync when changing rates.

- **Reports (`report/`)** — `generator.py` (PDF via WeasyPrint/ReportLab), `html_generator.py` and `offer_html_generator.py` (Jinja2 templates in `report/templates/`), `offer_agent.py` (TOP-5 + 5-extras agent used by the automation pipeline), `client_artifacts.py` (writes `ai_input` / `ai_prompt` / `analysis_json` / `client_report` files into `data/client_searches/` and exposes them via `/artifacts/{filename}`). Mail HTML structure must follow `przyklady_maili_README.md`.

## Configuration knobs that change behavior significantly

These env vars are read across modules; consult before debugging "why does the scraper / AI behave differently":

- Data source: `USE_MOCK_DATA`, `FORCE_REFRESH`, `CACHE_MAX_AGE_HOURS`, `HTML_CACHE_DIR`, `SEARCH_ARTIFACT_DIR`
- Scraper scope: `SEARCH_MAX_PAGES`, `SEARCH_DETAIL_MULTIPLIER`, `MAX_RESULTS_PER_SOURCE`, `OPEN_ALL_PREFILTERED_DETAILS`, `COLLECT_ALL_PREFILTERED_RESULTS`, `STRICT_SCAN_MAX_RESULTS_THRESHOLD`, `BLOCK_MEDIA_ASSETS`
- Browser/extensions: `USE_EXTENSIONS`, `KEEP_BROWSER_OPEN`, `DISABLED_EXTENSIONS`, `CHROME_EXECUTABLE_PATH`
- Filtering: `FILTER_SELLER_INSURANCE_ONLY`, `MIN_AUCTION_WINDOW_HOURS`, `MAX_AUCTION_WINDOW_HOURS`
- AI: `AI_ANALYSIS_MODE`, `AI_ANALYSIS_STRICT`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `ANTHROPIC_API_KEY`
- Orchestrator: `ORCHESTRATOR_MAX_RESULTS`, `CLIENT_EMAIL`, `GMAIL_ADDRESS`

The `README.md` in `usa-car-finder/` has a fuller annotated `.env` example.

## Working in Polish

Product docs, prompts, UI strings, log messages, and AI system prompts are in Polish. Match that language when editing prompts or user-facing text; code identifiers stay English.
