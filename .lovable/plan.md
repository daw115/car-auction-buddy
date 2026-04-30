## USA Car Finder — Operational Panel (Lovable + your Python scraper)

Single-operator panel that drives the full workflow: client → criteria → search (manual paste or call your Python scraper) → AI analysis (Anthropic) → HTML report + downloadable artifacts → saved record you can return to.

No landing page. The root URL `/` is the operational panel.

### Architecture

```text
Browser (React panel)
        │
        ▼
TanStack Start server functions (Cloudflare Worker)
   ├─ Lovable Cloud (Postgres)  ← clients, records, artifacts metadata
   ├─ Anthropic API             ← analysis (your ANTHROPIC_API_KEY)
   └─ Your Python scraper       ← optional, called via SCRAPER_BASE_URL
```

Lovable Cloud handles persistence (no SQLite, no local files). Artifacts (AI input JSON, prompt, analysis JSON, HTML report, mail HTML) are stored as rows + downloadable on demand.

### Panel layout (single page, 3 columns / stacked on mobile)

1. **Client column** — list of saved clients, "+ New client" form (name, contact, notes). Click loads client into the workspace.
2. **Workspace column** (the main pane)
   - Search criteria form: make, model, year range, max price, damage filters, auction-window hours (12–120 default), seller-type-insurance toggle (default on).
   - Listings table — populated by either:
     - **Manual / paste** mode: paste JSON or CSV of pre-filtered listings from your scraper output, OR
     - **Online search** button (only enabled if `SCRAPER_BASE_URL` is configured) — POSTs criteria to your Python service, shows progress, fills the table.
   - "Run AI analysis" button → calls Anthropic, shows results inline.
   - "Generate report" → renders HTML in a preview frame.
   - Download buttons: `ai_input.json`, `prompt.txt`, `analysis.json`, `report.html`, `mail.html`.
   - "Save as record" → snapshots criteria + listings + analysis + report into a record row tied to the current client.
3. **Records column** — list of past records for the selected client, click to reload everything into the workspace (read-only or "duplicate to edit").

### Database (Lovable Cloud)

- `clients` — id, name, contact, notes, created_at
- `records` — id, client_id, criteria (jsonb), listings (jsonb), ai_input (jsonb), ai_prompt (text), analysis (jsonb), report_html (text), mail_html (text), status, created_at
- `app_config` — singleton row for runtime flags: `use_mock_data`, `ai_analysis_mode`, `filter_seller_insurance_only`, `min_auction_window_hours`, `max_auction_window_hours`, `collect_all_prefiltered_results`, `open_all_prefiltered_details`. Editable from a small Settings drawer; defaults match your production list.

No auth. No RLS-per-user (single operator). Public access to the published URL — keep the URL private.

### AI analysis

Server function calls `https://api.anthropic.com/v1/messages` with `ANTHROPIC_API_KEY` (Lovable Cloud secret, never in code). Default model from `ANTHROPIC_MODEL` env (e.g. `claude-sonnet-4-5`). Prompt builder mirrors the structure used by `usa-car-finder/ai/analyzer.py` so the input JSON / prompt / output JSON download cleanly. Errors are caught and surfaced in the UI (no blank screens).

### HTML report

Jinja-style template re-implemented in TS, styled to match `przyklady_maili_README.md` (HTML mail look). Output is HTML + Markdown + JSON. **No DOCX, no PDF** (WeasyPrint can't run on the Worker — explicitly out of scope).

### Bridge to your Python service

You deploy `usa-car-finder/` on a host that supports Playwright + persistent disk (Railway, Render, Fly.io, Hetzner — your choice). Lovable calls it via two endpoints, expected contract:

- `POST {SCRAPER_BASE_URL}/api/search` — body: criteria JSON; auth: `Authorization: Bearer ${SCRAPER_API_TOKEN}`; returns pre-filtered listings (sorted by closest auction first, seller-type insurance, damage filtered, with detail data already opened — i.e. exactly the order your existing scraper does).
- `GET {SCRAPER_BASE_URL}/health` — returns `{ ok: true }`.

If your existing FastAPI doesn't expose these yet, I'll include a minimal patch (one new router file) to add them on top of your current scraper logic — no logic changes, no CAPTCHA bypass. CAPTCHA / login is your service's problem (storage_state, manual login) and stays on your host.

The "Online search" button is hidden when `SCRAPER_BASE_URL` is unset, so the panel works standalone with manual paste from day one.

### Validation endpoints (so you can sanity-check after deploy)

- `GET /api/health` — returns `{ ok: true, scraper: <reachable|unconfigured|down> }`
- `GET /api/config` — returns current `app_config` + which env vars are set (booleans only, never values)
- `GET /api/records` — list of saved records (id, client name, created_at)

### Required environment variables (you set these in Lovable Cloud secrets)

- `ANTHROPIC_API_KEY` (required for AI)
- `ANTHROPIC_MODEL` (optional, default `claude-sonnet-4-5`)
- `ANTHROPIC_BASE_URL` (optional, default `https://api.anthropic.com`)
- `SCRAPER_BASE_URL` (optional — when set, enables Online search button)
- `SCRAPER_API_TOKEN` (required if `SCRAPER_BASE_URL` is set)

These stay on your **Python host** and are NOT needed in Lovable: `COPART_EMAIL/PASSWORD`, `IAAI_EMAIL/PASSWORD`, `AUTOHELPERBOT_EMAIL/PASSWORD`. Scraper credentials never touch the Lovable side.

### What's explicitly NOT included (and why)

- Playwright scraping inside Lovable — Worker runtime has no Chromium / child_process. Lives on your Python host.
- SQLite — replaced by Lovable Cloud Postgres.
- WeasyPrint / DOCX / PDF — not runnable on Worker; out of scope per your spec ("No DOCX. HTML + markdown/JSON.").
- Telegram / email_integration modules — not part of "online panel"; can be added later.
- Multi-user auth — single operator per your answer.

### Build steps

1. Enable Lovable Cloud, create `clients`, `records`, `app_config` tables, seed `app_config` with your production defaults.
2. Add Anthropic secrets.
3. Build the operational panel UI (3-column workspace, replacing the placeholder index).
4. Server functions: `listClients`, `createClient`, `saveRecord`, `listRecords`, `loadRecord`, `runAnalysis`, `renderReport`, `runScraperSearch` (optional bridge), `getConfig`, `updateConfig`.
5. Server routes: `/api/health`, `/api/config`, `/api/records` for validation.
6. Artifact download endpoints (return JSON / text / HTML with proper Content-Disposition).
7. Optional: drop a `scraper_bridge.py` snippet in chat for you to paste into your FastAPI so the two endpoints exist on your host.

### Final deliverable

Working URL: your Lovable preview/published URL (`*.lovable.app`).
You configure: `ANTHROPIC_API_KEY`, optionally `ANTHROPIC_MODEL`, `SCRAPER_BASE_URL`, `SCRAPER_API_TOKEN` in Lovable Cloud secrets. Scraper credentials stay on your Python host.