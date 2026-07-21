import asyncio
import builtins
import os
import socket
import sqlite3
import subprocess

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from hypothesis import example, given, settings, strategies as st
from pydantic import ValidationError

os.environ["SCRAPER_API_TOKEN"] = "preservation-valid-sentinel"
os.environ["PUBLIC_BASE_URL"] = "https://viewer.invalid"
os.environ["USE_EXTENSIONS"] = "false"
os.environ["USE_MOCK_DATA"] = "false"

from api import main as api_main
from parser.models import ClientCriteria

# **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**


def route(path: str) -> APIRoute:
    return next(
        item
        for item in api_main.app.routes
        if isinstance(item, APIRoute) and item.path == path
    )


def normalized_route(path: str) -> dict[str, object]:
    item = route(path)
    return {
        "path": item.path,
        "methods": sorted(item.methods),
        "name": item.name,
        "response_class": getattr(
            item.response_class, "__name__", type(item.response_class).__name__
        ),
        "dependencies": [
            getattr(dependency.call, "__name__", str(dependency.call))
            for dependency in item.dependant.dependencies
        ],
    }

EXPECTED_ROUTES = [
    {
        "path": "/api/logs/stream",
        "methods": ["GET"],
        "name": "logs_stream",
        "response_class": "DefaultPlaceholder",
        "dependencies": ["_require_bearer"],
    },
    {
        "path": "/api/logs/tail",
        "methods": ["GET"],
        "name": "logs_tail",
        "response_class": "DefaultPlaceholder",
        "dependencies": ["_require_bearer"],
    },
    {
        "path": "/api/search",
        "methods": ["POST"],
        "name": "dashboard_search",
        "response_class": "DefaultPlaceholder",
        "dependencies": ["_require_bearer"],
    },
    {
        "path": "/config",
        "methods": ["GET"],
        "name": "config",
        "response_class": "DefaultPlaceholder",
        "dependencies": [],
    },
    {
        "path": "/health",
        "methods": ["GET"],
        "name": "health",
        "response_class": "DefaultPlaceholder",
        "dependencies": [],
    },
]


def test_health_and_representative_route_metadata_match_unfixed_baseline() -> None:
    response = TestClient(api_main.app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert isinstance(response.json()["use_extensions"], bool)
    assert isinstance(response.json()["use_mock_data"], bool)
    observed = [normalized_route(item["path"]) for item in EXPECTED_ROUTES]
    assert observed == EXPECTED_ROUTES

@settings(max_examples=30, deadline=None)
@example(token="preservation-valid-sentinel", invalid="wrong-sentinel")
@given(
    token=st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"),
            whitelist_characters="-_.:/",
        ),
        min_size=1,
        max_size=64,
    ),
    invalid=st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"),
            whitelist_characters="-_.:/",
        ),
        min_size=1,
        max_size=64,
    ),
)
def test_bearer_behavior_is_preserved_for_generated_non_bug_cases(
    token: str, invalid: str
) -> None:
    if invalid == token:
        invalid += "-different"
    api_main.SCRAPER_API_TOKEN = token

    with pytest.raises(HTTPException) as missing:
        api_main._require_bearer(None)
    assert (missing.value.status_code, missing.value.detail) == (401, "Brak Bearer tokena")

    with pytest.raises(HTTPException) as rejected:
        api_main._require_bearer(f"Bearer {invalid}")
    assert (rejected.value.status_code, rejected.value.detail) == (
        403,
        "Nieprawidłowy token",
    )

    assert api_main._require_bearer(f"Bearer {token}") is None


def test_unprotected_local_auth_behavior_is_preserved() -> None:
    api_main.SCRAPER_API_TOKEN = ""
    assert api_main._require_bearer(None) is None


def test_stream_retains_bearer_dependency_metadata() -> None:
    stream = route("/api/logs/stream")
    dependencies = [item.call for item in stream.dependant.dependencies]
    assert dependencies == [api_main._require_bearer]

@settings(max_examples=20, deadline=None)
@given(make=st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu")), min_size=1, max_size=30))
def test_copart_iaai_defaults_and_source_validation_are_preserved(make: str) -> None:
    criteria = ClientCriteria(make=make)
    assert criteria.sources == ["copart", "iaai"]
    assert ClientCriteria(make=make, sources=["copart"]).sources == ["copart"]
    assert ClientCriteria(make=make, sources=["iaai"]).sources == ["iaai"]
    assert ClientCriteria(make=make, sources=["copart", "iaai"]).sources == [
        "copart",
        "iaai",
    ]
    with pytest.raises(ValidationError):
        ClientCriteria(make=make, sources=["manheim"])


def test_capability_discovery_is_side_effect_free_on_unfixed_and_fixed_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_on_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("capability discovery attempted a forbidden side effect")

    original_import = builtins.__import__
    forbidden_imports = (
        "aiohttp",
        "playwright",
        "requests",
        "scraper.automated_scraper",
        "scraper.browser_context",
        "scraper.copart",
        "scraper.iaai",
    )

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith(forbidden_imports):
            fail_on_call()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(sqlite3, "connect", fail_on_call)
    monkeypatch.setattr(socket.socket, "connect", fail_on_call)
    monkeypatch.setattr(subprocess, "run", fail_on_call)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_on_call)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", fail_on_call)

    api_main.SCRAPER_API_TOKEN = "preservation-valid-sentinel"
    response = TestClient(api_main.app).get(
        "/api/capabilities",
        headers={"Authorization": "Bearer preservation-valid-sentinel"},
    )
    assert response.status_code in {200, 404}
