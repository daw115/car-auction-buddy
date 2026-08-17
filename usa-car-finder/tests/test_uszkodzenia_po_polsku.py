"""Kody uszkodzeń z aukcji trafiają do klienta po polsku.

Napis „RIGHT SIDE" w polskim zdaniu oferty mówi klientowi jedno: że tekst jest
skądś przeklejony. Testy pilnują tłumaczenia, a przede wszystkim tego, że
nieznanego kodu NIE zgadujemy — zła polska nazwa szkody zostanie wzięta za
ustalenie, angielska co najwyżej za pytanie do brokera.
"""

import pytest

from report.uszkodzenia import opis, po_polsku


@pytest.mark.parametrize(
    "kod,oczekiwane",
    [
        ("RIGHT SIDE", "Uszkodzony prawy bok"),
        ("ALL OVER", "Uszkodzenia na całym nadwoziu"),
        ("WATER/FLOOD", "Auto zalane"),
        ("WATER / FLOOD", "Auto zalane"),  # aukcje piszą to na oba sposoby
        ("front end", "Uszkodzony przód"),
        ("  Normal   Wear  ", "Normalne zużycie"),
        ("MINOR DENT/SCRATCHES", "Drobne wgniecenia i rysy"),
    ],
)
def test_tlumaczy_kody_aukcji(kod: str, oczekiwane: str) -> None:
    assert po_polsku(kod) == oczekiwane


def test_nieznany_kod_wraca_bez_zmian() -> None:
    """Bez zgadywania. Lepiej pokazać kod aukcji niż wymyśloną szkodę."""
    assert po_polsku("SOMETHING NEW") == "SOMETHING NEW"


def test_pusty_kod_nie_daje_smieci() -> None:
    assert po_polsku("") == ""
    assert opis("", None) == "brak danych"


def test_dwie_szkody_skladaja_sie_w_zdanie() -> None:
    assert opis("FRONT END", "RIGHT SIDE") == "Uszkodzony przód, uszkodzony prawy bok"


def test_jedna_szkoda_zostaje_sama() -> None:
    assert opis("HAIL", None) == "Uszkodzenia od gradu"
