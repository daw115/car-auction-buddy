# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo is a workspace for the **USA Car Finder** project — a tool that scrapes Copart/IAAI auctions, scores lots with AI, and produces client-ready offers.

- `usa-car-finder/` — the actual application (FastAPI + Playwright + AI pipeline). All commands below run from inside this directory.
- `backend/services/scrapers/` — standalone Playwright-with-extensions experiments, **not** wired into `usa-car-finder`. Treat as reference/sandbox.
- `usa-car-finder/extensions/{auctiongate,autohelperbot,bidwise,manheim-collector}/` — unpacked Chromium extensions. AuctionGate/AutoHelperBot are loaded by the scraper when `USE_EXTENSIONS=true`; `manheim-collector` is our own and runs in the logged-in Chrome on the server (see `scripts/manheim-browser-run.sh`).
- `playwright_profiles/`, `usa-car-finder/playwright_profiles/` — saved login state for Copart/IAAI used by the scraper.
- Top-level `*.md` files (`ZALOZENIA_APLIKACJI.md`, `PLAYWRIGHT_ARCHITECTURE.md`, `KALKULATOR_ZALOZENIA.md`, `agent-oferta-auto-usa.md`, `przyklady_maili_README.md`, `usa_car_finder_prompt.md`) are the **product/architecture spec** in Polish — they are the source of truth for business logic (scoring rules, import-cost calculator, mail/PDF templates, agent prompts).

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

Tests are of two kinds. `tests/` is a pytest suite and is the gate before every deploy:

```bash
python -m pytest tests/ -q
```

The `test_*.py` files in the project root are runnable scripts (`python test_scrapers.py`), not pytest cases. No linter or formatter is configured.

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

- **Scraping (`scraper/`)** — `AutomatedScraper` is the facade over `copart.py`, `iaai.py` and `manheim.py`, all built on `base.py` + `browser_context.py`. Manheim is opt-in (`MANHEIM_BACKEND_ENABLED`), returns only the top 3 lots, and cannot be driven directly: the BidWise extension occupies the single `chrome.debugger` slot on its tab. Instead the backend leaves jobs (`api/manheim_jobs.py`) that our own `manheim-collector` extension polls from inside the logged-in page and answers by replaying the GraphQL chain into `POST /api/manheim/ingest`. `scraper/manheim_session.py` holds the dependency-free readiness check used by `/api/capabilities`. When `USE_EXTENSIONS=true`, `extension_enricher.py` reads the AuctionGate/AutoHelperBot iframes directly from the detail page (full VIN, reserve price, seller type) — the extensions only work in Playwright's bundled Chromium, not Google Chrome. `storage_state.py` and `*_login_helper.py` persist auth in `data/chrome_profile/` and the `playwright_profiles/*.json` files.

- **Parsing (`parser/`)** — `models.py` defines the canonical Pydantic types: `ClientCriteria`, `CarLot`, `AIAnalysis`, `AnalyzedLot`, `SearchResponse`. `copart_parser.py` / `iaai_parser.py` turn cached HTML into `CarLot`s. All downstream code consumes these models — when extending fields, change `models.py` first.

- **AI scoring (`ai/analyzer.py`)** — `analyze_lots(lots, criteria)` is the single entry. Behavior is driven by env vars:
  - `AI_ANALYSIS_MODE` ∈ `claude-code` (what `.env` actually sets), `auto`, `openai`/`gpt`, `anthropic`, `local`
  - `AI_ANALYSIS_STRICT=true` → no fallback to local on missing keys / API errors
  - **The score is computed outside the model.** `scoring/unified.py` produces it deterministically (weighted components with weight renormalisation, thresholds 7.5 POLECAM / 5.0 RYZYKO), and `ai/analyzer.py` overwrites whatever the model returned. Scoring rule changes go in `scoring/unified.py`, **not** in the prompt.
  - US region is one component (`logistics`, weight 0.10) via `scoring/regions.py` — not a flat ±1.5 bonus. Flood/fire, frame damage, salvage-when-Clean-required and red-light are hard disqualifiers: score 0.0 and ODRZUĆ.
  - The `condition` component is an **AutoGrade 0–5** from `scoring/autograde.py`, the same scale Manheim prints on a listing. Manheim supplies a grade; Copart and IAAI supply only damage text, so we compute the equivalent — without a shared scale you cannot answer whether a Copart lot is in better shape than a Manheim one. When the auction supplies its own grade, **that number wins**; ours runs alongside and flags a divergence ≥0.5 for the broker.
  - **AutoGrade is condition ONLY.** The published NAAA/Manheim methodology explicitly excludes mileage, model year, make, trim, colour, options, MSRP, announcements, estimated repair cost and repair action — value is meant to come from grade *plus* year/mileage/MMR. Keep it that way: putting any of those into `autograde.py` turns it into a second buying score and destroys comparability with the auction's number. Price, mileage and logistics have their own components in `unified.py`; that is where they belong.
  - Two non-obvious rules from the spec are implemented and tested: tread depth does **not** affect the grade unless a tyre is at ≤3/32 *and* carries no separate replacement line item (no double-dipping), and the 4/32–7/32 wear band is a Minor reduction even though Manheim's UI colours 6/32+ green. Repeated occurrences of the same line item decay (`_REPEAT_DECAY`) — NAAA puts "parking lot dings" in the grade-3 definition, so ten scratches must not produce a wreck.
  - The weighting algorithm itself is patented (US 8,230,362) and unpublished. Our deductions are a calibrated reconstruction of the published Major/Moderate/Minor structure, not a copy — say so when it matters, and treat the auction's own grade as authoritative.
  - Budget is **not** a disqualifier. A lot above the client's ceiling keeps its score and gets a separate verdict — `recommendation` becomes `PONAD BUDŻET` (the fourth allowed value). Such lots never enter the client offer unless the broker explicitly allows them (`allow_over_budget`).
  - The client's budget is a **landed PLN amount**, not an auction price. The auction ceiling is derived per lot by `scoring/budget.max_bid_for_budget()`, because towing enters the customs base and is multiplied by duty, VAT and excise.

- **Pricing (`pricing/`)** — landed-cost calculation for PL import. `import_calculator.py` is pure arithmetic; the rates come from outside it. The assumptions are documented in `KALKULATOR_ZALOZENIA.md` — keep that file in sync when changing rates.
  - `tariff.py` is the **only module that knows the law**. Duty is no longer a constant: since 1 July 2026 (EU regulation 2026/1455, in force until 31 Dec 2029) a car *assembled in the USA* enters at 0%, everything else — including EVs, which are excluded — stays at 10%. Excise has four rates, not two: 3.1% / 18.6% for combustion, 1.55% / 9.3% for hybrids up to 3500 cm³, where a Feb 2026 general interpretation from the Ministry of Finance extended the preference to mild hybrids (48 V).
  - `vin.py` derives country of assembly from the first VIN character. Copart masks the last six characters but never the first, so 0%-duty eligibility is known from the results list, before opening the lot.
  - `drivetrain.py` detects BEV/HEV/PHEV/MHEV from the trim string. Pass it only vehicle-identifying fields — feeding it damage text produces false matches.
  - `fx.py` pulls USD/PLN from the NBP API with a markup (`FX_MARKUP_PCT`, default 2%), cached for the working day. `FX_RATE_OVERRIDE` pins it — the test suite sets it via `tests/conftest.py`, otherwise every amount-asserting test would track the daily fixing.
  - **When data is missing, price HIGHER.** Unknown assembly country → 10% duty; unrecognised drivetrain → combustion rate; unknown displacement → 18.6%. An overstated quote can be lowered once the data is confirmed; an understated one comes back to the client as a surcharge, which is exactly what the offer promises never happens. Every `Rates` carries `assumptions` — surface them in the broker brief.
  - `calculate_lot_import_costs(lot)` is the single choke point that applies all of the above. Anything holding a `CarLot` must go through it (or `scoring/budget.landed_cost_for_lot`), never through `landed_cost_pln`, which is lot-blind and deliberately conservative.

- **Sales agent (`sales/`)** — lead intake, qualification and client conversation. Same split as the offer pipeline: Python computes, the model only writes sentences, a validator rejects anything breaking the rules.
  - `qualification.py` scores a lead 0-100 deterministically (weights renormalise over the components we actually have, as in `scoring/unified.py`). Two conditions cap the segment at C regardless of points: refusing a damaged car, and a budget below the auction floor — both mean "not today", not "slightly worse".
  - `agent.py` proposes the next message. System prompt is `agent-sprzedaz-usa.md` and must stay byte-identical between calls for the prompt cache; everything variable goes into the user message. `SALES_AGENT_MODEL_ENABLED=false` falls back to rule-composed drafts; `SALES_PARSER_ENABLED=false` skips the LLM intake parser (regex extraction of budget/year still runs).
  - `db.py` — `approve_and_send` is the only path from draft to message, and it is idempotent. **Nothing in this package sends anything.** The API returns a `wa.me` link; a human clicks it.
  - `api/sales_routes.py` exposes two routers: `public_router` (the landing-page form — open, rate-limited, honeypot) and `router` (broker views), gated at `include_router` time in `api/main.py`. Add new broker endpoints to `router` so they inherit the token check.

- **Reports (`report/`)** — `generator.py` (PDF via WeasyPrint/ReportLab), `html_generator.py` and `offer_html_generator.py` (Jinja2 templates in `report/templates/`), `offer_agent.py` (client offer + broker brief for the automation pipeline — every figure is computed in Python from `pricing/import_calculator.py`; the LLM only writes prose and its output is validated in `_clean_prose`, so digits, auction jargon and banned phrases never reach the client. The system prompt is `agent-oferta-auto-usa.md`), `client_artifacts.py` (writes `<slug>_analysis.json` and `<slug>_client_report.md` into `data/client_searches/` and exposes them via `/artifacts/{filename}`), `whatsapp.py` (short client message + wa.me link — **generates only, never sends**; the broker approves and sends it). Mail HTML structure must follow `przyklady_maili_README.md`.

## Configuration knobs that change behavior significantly

These env vars are read across modules; consult before debugging "why does the scraper / AI behave differently":

- Data source: `USE_MOCK_DATA`, `FORCE_REFRESH`, `CACHE_MAX_AGE_HOURS`, `HTML_CACHE_DIR`, `SEARCH_ARTIFACT_DIR`
- Scraper scope: `SEARCH_MAX_PAGES`, `SEARCH_DETAIL_MULTIPLIER`, `MAX_RESULTS_PER_SOURCE`, `OPEN_ALL_PREFILTERED_DETAILS`, `COLLECT_ALL_PREFILTERED_RESULTS`, `STRICT_SCAN_MAX_RESULTS_THRESHOLD`, `BLOCK_MEDIA_ASSETS`
- Browser/extensions: `USE_EXTENSIONS`, `KEEP_BROWSER_OPEN`, `DISABLED_EXTENSIONS`, `CHROME_EXECUTABLE_PATH`
- Filtering: `FILTER_SELLER_INSURANCE_ONLY`, `MIN_AUCTION_WINDOW_HOURS`, `MAX_AUCTION_WINDOW_HOURS`
- AI: `AI_ANALYSIS_MODE`, `AI_ANALYSIS_STRICT`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `ANTHROPIC_API_KEY`
- Claude Code as the model provider (the current default for analysis, reports and offers): `ai/claude_code.py` is the single entry point — it shells out to `claude -p` and authenticates with the logged-in **subscription**, not an API key (`ANTHROPIC_API_KEY` in `.env` belongs to the dead `oneprovider.dev` proxy). Never add `--bare`: it disables the OAuth read this depends on. The system prompt must stay byte-identical between calls — it is passed via `--system-prompt` so the ~21k-token prefix hits the prompt cache (measured 13× cheaper on the second call). Models per task: `CLAUDE_CODE_MODEL`, `CLAUDE_CODE_OFFER_MODEL`, `CLAUDE_CODE_REPORTS_MODEL`. If calls fail with "niezalogowany", run `claude /login` on the server as the service user.
- Orchestrator: `ORCHESTRATOR_MAX_RESULTS`, `CLIENT_EMAIL`, `GMAIL_ADDRESS`

The `README.md` in `usa-car-finder/` has a fuller annotated `.env` example.

## Working in Polish

Product docs, prompts, UI strings, log messages, and AI system prompts are in Polish. Match that language when editing prompts or user-facing text; code identifiers stay English.
