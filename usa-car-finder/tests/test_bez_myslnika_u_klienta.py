"""W tekście dla klienta nie ma długiego myślnika.

Myślnik (—) w polskim zdaniu czyta się jak tekst złożony maszynowo i jest
pierwszą rzeczą, po której widać, że oferty nie pisze człowiek. W dokumentach
brokerskich jest dozwolony, bo tam służy za znacznik „brak danych".

Regresja: obrazek oferty, czyli PIERWSZA rzecz, jaką klient dostaje, miał go
przy każdym aucie w linii o stanie („Uszkodzony przód — Naprawa nie jest
wliczona..."). Przeszło to przez wydanie 1.0.0 i wyszło dopiero przy oglądaniu
wyrenderowanego PNG.
"""

import re

from parser.models import AIAnalysis, AnalyzedLot, CarLot
from report.html_reports import render_client_report, render_client_shortlist

MYSLNIK = "—"

LOT = CarLot(
    source="copart",
    lot_id="88001",
    url="https://copart.com/lot/88001",
    year=2020,
    make="BMW",
    model="M5",
    current_bid_usd=18500,
    odometer_mi=71822,
    location_state="VA",
    damage_primary="FRONT END",
    damage_secondary="RIGHT FRONT",
)
ITEM = AnalyzedLot(
    lot=LOT,
    analysis=AIAnalysis(lot_id="88001", score=7.2, recommendation="POLECAM", client_description_pl=""),
)

LOT_Z_OCENA = CarLot(
    source="manheim",
    lot_id="88002",
    url="https://manheim.com/lot/88002",
    year=2021,
    make="LEXUS",
    model="RX",
    current_bid_usd=21000,
    location_state="NJ",
    damage_primary="Condition Grade 4.2",
)
ITEM_Z_OCENA = AnalyzedLot(
    lot=LOT_Z_OCENA,
    analysis=AIAnalysis(lot_id="88002", score=8.1, recommendation="POLECAM", client_description_pl=""),
)


def _widoczny_tekst(html: str) -> str:
    """Sam tekst, bez znaczników — myślnik w komentarzu Jinja nikomu nie szkodzi."""
    bez_komentarzy = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", bez_komentarzy)


def test_obrazek_oferty_bez_myslnika() -> None:
    tekst = _widoczny_tekst(render_client_shortlist([ITEM], pokaz_naglowek=False))
    assert MYSLNIK not in tekst, f"myślnik w ofercie: {_fragment(tekst)}"


def test_obrazek_oferty_z_ocena_stanu_bez_myslnika() -> None:
    """Druga gałąź `_stan_pojazdu` — loty z Manheima mają ocenę zamiast szkody."""
    tekst = _widoczny_tekst(render_client_shortlist([ITEM_Z_OCENA], pokaz_naglowek=False))
    assert MYSLNIK not in tekst, f"myślnik w ofercie: {_fragment(tekst)}"


def test_raport_dla_klienta_bez_myslnika() -> None:
    tekst = _widoczny_tekst(render_client_report(ITEM))
    assert MYSLNIK not in tekst, f"myślnik w raporcie: {_fragment(tekst)}"


def test_naglowek_oferty_tez_bez_myslnika() -> None:
    """Nagłówek bywa włączany osobno, więc sprawdzamy obie wersje."""
    tekst = _widoczny_tekst(render_client_shortlist([ITEM], pokaz_naglowek=True))
    assert MYSLNIK not in tekst, f"myślnik w nagłówku: {_fragment(tekst)}"


def _fragment(tekst: str) -> str:
    i = tekst.find(MYSLNIK)
    return repr(tekst[max(0, i - 60) : i + 60])
