"""
Car Auction Buddy — Reports API (FastAPI)

Standalone service that exposes generated reports and JSON artifacts
from the Supabase `records` table via REST endpoints.

Auth: simple API key in X-API-Key header.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from supabase import Client, create_client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
REPORTS_API_KEY = os.environ["REPORTS_API_KEY"]

# ---------------------------------------------------------------------------
# Supabase client (service-role — bypasses RLS)
# ---------------------------------------------------------------------------

_supabase: Client | None = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _supabase


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(key: str | None = Security(api_key_header)) -> str:
    if not key or key != REPORTS_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return key


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Car Auction Buddy — Reports API",
    version="1.0.0",
    dependencies=[Depends(verify_api_key)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["X-API-Key", "Content-Type"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ClientOut(BaseModel):
    id: str
    name: str
    contact: str | None = None
    notes: str | None = None
    created_at: str


class RecordSummary(BaseModel):
    id: str
    title: str | None = None
    status: str
    created_at: str
    updated_at: str
    listings_count: int = 0
    has_report_html: bool = False
    has_analysis: bool = False
    has_mail_html: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/clients", response_model=list[ClientOut])
async def list_clients():
    """List all clients."""
    sb = get_supabase()
    resp = sb.table("clients").select("id, name, contact, notes, created_at").order("created_at", desc=True).execute()
    return resp.data


@app.get("/clients/{client_id}/records", response_model=list[RecordSummary])
async def list_client_records(client_id: str):
    """List records (reports) for a specific client."""
    sb = get_supabase()

    # Verify client exists
    client = sb.table("clients").select("id").eq("id", client_id).maybe_single().execute()
    if not client.data:
        raise HTTPException(status_code=404, detail="Client not found")

    resp = (
        sb.table("records")
        .select("id, title, status, created_at, updated_at, listings, report_html, analysis, mail_html")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .execute()
    )

    results: list[dict[str, Any]] = []
    for r in resp.data:
        listings = r.get("listings") or []
        results.append(
            {
                "id": r["id"],
                "title": r.get("title"),
                "status": r["status"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "listings_count": len(listings) if isinstance(listings, list) else 0,
                "has_report_html": bool(r.get("report_html")),
                "has_analysis": bool(r.get("analysis")),
                "has_mail_html": bool(r.get("mail_html")),
            }
        )
    return results


@app.get("/records/{record_id}/report.html")
async def get_report_html(record_id: str):
    """Return the rendered HTML report for a record."""
    sb = get_supabase()
    resp = sb.table("records").select("report_html").eq("id", record_id).maybe_single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Record not found")
    html = resp.data.get("report_html")
    if not html:
        raise HTTPException(status_code=404, detail="Report HTML not generated yet")
    from fastapi.responses import HTMLResponse

    return HTMLResponse(content=html, media_type="text/html")


@app.get("/records/{record_id}/analysis.json")
async def get_analysis_json(record_id: str):
    """Return the AI analysis JSON for a record."""
    sb = get_supabase()
    resp = sb.table("records").select("analysis").eq("id", record_id).maybe_single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Record not found")
    analysis = resp.data.get("analysis")
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not available")
    from fastapi.responses import JSONResponse

    return JSONResponse(content=analysis)


@app.get("/records/{record_id}/lots.json")
async def get_lots_json(record_id: str):
    """Return the raw listings (lots) JSON for a record."""
    sb = get_supabase()
    resp = sb.table("records").select("listings").eq("id", record_id).maybe_single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Record not found")
    listings = resp.data.get("listings")
    if listings is None:
        raise HTTPException(status_code=404, detail="Listings not available")
    from fastapi.responses import JSONResponse

    return JSONResponse(content=listings)


@app.get("/records/{record_id}/mail.html")
async def get_mail_html(record_id: str):
    """Return the email HTML for a record."""
    sb = get_supabase()
    resp = sb.table("records").select("mail_html").eq("id", record_id).maybe_single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Record not found")
    mail = resp.data.get("mail_html")
    if not mail:
        raise HTTPException(status_code=404, detail="Mail HTML not generated yet")
    from fastapi.responses import HTMLResponse

    return HTMLResponse(content=mail, media_type="text/html")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", include_in_schema=True)
async def health():
    return {"status": "ok"}
