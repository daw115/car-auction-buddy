import asyncio
import json
import os

from fastapi.testclient import TestClient
from hypothesis import example, given, settings, strategies as st

os.environ["SCRAPER_API_TOKEN"] = "server-only-sentinel"
os.environ["PUBLIC_BASE_URL"] = "https://viewer.invalid"
from api import main as api_main

# **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
SOURCES = {"copart", "iaai", "manheim"}
ALPHABET = list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/.\"'<>") + ["ł", "漢", "🙂"]


def assert_consumer_shape(payload: object) -> None:
    assert isinstance(payload, dict) and isinstance(payload.get("checkedAt"), str)
    sources = payload.get("sources")
    assert isinstance(sources, dict) and set(sources) == SOURCES
    for source in ("copart", "iaai", "manheim"):
        item = sources[source]
        assert isinstance(item.get("available"), bool)
        allowed = {"official_api", "unavailable"} if source == "manheim" else {"live", "unavailable"}
        assert item.get("mode") in allowed
        assert item["available"] == (item["mode"] != "unavailable")
        assert "reason" not in item or isinstance(item["reason"], str) and len(item["reason"]) <= 200


def test_openapi_contract_declares_html_viewer() -> None:
    schema = api_main.app.openapi()
    viewer = schema["paths"]["/api/logs/viewer"]["get"]
    assert "text/html" in viewer["responses"]["200"]["content"]


@settings(max_examples=30, deadline=None)
@example(token="server-only-sentinel")
@example(token="quote-'\"-markup-</script>")
@example(token="unicode-ł-漢-🙂")
@example(token="slash/path_and-long-" + "x" * 80)
@given(token=st.text(alphabet=ALPHABET, min_size=24, max_size=64))
def test_protected_viewer_never_discloses_or_constructs_server_bearer(token: str) -> None:
    api_main.SCRAPER_API_TOKEN = token
    response = asyncio.run(api_main.logs_viewer())
    body = response.body.decode("utf-8")
    visible = response.body + b"\n" + json.dumps(dict(response.headers)).encode()
    assert token.encode() not in visible
    assert all(marker not in body for marker in ("Authorization", "Bearer ", "/api/logs/stream", "localStorage", "sessionStorage"))


@settings(max_examples=12, deadline=None)
@example(manheim_enabled=None)
@given(manheim_enabled=st.one_of(st.none(), st.sampled_from(["false", "true", "TRUE", "malformed"])))
def test_authorized_capabilities_match_conservative_consumer_contract(manheim_enabled: str | None) -> None:
    api_main.SCRAPER_API_TOKEN = "server-only-sentinel"
    os.environ.pop("MANHEIM_BACKEND_ENABLED", None) if manheim_enabled is None else os.environ.__setitem__("MANHEIM_BACKEND_ENABLED", manheim_enabled)
    response = TestClient(api_main.app).get("/api/capabilities", headers={"Authorization": "Bearer server-only-sentinel"})
    assert response.status_code == 200
    assert_consumer_shape(response.json())
    assert "server-only-sentinel" not in response.text
    if manheim_enabled != "true":
        assert response.json()["sources"]["manheim"]["mode"] == "unavailable"
