from datetime import datetime, timezone

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api import main as api_main


SOURCES = {"copart", "iaai", "manheim"}


def _assert_exact_frontend_contract(payload: object) -> None:
    """Mirror auctionSourceCapabilitiesPayloadSchema from auction-sources.ts."""
    assert isinstance(payload, dict)
    assert isinstance(payload.get("checkedAt"), str)
    assert set(payload) == {"checkedAt", "sources"}

    sources = payload.get("sources")
    assert isinstance(sources, dict) and set(sources) == SOURCES
    for source in ("copart", "iaai", "manheim"):
        capability = sources[source]
        assert isinstance(capability, dict)
        assert set(capability) <= {"available", "mode", "reason"}
        assert isinstance(capability.get("available"), bool)
        allowed_modes = (
            {"official_api", "unavailable"}
            if source == "manheim"
            else {"live", "unavailable"}
        )
        assert capability.get("mode") in allowed_modes
        assert capability["available"] == (capability["mode"] != "unavailable")
        if "reason" in capability:
            assert isinstance(capability["reason"], str)
            assert len(capability["reason"]) <= 200


def test_pure_builder_maps_readiness_to_exact_source_contract() -> None:
    checked_at = datetime(2026, 7, 19, 12, 30, tzinfo=timezone.utc)

    payload = api_main.build_auction_source_capabilities(
        checked_at=checked_at,
        copart_ready=True,
        iaai_ready=False,
        manheim_enabled=True,
        manheim_adapter_ready=False,
    ).model_dump(mode="json", by_alias=True)

    _assert_exact_frontend_contract(payload)
    assert payload["checkedAt"] == "2026-07-19T12:30:00Z"
    assert payload["sources"] == {
        "copart": {"available": True, "mode": "live"},
        "iaai": {
            "available": False,
            "mode": "unavailable",
            "reason": "live_backend_not_configured",
        },
        "manheim": {
            "available": False,
            "mode": "unavailable",
            "reason": "credentials_or_adapter_missing",
        },
    }


def test_strict_models_reject_extra_sources_and_oversized_reasons() -> None:
    base = {
        "checkedAt": "2026-07-19T12:30:00Z",
        "sources": {
            "copart": {"available": True, "mode": "live"},
            "iaai": {"available": True, "mode": "live"},
            "manheim": {
                "available": False,
                "mode": "unavailable",
                "reason": "credentials_or_adapter_missing",
            },
        },
    }

    with pytest.raises(ValidationError):
        api_main.AuctionSourceCapabilitiesPayload.model_validate(
            {
                **base,
                "sources": {**base["sources"], "other": {"available": True}},
            }
        )

    with pytest.raises(ValidationError):
        api_main.AuctionSourceCapabilitiesPayload.model_validate(
            {
                **base,
                "sources": {
                    **base["sources"],
                    "manheim": {
                        "available": False,
                        "mode": "unavailable",
                        "reason": "x" * 201,
                    },
                },
            }
        )


def test_authenticated_endpoint_is_schema_valid_and_manheim_flag_alone_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "task-3-3-server-only-sentinel"
    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", sentinel)
    monkeypatch.setattr(api_main, "USE_MOCK_DATA", False)
    monkeypatch.setenv("MANHEIM_BACKEND_ENABLED", "true")
    client = TestClient(api_main.app)

    assert client.get("/api/capabilities").status_code == 401
    assert client.get(
        "/api/capabilities", headers={"Authorization": "Bearer invalid"}
    ).status_code == 403

    response = client.get(
        "/api/capabilities", headers={"Authorization": f"Bearer {sentinel}"}
    )
    assert response.status_code == 200
    assert sentinel not in response.text
    payload = response.json()
    _assert_exact_frontend_contract(payload)
    assert datetime.fromisoformat(payload["checkedAt"].replace("Z", "+00:00")).utcoffset() == timezone.utc.utcoffset(None)
    assert payload["sources"]["copart"] == {"available": True, "mode": "live"}
    assert payload["sources"]["iaai"] == {"available": True, "mode": "live"}
    assert payload["sources"]["manheim"] == {
        "available": False,
        "mode": "unavailable",
        "reason": "credentials_or_adapter_missing",
    }

    route = next(
        item
        for item in api_main.app.routes
        if isinstance(item, APIRoute) and item.path == "/api/capabilities"
    )
    assert route.response_model is api_main.AuctionSourceCapabilitiesPayload
    assert [dependency.call for dependency in route.dependant.dependencies] == [
        api_main._require_bearer
    ]


def test_mock_configuration_does_not_claim_live_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", "")
    monkeypatch.setattr(api_main, "USE_MOCK_DATA", True)

    payload = TestClient(api_main.app).get("/api/capabilities").json()
    for source in ("copart", "iaai"):
        assert payload["sources"][source] == {
            "available": False,
            "mode": "unavailable",
            "reason": "live_backend_not_configured",
        }
