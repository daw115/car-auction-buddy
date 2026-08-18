"""Model nie może zdradzić tego, czego nie dostał.

Raport klienta w trybie LLM powstaje z JSON-a wrzuconego do promptu. Payload był
wspólny z raportem brokera, więc model widział cenę aukcyjną, nasz wynik punktowy,
werdykt i czerwone flagi — a jedyną barierą było to, że akurat ich nie użył.

Reguła w prompcie jest prośbą, nie zabezpieczeniem: przy tysiącu generowań kiedyś
zostanie pominięta, a wyjdzie to dopiero u klienta. Ten sam błąd znaleziono
w szablonie hybrydowym, gdzie pola były wypisane wprost w HTML-u.
"""

import json

import pytest

from parser.models import AIAnalysis, AnalyzedLot, CarLot
from report.llm_html_reports import _lot_data_for_prompt

LOT = CarLot(
    source="copart",
    lot_id="55512345",
    url="https://copart.com/lot/55512345",
    year=2021,
    make="Volvo",
    model="XC60",
    damage_primary="RIGHT SIDE",
    current_bid_usd=9800,
    seller_type="insurance",
)
ANALIZA = AIAnalysis(
    lot_id="55512345",
    score=8.2,
    recommendation="POLECAM",
    red_flags=["Salvage title"],
    estimated_repair_usd=2500,
    client_description_pl="Opis.",
    ai_notes="Notatka dla brokera.",
)
ITEM = AnalyzedLot(lot=LOT, analysis=ANALIZA)


def _payload(dla_klienta: bool) -> dict:
    return json.loads(_lot_data_for_prompt(ITEM, None, dla_klienta=dla_klienta))


@pytest.mark.parametrize(
    "pole",
    [
        "current_bid_usd",
        "buy_now_price_usd",
        "seller_reserve_usd",
        "seller_type",
        "ai_score",
        "ai_recommendation",
        "ai_red_flags",
        "ai_notes",
        "ai_estimated_repair_usd",
        "url",
    ],
)
def test_model_nie_widzi_pola_wewnetrznego(pole: str) -> None:
    assert pole not in _payload(dla_klienta=True)


def test_broker_dostaje_komplet() -> None:
    """Odcinamy klientowi, nie brokerowi — jemu te liczby są do pracy potrzebne."""
    broker = _payload(dla_klienta=False)
    assert broker["ai_score"] == 8.2
    assert broker["current_bid_usd"] == 9800
    assert broker["ai_recommendation"] == "POLECAM"


def test_klient_dostaje_uszkodzenie_po_polsku() -> None:
    assert _payload(dla_klienta=True)["damage_primary"] == "uszkodzony prawy bok"


def test_klient_nadal_wie_co_to_za_auto() -> None:
    """Odcięcie nie może zabrać danych, dla których ten raport powstaje."""
    klient = _payload(dla_klienta=True)
    assert klient["make"] == "Volvo"
    assert klient["odometer_mi"] == LOT.odometer_mi
    assert klient["title_type"] == LOT.title_type
