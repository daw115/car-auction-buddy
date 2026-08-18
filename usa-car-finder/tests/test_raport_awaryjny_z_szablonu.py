"""Gdy model odda JSON nie do odczytania, raport i tak ma powstać.

W logu produkcyjnym widać 34 przypadki „report failed": model oddaje JSON
z usterką w środku prozy, parser się poddaje, plik nie zostaje zapisany.
Broker dostawał wtedy listę, w której część aut ma raport, a część nie — bez
słowa dlaczego. Szablon nie potrzebuje modelu i zawsze się wyrenderuje.

Test sprawdza samo renderowanie awaryjne: że dla lota, dla którego ścieżka
modelowa padła, deterministyczny szablon daje kompletny dokument.
"""

import pytest

from parser.models import AIAnalysis, AnalyzedLot, CarLot
from report.html_reports import render_broker_report, render_client_report

LOT = CarLot(
    source="iaai",
    lot_id="46010418",  # ten sam, który padał w logu
    url="https://iaai.com/lot/46010418",
    year=2015,
    make="MERCEDES-BENZ",
    model="CLA 250",
    damage_primary="FRONT END",
    current_bid_usd=6800,
)
ITEM = AnalyzedLot(
    lot=LOT,
    analysis=AIAnalysis(
        lot_id="46010418",
        score=7.1,
        recommendation="POLECAM",
        client_description_pl="",
    ),
)


@pytest.mark.parametrize("render", [render_client_report, render_broker_report])
def test_szablon_dziala_bez_modelu(render) -> None:
    html = render(ITEM)
    assert html.strip().startswith("<!DOCTYPE html>") or "<html" in html
    assert "CLA 250" in html
    assert len(html) > 1000, "raport awaryjny nie może być pustą skorupą"


def test_szablon_klienta_nie_wnosi_danych_wewnetrznych() -> None:
    """Zejście na szablon nie może obejść reguł treści dla klienta."""
    html = render_client_report(ITEM)
    assert "POLECAM" not in html
    assert "7.1" not in html
    assert "6800" not in html and "6 800" not in html


def test_szablon_tlumaczy_uszkodzenie() -> None:
    assert "Uszkodzony przód" in render_client_report(ITEM)
