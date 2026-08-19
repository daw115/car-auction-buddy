"""Klient nie może zobaczyć dwóch kwot za to samo auto.

Docstring `pricing.import_calculator.client_price_pln` mówi to wprost: to
„jedyna definicja ceny końcowej w całym systemie", a `private_total_pln` to
KOSZT SPROWADZENIA, nie cena sprzedaży. Mimo to obrazek oferty i raport
szczegółowy pokazywały `private_total_pln` pod etykietą „pod drzwi", a wiadomość
na WhatsAppie liczyła z prowizją.

Na lotach z produkcji różnica wynosiła 2 635 – 3 625 zł. Klient dostawał obie
kwoty w jednej rozmowie, a kto uwierzył obrazkowi, dopłacałby przy odbiorze —
czyli dokładnie ta niespodzianka, której oferta obiecuje nigdy nie robić.
"""

import re

from parser.models import AIAnalysis, AnalyzedLot, CarLot
from pricing.import_calculator import calculate_lot_import_costs
from report.html_reports import render_client_report, render_client_shortlist
from report.whatsapp import build_draft
from scoring.budget import landed_cost_for_lot

LOT = CarLot(
    source="copart",
    lot_id="77001",
    url="https://copart.com/lot/77001",
    year=2021,
    make="AUDI",
    model="A4",
    current_bid_usd=9800,
    location_state="NJ",
    damage_primary="FRONT END",
)
ITEM = AnalyzedLot(
    lot=LOT,
    analysis=AIAnalysis(lot_id="77001", score=7.4, recommendation="POLECAM", client_description_pl=""),
)


def _kwoty(html: str) -> set[int]:
    """Kwoty w złotówkach wypisane w dokumencie."""
    return {
        int(m.replace(" ", "").replace(" ", ""))
        for m in re.findall(r"([\d  ]{5,})\s*zł", html)
        if m.strip()
    }


def test_obrazek_oferty_pokazuje_cene_z_prowizja() -> None:
    naleznosc = round(landed_cost_for_lot(LOT, settlement="private"))
    kwoty = _kwoty(render_client_shortlist([ITEM], pokaz_naglowek=False))
    assert any(abs(k - naleznosc) <= 1 for k in kwoty), (
        f"obrazek nie pokazuje ceny końcowej {naleznosc}; widoczne kwoty: {sorted(kwoty)}"
    )


def test_raport_szczegolowy_pokazuje_te_sama_cene() -> None:
    naleznosc = round(landed_cost_for_lot(LOT, settlement="private"))
    kwoty = _kwoty(render_client_report(ITEM))
    assert any(abs(k - naleznosc) <= 1 for k in kwoty), (
        f"raport nie pokazuje ceny końcowej {naleznosc}; widoczne kwoty: {sorted(kwoty)}"
    )


def test_zaden_dokument_nie_pokazuje_kosztu_bez_prowizji() -> None:
    """To jest ta druga, niższa kwota — i to ona myliła klienta."""
    koszty = calculate_lot_import_costs(LOT)
    bez_prowizji = round(float(koszty["private_total_pln"]))
    naleznosc = round(landed_cost_for_lot(LOT, settlement="private"))
    assert bez_prowizji != naleznosc, "test bez sensu, gdy prowizja wynosi zero"

    for nazwa, html in (
        ("obrazek", render_client_shortlist([ITEM], pokaz_naglowek=False)),
        ("raport", render_client_report(ITEM)),
    ):
        assert bez_prowizji not in _kwoty(html), f"{nazwa} nadal pokazuje koszt bez prowizji"


def test_wiadomosc_i_obrazek_mowia_to_samo() -> None:
    draft = build_draft([LOT], client_name="Jan")
    z_wiadomosci = {int(m.replace(" ", "").replace(" ", "")) for m in re.findall(r"([\d  ]{5,})\s*zł", draft.text)}
    z_obrazka = _kwoty(render_client_shortlist([ITEM], pokaz_naglowek=False))
    assert z_wiadomosci & z_obrazka, (
        f"wiadomość mówi {sorted(z_wiadomosci)}, obrazek {sorted(z_obrazka)} — klient dostaje dwie ceny"
    )
