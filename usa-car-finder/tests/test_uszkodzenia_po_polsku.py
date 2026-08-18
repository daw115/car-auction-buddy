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


def test_all_over_to_nie_dachowanie() -> None:
    """Regresja: poprzednia tabela w offer_agent miała „all over" w jednym wzorcu
    z „rollover" i mówiła klientowi o dachowaniu, którego nie było."""
    assert po_polsku("ALL OVER") == "Uszkodzenia na całym nadwoziu"
    assert "achowanie" not in po_polsku("ALL OVER")
    assert po_polsku("ROLLOVER") == "Dachowanie"


def test_wzorzec_lapie_warianty_spoza_slownika() -> None:
    """Aukcje wypisują kombinacje, których nikt nie skatalogował."""
    assert po_polsku("LEFT FRONT END") == "Uszkodzony lewy przód"
    assert po_polsku("ENGINE BURN") == "Ślady pożaru"


def test_slownik_ma_pierwszenstwo_przed_wzorcem() -> None:
    """„TOP/ROOF" pasuje też do wzorca na dach — ma wygrać dokładne trafienie."""
    assert po_polsku("TOP/ROOF") == "Uszkodzony dach"


def test_rozpoznaj_przyznaje_sie_do_nieznajomosci() -> None:
    """W prozie oferty angielski napis wygląda na tekst niedokończony, więc
    wołający musi móc odróżnić „nie wiem" od tłumaczenia."""
    from report.uszkodzenia import rozpoznaj

    assert rozpoznaj("COS ZUPELNIE NOWEGO") is None
    assert rozpoznaj("RIGHT SIDE") == "Uszkodzony prawy bok"
    assert rozpoznaj("RIGHT SIDE", mala=True) == "uszkodzony prawy bok"


def test_agent_ofert_korzysta_z_tego_samego_slownika() -> None:
    """Dwie tabele dla tego samego kodu rozjeżdżają się po cichu — i rozjechały."""
    from parser.models import CarLot
    from report.offer_agent import _damage_pl

    lot = CarLot(source="copart", lot_id="1", url="https://x/1", damage_primary="ALL OVER")
    assert _damage_pl(lot) == "uszkodzenia na całym nadwoziu"

    nieznany = CarLot(source="copart", lot_id="2", url="https://x/2", damage_primary="COS NOWEGO")
    assert _damage_pl(nieznany) == "zakres uszkodzeń do potwierdzenia"
