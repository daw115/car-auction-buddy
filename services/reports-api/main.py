"""Authenticated, read-only API for generated Car Auction Buddy reports."""

from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass
from hmac import compare_digest
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import html5lib
import tinycss2
from fastapi import APIRouter, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from supabase import Client, create_client

MIN_API_KEY_LENGTH = 32
SAFE_IMAGE_PLACEHOLDER = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
HTML_CONTENT_SECURITY_POLICY = (
    "sandbox; default-src 'none'; img-src data:; "
    "style-src 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com"
)


def normalize_exact_origin(
    raw_value: str, name: str, allowed_schemes: frozenset[str]
) -> str:
    """Validate and serialize an exact browser-style HTTP origin."""
    if (
        not raw_value.isascii()
        or "\\" in raw_value
        or any(character.isspace() for character in raw_value)
    ):
        raise RuntimeError(f"{name} must be a canonical HTTP(S) origin")

    try:
        parsed = urlparse(raw_value)
        port = parsed.port
    except ValueError as error:
        raise RuntimeError(f"{name} must be a canonical HTTP(S) origin") from error

    hostname = parsed.hostname
    if (
        parsed.scheme not in allowed_schemes
        or not hostname
        or parsed.username
        or parsed.password
        or "%" in parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(f"{name} must be a canonical HTTP(S) origin")

    host = hostname.lower()
    try:
        ipaddress.ip_address(host)
        serialized_host = f"[{host}]" if ":" in host else host
    except ValueError:
        labels = host.split(".")
        if any(
            not label
            or len(label) > 63
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
            for label in labels
        ):
            raise RuntimeError(f"{name} must be a canonical HTTP(S) origin")
        serialized_host = host

    default_port = 443 if parsed.scheme == "https" else 80
    serialized_port = "" if port is None or port == default_port else f":{port}"
    return f"{parsed.scheme}://{serialized_host}{serialized_port}"


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_role_key: str
    reports_api_key: str
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        supabase_url = normalize_exact_origin(
            require_env("SUPABASE_URL"), "SUPABASE_URL", frozenset({"https"})
        )
        service_role_key = require_env("SUPABASE_SERVICE_ROLE_KEY")
        reports_api_key = require_env("REPORTS_API_KEY")
        if len(reports_api_key) < MIN_API_KEY_LENGTH:
            raise RuntimeError(
                f"REPORTS_API_KEY must contain at least {MIN_API_KEY_LENGTH} characters"
            )

        configured_origins = (
            origin.strip()
            for origin in os.getenv("REPORTS_API_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        cors_origins = tuple(
            dict.fromkeys(
                normalize_exact_origin(
                    origin,
                    "REPORTS_API_CORS_ORIGINS",
                    frozenset({"http", "https"}),
                )
                for origin in configured_origins
            )
        )
        return cls(
            supabase_url=supabase_url,
            supabase_service_role_key=service_role_key,
            reports_api_key=reports_api_key,
            cors_origins=cors_origins,
        )


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be configured")
    return value


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


def artifact_headers(record_id: UUID, artifact: str, extension: str) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Disposition": f'attachment; filename="{record_id}-{artifact}.{extension}"',
        "Content-Security-Policy": HTML_CONTENT_SECURITY_POLICY,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }


def ensure_safe_css(css: str, *, declarations_only: bool) -> None:
    """Reject CSS constructs that can fetch resources or execute legacy expressions."""
    nodes = (
        tinycss2.parse_declaration_list(css, skip_comments=True, skip_whitespace=True)
        if declarations_only
        else tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    )
    blocked_functions = {
        "cross-fade",
        "element",
        "expression",
        "image",
        "image-set",
        "paint",
        "url",
        "-webkit-image-set",
    }

    def is_unsafe(node) -> bool:
        node_type = getattr(node, "type", "")
        if node_type in {"error", "url"}:
            return True
        if (
            node_type == "function"
            and getattr(node, "lower_name", "") in blocked_functions
        ):
            return True
        if node_type == "at-rule" and getattr(node, "lower_at_keyword", "") in {
            "import",
            "namespace",
        }:
            return True
        for attribute in ("arguments", "content", "prelude", "value"):
            children = getattr(node, attribute, None)
            if isinstance(children, (list, tuple)) and any(
                is_unsafe(child) for child in children
            ):
                return True
        return False

    if any(is_unsafe(node) for node in nodes):
        raise HTTPException(
            status_code=409, detail="HTML artifact contains active content"
        )


def ensure_safe_html_artifact(html: str) -> str:
    """Reject active HTML and replace external images with an inert placeholder."""
    unsafe_tags = {
        "area",
        "audio",
        "base",
        "embed",
        "form",
        "iframe",
        "input",
        "math",
        "noscript",
        "object",
        "script",
        "source",
        "svg",
        "track",
        "video",
    }
    safe_inert_attributes = {
        "abbr",
        "align",
        "alt",
        "border",
        "cellpadding",
        "cellspacing",
        "charset",
        "class",
        "colspan",
        "content",
        "dir",
        "download",
        "headers",
        "height",
        "id",
        "lang",
        "media",
        "name",
        "rel",
        "role",
        "rowspan",
        "scope",
        "style",
        "target",
        "title",
        "type",
        "valign",
        "width",
    }
    allowed_url_attributes = {("a", "href"), ("img", "src"), ("link", "href")}
    modified = False
    try:
        document = html5lib.parse(
            html, treebuilder="etree", namespaceHTMLElements=False
        )
    except Exception as error:
        raise HTTPException(
            status_code=409, detail="HTML artifact is malformed"
        ) from error

    for element in document.iter():
        if not isinstance(element.tag, str):
            continue
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in unsafe_tags:
            raise HTTPException(
                status_code=409, detail="HTML artifact contains active content"
            )

        attributes = {
            str(name).rsplit("}", 1)[-1].lower(): str(value)
            for name, value in element.attrib.items()
        }
        if tag == "meta" and "http-equiv" in attributes:
            raise HTTPException(
                status_code=409, detail="HTML artifact contains active content"
            )
        if tag == "link" and attributes.get("rel", "").lower().split() != [
            "stylesheet"
        ]:
            raise HTTPException(
                status_code=409, detail="HTML artifact contains active content"
            )

        for name, value in attributes.items():
            compact_value = "".join(value.split()).lower()
            if name.startswith("on") or name in {"srcdoc", "formaction"}:
                raise HTTPException(
                    status_code=409, detail="HTML artifact contains active content"
                )
            if name == "style":
                ensure_safe_css(value, declarations_only=True)
            if name not in {"href", "src"}:
                is_safe_inert_attribute = (
                    name in safe_inert_attributes
                    or name.startswith("aria-")
                    or name.startswith("data-")
                )
                if not is_safe_inert_attribute:
                    raise HTTPException(
                        status_code=409, detail="HTML artifact contains active content"
                    )
                continue
            if (tag, name) not in allowed_url_attributes or compact_value.startswith(
                "//"
            ):
                raise HTTPException(
                    status_code=409, detail="HTML artifact contains active content"
                )

            try:
                parsed_uri = urlparse(compact_value)
                _ = parsed_uri.port
            except ValueError as error:
                raise HTTPException(
                    status_code=409, detail="HTML artifact contains active content"
                ) from error

            if tag == "a":
                if parsed_uri.scheme and parsed_uri.scheme not in {
                    "http",
                    "https",
                    "mailto",
                    "tel",
                }:
                    raise HTTPException(
                        status_code=409, detail="HTML artifact contains active content"
                    )
            elif tag == "img":
                if not compact_value.startswith("data:image/"):
                    element.set(name, SAFE_IMAGE_PLACEHOLDER)
                    modified = True
            elif (
                parsed_uri.scheme != "https"
                or parsed_uri.hostname != "fonts.googleapis.com"
            ):
                raise HTTPException(
                    status_code=409, detail="HTML artifact contains active content"
                )

        if tag == "style" and element.text:
            ensure_safe_css(element.text, declarations_only=False)

    if not modified:
        return html
    return html5lib.serialize(
        document,
        tree="etree",
        omit_optional_tags=False,
        quote_attr_values="always",
    )


def create_app(
    settings: Settings | None = None, supabase_client: Client | None = None
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    client = supabase_client or create_client(
        resolved_settings.supabase_url,
        resolved_settings.supabase_service_role_key,
    )
    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def verify_api_key(key: str | None = Security(api_key_header)) -> str:
        if not key or not compare_digest(key, resolved_settings.reports_api_key):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API key",
                headers={"WWW-Authenticate": "APIKey"},
            )
        return key

    app = FastAPI(
        title="Car Auction Buddy — Reports API",
        version="1.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = resolved_settings
    app.state.supabase = client

    if resolved_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET"],
            allow_headers=["X-API-Key", "Content-Type"],
            max_age=600,
        )

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    protected = APIRouter(dependencies=[Security(verify_api_key)])

    @protected.get("/clients", response_model=list[ClientOut])
    def list_clients():
        response = (
            client.table("clients")
            .select("id, name, contact, notes, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        return response.data

    @protected.get("/clients/{client_id}/records", response_model=list[RecordSummary])
    def list_client_records(client_id: UUID):
        client_id_string = str(client_id)
        existing_client = (
            client.table("clients")
            .select("id")
            .eq("id", client_id_string)
            .maybe_single()
            .execute()
        )
        if not existing_client.data:
            raise HTTPException(status_code=404, detail="Client not found")

        response = (
            client.table("records")
            .select(
                "id, title, status, created_at, updated_at, listings, "
                "report_html, analysis, mail_html"
            )
            .eq("client_id", client_id_string)
            .order("created_at", desc=True)
            .execute()
        )
        results: list[dict[str, Any]] = []
        for record in response.data:
            listings = record.get("listings") or []
            results.append(
                {
                    "id": record["id"],
                    "title": record.get("title"),
                    "status": record["status"],
                    "created_at": record["created_at"],
                    "updated_at": record["updated_at"],
                    "listings_count": len(listings)
                    if isinstance(listings, list)
                    else 0,
                    "has_report_html": bool(record.get("report_html")),
                    "has_analysis": bool(record.get("analysis")),
                    "has_mail_html": bool(record.get("mail_html")),
                }
            )
        return results

    def get_record_artifact(record_id: UUID, column: str, unavailable_message: str):
        response = (
            client.table("records")
            .select(column)
            .eq("id", str(record_id))
            .maybe_single()
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail="Record not found")
        value = response.data.get(column)
        if value is None or value == "":
            raise HTTPException(status_code=404, detail=unavailable_message)
        return value

    @protected.get("/records/{record_id}/report.html")
    def get_report_html(record_id: UUID):
        html = ensure_safe_html_artifact(
            get_record_artifact(
                record_id, "report_html", "Report HTML not generated yet"
            )
        )
        return HTMLResponse(
            content=html,
            headers=artifact_headers(record_id, "report", "html"),
        )

    @protected.get("/records/{record_id}/analysis.json")
    def get_analysis_json(record_id: UUID):
        analysis = get_record_artifact(record_id, "analysis", "Analysis not available")
        return JSONResponse(
            content=analysis,
            headers=artifact_headers(record_id, "analysis", "json"),
        )

    @protected.get("/records/{record_id}/lots.json")
    def get_lots_json(record_id: UUID):
        listings = get_record_artifact(record_id, "listings", "Listings not available")
        return JSONResponse(
            content=listings,
            headers=artifact_headers(record_id, "lots", "json"),
        )

    @protected.get("/records/{record_id}/mail.html")
    def get_mail_html(record_id: UUID):
        mail = ensure_safe_html_artifact(
            get_record_artifact(record_id, "mail_html", "Mail HTML not generated yet")
        )
        return HTMLResponse(
            content=mail,
            headers=artifact_headers(record_id, "mail", "html"),
        )

    app.include_router(protected)
    return app


app = create_app()
