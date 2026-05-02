# Reports API — Car Auction Buddy

Standalone FastAPI service for downloading generated reports and JSON artifacts.

## Endpoints

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| GET | `/clients` | List all clients | JSON array |
| GET | `/clients/{id}/records` | List records for a client | JSON array (metadata) |
| GET | `/records/{id}/report.html` | HTML report | `text/html` |
| GET | `/records/{id}/analysis.json` | AI analysis | `application/json` |
| GET | `/records/{id}/lots.json` | Raw listings | `application/json` |
| GET | `/records/{id}/mail.html` | Email HTML | `text/html` |
| GET | `/health` | Health check | `{"status": "ok"}` |

## Auth

All endpoints (except `/health`) require `X-API-Key` header matching `REPORTS_API_KEY`.

## Setup

```bash
# 1. Create .env from template
cp .env.example .env
# Edit .env with real values

# 2a. Run locally
pip install -r requirements.txt
uvicorn main:app --reload

# 2b. Or with Docker
docker build -t reports-api .
docker run --env-file .env -p 8000:8000 reports-api
```

## API docs

Once running: `http://localhost:8000/docs` (Swagger UI) or `/redoc`.

## Example

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/clients

curl -H "X-API-Key: your-key" http://localhost:8000/clients/UUID/records

curl -H "X-API-Key: your-key" http://localhost:8000/records/UUID/report.html > report.html
```
