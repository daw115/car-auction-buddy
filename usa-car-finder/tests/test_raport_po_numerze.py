"""Numer od klienta → raport szczegółowy, całą drogą przez endpoint.

Ta ścieżka miała dwa błędy, których nie widać w testach renderowania: loty
przychodzą tu w kształcie kandydata z wyszukiwania (`{lot, score, ...}`),
a nie jako `AnalyzedLot`, i identyfikuje się je kluczem, bo Manheim nie podaje
`lot_id`. Oba wychodzą dopiero wtedy, gdy przejdzie się tędy naprawdę.
"""

import asyncio

import pytest

from sales import db, pipeline

LOT_Z_MANHEIMU = {
    "source": "manheim",
    # Manheim wstawia tu nazwę kanału aukcji, tę samą dla każdego auta — to jest sedno.
    "lot_id": "OVE",
    "vin": "YV4A22RK1M1700001",
    "url": "https://example.test/1",
    "year": 2021,
    "make": "Volvo",
    "model": "XC60",
}
LOT_Z_COPARTU = {
    "source": "copart",
    "lot_id": "778899",
    "url": "https://example.test/2",
    "year": 2022,
    "make": "Toyota",
    "model": "RAV4",
}


@pytest.fixture(autouse=True)
def baza(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_PATH", str(tmp_path / "app.db"))
    db.init_db()
    pipeline.init()


@pytest.fixture
def sprawa_z_oferta(monkeypatch):
    """Lead po kroku 1: poszła oferta z dwoma autami, wyniki wyszukiwania są w bazie."""
    lead = db.create_lead(db.Lead(name="Jan", phone="601234567", raw_request="XC60"))
    pipeline.zapisz_oferte(lead.id, [LOT_Z_MANHEIMU, LOT_Z_COPARTU])

    kandydaci = [
        {"lot": LOT_Z_MANHEIMU, "score": 8.2, "recommendation": "POLECAM", "is_top": True},
        {"lot": LOT_Z_COPARTU, "score": 6.4, "recommendation": "RYZYKO", "is_top": False},
    ]
    from api import sales_routes

    monkeypatch.setattr(db, "latest_lead_search", lambda _id: {"candidates": kandydaci})
    monkeypatch.setattr(sales_routes.db, "latest_lead_search", lambda _id: {"candidates": kandydaci})
    return lead.id


def test_numer_jeden_wskazuje_auto_bez_lot_id(sprawa_z_oferta):
    """Klient odpisuje „1", a pierwsze auto jest z Manheimu — czyli bez numeru lota."""
    from api.sales_routes import WyborZOdpowiedziIn, sprawa_wybor_z_odpowiedzi

    wynik = asyncio.run(sprawa_wybor_z_odpowiedzi(sprawa_z_oferta, WyborZOdpowiedziIn(tekst="1")))

    assert wynik["numery"] == [1]
    assert wynik["klucze"] == [LOT_Z_MANHEIMU["vin"]]
    assert wynik["auta"][0]["nazwa"] == "2021 Volvo XC60"


def test_raport_po_numerze_zapisuje_wybor_i_wysyla_oba_pliki(sprawa_z_oferta, monkeypatch):
    from api.sales_routes import RaportSzczegolowyIn, sprawa_raport_szczegolowy

    wyslane: list[str] = []

    from notify import wysylka
    from report import pdf_export

    monkeypatch.setattr(pdf_export, "dostepny", lambda: True)
    monkeypatch.setattr(pdf_export, "html_na_pdf", lambda html: b"%PDF-udawany")
    monkeypatch.setattr(wysylka, "odbiorcy", lambda: [111])
    monkeypatch.setattr(
        wysylka,
        "wyslij_plik",
        lambda dane, nazwa, podpis, **kw: wyslane.append(nazwa) or 1,
    )

    wynik = asyncio.run(sprawa_raport_szczegolowy(sprawa_z_oferta, RaportSzczegolowyIn(numery=[1])))

    # Raport klienta i brokera idą razem — rozdzielone znaczyłyby, że któryś
    # czasem nie zostanie kliknięty.
    assert len(wynik["pliki"]) == 2
    assert len(wyslane) == 2

    stan = wynik["sprawa"]
    assert stan["krok"] == 4, "po wysłaniu raportu sprawa czeka już na decyzję"
    assert stan["wybrane"][0]["nazwa"] == "2021 Volvo XC60"
    assert stan["wybrane"][0]["nazwa"] != "spoza oferty"


def test_numer_spoza_oferty_konczy_sie_czytelnym_bledem(sprawa_z_oferta):
    from fastapi import HTTPException

    from api.sales_routes import RaportSzczegolowyIn, sprawa_raport_szczegolowy

    with pytest.raises(HTTPException) as blad:
        asyncio.run(sprawa_raport_szczegolowy(sprawa_z_oferta, RaportSzczegolowyIn(numery=[7])))
    assert blad.value.status_code == 400
    assert "7" in str(blad.value.detail)
