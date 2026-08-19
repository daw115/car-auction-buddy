"""Backend musi umieć powiedzieć, czym jest.

Panel ma `/api/version` od początku, backend nie miał nic: żeby sprawdzić, co
stoi na produkcji, trzeba było czytać `readlink /opt/usacar/current`. To pierwsze
pytanie przy każdej diagnozie, a przy dwóch wdrożeniach pod rząd łatwo tu
o pomyłkę.
"""

from fastapi.testclient import TestClient

from api import main as api_main
from wersja import WERSJA


def test_endpoint_oddaje_wersje() -> None:
    odp = TestClient(api_main.app).get("/version")
    assert odp.status_code == 200
    assert odp.json()["wersja"] == WERSJA


def test_fastapi_deklaruje_te_sama_wersje() -> None:
    """Numer w konstruktorze FastAPI był dotąd wpisany z ręki i nigdy
    nieaktualizowany — czyli nie znaczył nic."""
    assert api_main.app.version == WERSJA


def test_wersja_wyglada_jak_wersja() -> None:
    import re

    assert re.fullmatch(r"\d+\.\d+\.\d+", WERSJA), f"nie semver: {WERSJA!r}"
