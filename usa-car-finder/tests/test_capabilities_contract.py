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
        assert capability.get("mode") in {"live", "unavailable"}
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
        manheim_session_ready=False,
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
            "reason": "manheim_session_not_configured",
        },
    }


def test_manheim_is_live_only_when_flag_and_session_agree() -> None:
    checked_at = datetime(2026, 7, 19, 12, 30, tzinfo=timezone.utc)

    def manheim(*, enabled: bool, session: bool) -> dict:
        payload = api_main.build_auction_source_capabilities(
            checked_at=checked_at,
            copart_ready=True,
            iaai_ready=True,
            manheim_enabled=enabled,
            manheim_session_ready=session,
        ).model_dump(mode="json", by_alias=True)
        _assert_exact_frontend_contract(payload)
        return payload["sources"]["manheim"]

    assert manheim(enabled=True, session=True) == {"available": True, "mode": "live"}
    unavailable = {
        "available": False,
        "mode": "unavailable",
        "reason": "manheim_session_not_configured",
    }
    assert manheim(enabled=True, session=False) == unavailable
    assert manheim(enabled=False, session=True) == unavailable
    assert manheim(enabled=False, session=False) == unavailable


def test_strict_models_reject_extra_sources_and_oversized_reasons() -> None:
    base = {
        "checkedAt": "2026-07-19T12:30:00Z",
        "sources": {
            "copart": {"available": True, "mode": "live"},
            "iaai": {"available": True, "mode": "live"},
            "manheim": {
                "available": False,
                "mode": "unavailable",
                "reason": "manheim_session_not_configured",
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
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    sentinel = "task-3-3-server-only-sentinel"
    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", sentinel)
    monkeypatch.setattr(api_main, "USE_MOCK_DATA", False)
    monkeypatch.setenv("MANHEIM_BACKEND_ENABLED", "true")
    # Sesja Manheima zależy od katalogów na dysku — celujemy w nieistniejące,
    # żeby test sprawdzał regułę ("sama flaga nie wystarczy"), a nie to, czy
    # akurat na tej maszynie ktoś zalogował BidWise.
    monkeypatch.setenv("MANHEIM_CHROME_CDP_URL", "")
    monkeypatch.setenv("MANHEIM_EXTENSION_DIR", str(tmp_path / "bez-wtyczki"))
    monkeypatch.setenv("MANHEIM_CHROME_PROFILE_DIR", str(tmp_path / "bez-profilu"))
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
    # Sama flaga nie wystarczy — i powód mówi, czego brakuje. W trybie kolektora
    # znaczy to "przeglądarka się nie odezwała", a nie "nie ma konfiguracji".
    assert payload["sources"]["manheim"] == {
        "available": False,
        "mode": "unavailable",
        "reason": "collector_not_seen_recently",
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


def test_rejected_collector_is_named_as_a_token_mismatch(monkeypatch):
    """Najczęstsza awaria Manheima ma mieć własny powód, nie wspólny worek.

    Zalogowana przeglądarka odbijana na 403 wyglądała dotąd identycznie jak brak
    konfiguracji — a naprawa to jedno pole w opcjach rozszerzenia.
    """
    from api import manheim_ingest as ingest_store
    from scraper.manheim_session import unavailable_reason

    monkeypatch.setenv("MANHEIM_SOURCE_MODE", "collector")
    ingest_store.note_rejection(403, "token rozszerzenia się nie zgadza")
    assert unavailable_reason() == "collector_token_mismatch"

    ingest_store.note_rejection(401, "kolektor nie podał tokena")
    assert unavailable_reason() == "collector_unauthorized"


def test_rejection_shows_up_in_the_ingest_status(monkeypatch):
    from api import manheim_ingest as ingest_store

    ingest_store.note_rejection(403, "token rozszerzenia się nie zgadza")
    rejection = ingest_store.status()["lastRejection"]

    assert rejection["status"] == 403
    assert "token" in rejection["detail"]
