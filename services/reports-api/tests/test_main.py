from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("REPORTS_API_KEY", "test-api-key-with-at-least-32-characters")

from main import Settings, create_app  # noqa: E402

API_KEY = "test-api-key-with-at-least-32-characters"
CLIENT_ID = "11111111-1111-4111-8111-111111111111"
RECORD_ID = "22222222-2222-4222-8222-222222222222"


@dataclass
class FakeResponse:
    data: Any


class FakeQuery:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = deepcopy(rows)
        self.filters: list[tuple[str, Any]] = []
        self.single = False

    def select(self, _columns: str):
        return self

    def eq(self, column: str, value: Any):
        self.filters.append((column, value))
        return self

    def maybe_single(self):
        self.single = True
        return self

    def order(self, _column: str, *, desc: bool = False):
        if desc:
            self.rows.reverse()
        return self

    def execute(self):
        rows = [
            row
            for row in self.rows
            if all(str(row.get(column)) == str(value) for column, value in self.filters)
        ]
        return FakeResponse(
            rows[0] if self.single and rows else None if self.single else rows
        )


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "clients": [
                {
                    "id": CLIENT_ID,
                    "name": "Test Client",
                    "contact": None,
                    "notes": None,
                    "created_at": "2026-07-16T00:00:00Z",
                }
            ],
            "records": [
                {
                    "id": RECORD_ID,
                    "client_id": CLIENT_ID,
                    "title": "Test report",
                    "status": "ready",
                    "created_at": "2026-07-16T00:00:00Z",
                    "updated_at": "2026-07-16T00:01:00Z",
                    "listings": [],
                    "report_html": (
                        "<!doctype html><html lang='pl'><head>"
                        "<meta charset='utf-8'>"
                        "<link rel='stylesheet' "
                        "href='https://fonts.googleapis.com/css2?family=DM+Sans'>"
                        "<style>.report{color:#123}</style></head>"
                        "<body><a href='https://auction.example/lot/1'>lot</a>"
                        "<img alt='car' src='https://images.example/car.jpg'>"
                        "<div class='report' style='font-weight:700'>report</div>"
                        "</body></html>"
                    ),
                    "analysis": {"score": 8},
                    "mail_html": "<html><body>mail</body></html>",
                }
            ],
        }

    def table(self, name: str):
        return FakeQuery(self.tables[name])


@pytest.fixture
def settings() -> Settings:
    return Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-role-key",
        reports_api_key=API_KEY,
        cors_origins=("https://dashboard.example",),
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings, FakeSupabase()))


def auth_headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def test_health_is_public_and_has_security_headers(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_private_endpoints_reject_missing_or_wrong_key(client: TestClient, headers):
    response = client.get("/clients", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "APIKey"


def test_private_endpoint_accepts_exact_key(client: TestClient):
    response = client.get("/clients", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()[0]["name"] == "Test Client"


def test_interactive_api_docs_are_not_exposed(client: TestClient):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_record_ids_must_be_valid_uuids(client: TestClient):
    response = client.get("/records/not-a-uuid/report.html", headers=auth_headers())
    assert response.status_code == 422


def test_html_is_downloaded_with_a_sandboxed_csp(client: TestClient):
    response = client.get(f"/records/{RECORD_ID}/report.html", headers=auth_headers())
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('-report.html"')
    assert response.headers["content-security-policy"].startswith("sandbox;")
    assert "allow-scripts" not in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert "https://images.example/car.jpg" not in response.text
    assert "data:image/gif;base64," in response.text


def test_mail_artifact_uses_an_html_filename(client: TestClient):
    response = client.get(f"/records/{RECORD_ID}/mail.html", headers=auth_headers())
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('-mail.html"')


@pytest.mark.parametrize(
    "unsafe_html",
    [
        "<html><script>alert(1)</script></html>",
        "<img src=x onerror=alert(1)>",
        "<a href='java&#x73;cript:alert(1)'>open</a>",
        "<a href='data:text/html,%3Cscript%3Ealert(1)%3C/script%3E'>open</a>",
        "<a href='file:///etc/passwd'>open</a>",
        "<img srcset='//evil.example/x.png 1x'>",
        "<a href='https://safe.example' ping='https://evil.example/track'>open</a>",
        "<video poster='https://evil.example/poster.png'></video>",
        "<link rel='preload' href='https://fonts.googleapis.com/font.woff2'>",
        "<meta http-equiv='refresh' content='0;url=https://evil.example'>",
        "<svg onload='alert(1)'></svg>",
        '<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
        "<div style='background:url(javascript:alert(1))'>x</div>",
        "<div style='background:u\\72l(https://evil.example/track)'>x</div>",
        "<div style=\"background-image:image-set('https://evil.example/x' 1x)\">x</div>",
        "<style>@import 'https://evil.example/track.css';</style>",
    ],
)
def test_active_html_is_rejected(settings: Settings, unsafe_html: str):
    supabase = FakeSupabase()
    supabase.tables["records"][0]["report_html"] = unsafe_html
    unsafe_client = TestClient(create_app(settings, supabase))

    response = unsafe_client.get(
        f"/records/{RECORD_ID}/report.html", headers=auth_headers()
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "HTML artifact contains active content"}


def test_empty_listing_array_is_a_valid_artifact(client: TestClient):
    response = client.get(f"/records/{RECORD_ID}/lots.json", headers=auth_headers())
    assert response.status_code == 200
    assert response.json() == []


def test_missing_record_returns_not_found(client: TestClient):
    missing_id = UUID("33333333-3333-4333-8333-333333333333")
    response = client.get(
        f"/records/{missing_id}/analysis.json", headers=auth_headers()
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Record not found"}


def test_cors_allows_only_the_configured_origin(client: TestClient):
    allowed = client.options(
        "/clients",
        headers={
            "Origin": "https://dashboard.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )
    blocked = client.options(
        "/clients",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://dashboard.example"
    assert "access-control-allow-origin" not in blocked.headers


def test_settings_reject_weak_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("REPORTS_API_KEY", "short")
    with pytest.raises(RuntimeError, match="at least 32"):
        Settings.from_env()


def test_settings_reject_wildcard_cors(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("REPORTS_API_KEY", API_KEY)
    monkeypatch.setenv("REPORTS_API_CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="canonical"):
        Settings.from_env()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.supabase.co",
        "https://user:password@example.supabase.co",
        "https://example.supabase.co/rest/v1",
        "https://example.supabase.co?query=value",
        "https://example.supabase.co:99999",
        "https://%65xample.supabase.co",
        "https://example..supabase.co",
    ],
)
def test_settings_reject_noncanonical_supabase_url(
    monkeypatch: pytest.MonkeyPatch, url: str
):
    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("REPORTS_API_KEY", API_KEY)
    monkeypatch.delenv("REPORTS_API_CORS_ORIGINS", raising=False)
    with pytest.raises(RuntimeError, match="canonical"):
        Settings.from_env()


@pytest.mark.parametrize(
    "origin",
    [
        "https://dashboard.example:99999",
        "https://%64ashboard.example",
        "https://dashboard.example/path",
    ],
)
def test_settings_reject_noncanonical_cors_origin(
    monkeypatch: pytest.MonkeyPatch, origin: str
):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("REPORTS_API_KEY", API_KEY)
    monkeypatch.setenv("REPORTS_API_CORS_ORIGINS", origin)
    with pytest.raises(RuntimeError, match="canonical"):
        Settings.from_env()


def test_settings_normalize_default_ports_and_trailing_slashes(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SUPABASE_URL", "https://EXAMPLE.supabase.co:443/")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setenv("REPORTS_API_KEY", API_KEY)
    monkeypatch.setenv(
        "REPORTS_API_CORS_ORIGINS",
        "https://DASHBOARD.example:443/,http://localhost:80/",
    )

    settings = Settings.from_env()

    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.cors_origins == (
        "https://dashboard.example",
        "http://localhost",
    )
