"""Limit zgłoszeń ma dotyczyć jednego adresu, nie całego świata.

Panel woła backend PO STRONIE SERWERA, więc bez przekazanego nagłówka backend
widzi zawsze `127.0.0.1`. Limit „10 zgłoszeń na godzinę z tego adresu" działał
przez to jak limit globalny dla całej strony: jedenasty klient w ciągu godziny —
obojętne skąd — dostawał odmowę, a lead przepadał bez śladu w skrzynce.

Do tego pułapka na boty sprawdzana była PO limicie, więc bot łomoczący raz na
sześć minut wyczerpywał budżet przeznaczony dla prawdziwych klientów.
"""

import pytest
from fastapi import HTTPException

from api import sales_routes


class _ZadanieUdawane:
    def __init__(self, naglowki: dict, host: str = "127.0.0.1"):
        self.headers = {k.lower(): v for k, v in naglowki.items()}
        self.client = type("K", (), {"host": host})()


@pytest.fixture(autouse=True)
def czyste_liczniki():
    sales_routes._hits.clear()
    yield
    sales_routes._hits.clear()


def test_adres_z_krawedzi_cloudflare_ma_pierwszenstwo() -> None:
    """Klient nie ma jak podrobić `cf-connecting-ip` — wstawia go Cloudflare."""
    zadanie = _ZadanieUdawane({"cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "1.2.3.4"})
    assert sales_routes._client_ip(zadanie) == "203.0.113.7"


def test_bez_naglowkow_zostaje_loopback() -> None:
    """To jest dokładnie ten przypadek, w którym limit stawał się globalny."""
    assert sales_routes._client_ip(_ZadanieUdawane({})) == "127.0.0.1"


def test_dwaj_klienci_maja_osobne_budzety() -> None:
    limit = sales_routes.RATE_LIMIT_MAX
    pierwszy = _ZadanieUdawane({"cf-connecting-ip": "203.0.113.7"})
    drugi = _ZadanieUdawane({"cf-connecting-ip": "198.51.100.9"})

    for _ in range(limit):
        sales_routes._rate_limit(pierwszy)
    with pytest.raises(HTTPException) as blad:
        sales_routes._rate_limit(pierwszy)
    assert blad.value.status_code == 429

    # Drugi klient nie może płacić za pierwszego.
    sales_routes._rate_limit(drugi)


def test_odmowa_zostawia_slad_w_logu(caplog) -> None:
    """Odrzucone zgłoszenie nie istnieje nigdzie indziej — `_rate_limit` rzuca
    przed zapisem leada, więc bez wpisu w logu broker nie ma czego szukać."""
    import logging

    zadanie = _ZadanieUdawane({"cf-connecting-ip": "203.0.113.7"})
    for _ in range(sales_routes.RATE_LIMIT_MAX):
        sales_routes._rate_limit(zadanie)

    with caplog.at_level(logging.WARNING, logger="api.sales"):
        with pytest.raises(HTTPException):
            sales_routes._rate_limit(zadanie, opis_zgloszenia="600100200")
    # `getMessage()` skleja wzorzec z argumentami — inaczej telefon siedzi
    # w `r.args`, a nie w `r.message`, i asercja szuka go w złym miejscu.
    assert any("600100200" in r.getMessage() for r in caplog.records), (
        "brak śladu po odrzuconym leadzie"
    )
