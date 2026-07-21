import asyncio

from fastapi.routing import APIRoute

from api import main as api_main


def _route(path: str) -> APIRoute:
    return next(
        route
        for route in api_main.app.routes
        if isinstance(route, APIRoute) and route.path == path
    )


def _assert_defense_headers(response: object) -> None:
    headers = response.headers
    assert headers["cache-control"] == "no-store"
    assert headers["pragma"] == "no-cache"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_viewer_declares_html_response_in_openapi() -> None:
    route = _route("/api/logs/viewer")
    assert route.response_class is api_main.HTMLResponse

    schema = api_main.app.openapi()
    response_content = schema["paths"]["/api/logs/viewer"]["get"]["responses"]["200"]["content"]
    assert "text/html" in response_content


def test_protected_viewer_fails_closed_without_browser_credentials(monkeypatch) -> None:
    sentinel = "task-3-2-server-only-sentinel"
    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", sentinel)

    response = asyncio.run(api_main.logs_viewer())
    body = response.body.decode("utf-8")

    assert response.status_code == 403
    assert sentinel not in body
    assert all(
        marker not in body
        for marker in (
            "Authorization",
            "Bearer ",
            "/api/logs/stream",
            "const TOKEN",
            "localStorage",
            "sessionStorage",
        )
    )
    _assert_defense_headers(response)


def test_unprotected_local_viewer_streams_without_credentials(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", "")

    response = asyncio.run(api_main.logs_viewer())
    body = response.body.decode("utf-8")

    assert response.status_code == 200
    assert "fetch('/api/logs/stream'" in body
    assert all(
        marker not in body
        for marker in (
            "Authorization",
            "Bearer ",
            "const TOKEN",
            "localStorage",
            "sessionStorage",
        )
    )
    _assert_defense_headers(response)


def test_log_stream_retains_existing_bearer_dependency() -> None:
    stream = _route("/api/logs/stream")
    assert [dependency.call for dependency in stream.dependant.dependencies] == [
        api_main._require_bearer
    ]
