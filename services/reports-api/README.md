# Reports API — Car Auction Buddy

Read-only FastAPI service for downloading generated reports and JSON artifacts from Supabase. It uses a server-only service-role key and must not be exposed without its API-key boundary.

## Endpoints

| Method | Path                          | Access      | Description                       |
| ------ | ----------------------------- | ----------- | --------------------------------- |
| GET    | `/health`                     | Public      | Process liveness only             |
| GET    | `/clients`                    | `X-API-Key` | List clients                      |
| GET    | `/clients/{id}/records`       | `X-API-Key` | List report metadata for a client |
| GET    | `/records/{id}/report.html`   | `X-API-Key` | Download the HTML report          |
| GET    | `/records/{id}/analysis.json` | `X-API-Key` | Download AI analysis              |
| GET    | `/records/{id}/lots.json`     | `X-API-Key` | Download raw listings             |
| GET    | `/records/{id}/mail.html`     | `X-API-Key` | Download email HTML               |

Interactive API documentation is disabled. HTML artifacts are returned as attachments with a sandboxed Content Security Policy. Stored HTML containing scripts, event handlers, active embeds, unsafe URL schemes, or equivalent active content is rejected before download. External image URLs are replaced with an inert placeholder; images embedded as `data:image/...` remain available.

## Configuration

Copy `.env.example` to a server-only secret store and configure:

- `SUPABASE_URL` — required HTTPS project URL;
- `SUPABASE_SERVICE_ROLE_KEY` — required server-only credential that bypasses RLS;
- `REPORTS_API_KEY` — required unique random key, at least 32 characters;
- `REPORTS_API_CORS_ORIGINS` — optional comma-separated exact browser origins. Wildcards are rejected. Leave empty for non-browser clients.

## Local development

Use a dedicated port because the external `usa-car-finder` scraper commonly occupies port 8000:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt

set -a
. ./.env
set +a
uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

Run checks:

```bash
ruff check .
ruff format --check .
python -m pytest -q
```

Smoke test without printing the API key:

```bash
curl --fail --silent http://127.0.0.1:8001/health
curl --fail --silent \
  -H "X-API-Key: $REPORTS_API_KEY" \
  http://127.0.0.1:8001/clients
```

## Docker

The container runs as an unprivileged user and includes a liveness health check. Bind it to loopback unless a trusted reverse proxy provides the external boundary:

```bash
docker build -t car-auction-reports-api .
docker run --rm --env-file .env -p 127.0.0.1:8001:8000 car-auction-reports-api
```

Do not commit `.env`, expose the service-role key to browser code, or reuse `REPORTS_API_KEY` as another application secret.
