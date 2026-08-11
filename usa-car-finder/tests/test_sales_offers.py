"""Most między wynikami wyszukiwania a agentem sprzedaży."""
import pytest

from parser.models import CarLot
from sales.offers import offer_from_lot, offers_from_lots


def lot(lot_id="A", price=6000.0, state="FL", damage="Front End", model="RAV4"):
    return CarLot(
        source="copart", lot_id=lot_id, url="u", year=2019, make="Toyota", model=model,
        odometer_mi=51_000, current_bid_usd=price, location_state=state, damage_primary=damage,
    )


def test_offer_carries_the_landed_price_not_the_auction_bid():
    """Klient myśli w złotówkach pod klucz — stawka aukcyjna nic mu nie mówi."""
    oferta = offer_from_lot(lot(price=6000.0))

    assert oferta["cena_pln"] > 40_000, "6 tys. USD to ok. 52 tys. zł pod klucz, nie 24 tys."
    assert "Toyota RAV4" in oferta["nazwa"]
    assert oferta["ponad_budzet"] is False


def test_lot_without_a_price_is_not_an_offer():
    """Auto bez otwartej licytacji trafiłoby do wiadomości jako pozycja bez kwoty."""
    bez_ceny = CarLot(source="copart", lot_id="B", url="u", year=2019, make="Toyota", model="RAV4")

    assert offer_from_lot(bez_ceny) is None


def test_over_budget_is_flagged_for_the_agent():
    """Agent musi wiedzieć, że pisze o aucie droższym niż budżet klienta."""
    oferta = offer_from_lot(lot(price=30_000.0), budget_pln=60_000)

    assert oferta["ponad_budzet"] is True


def test_broker_order_is_preserved():
    """Broker zaznaczył auta w tej kolejności — przestawianie ich zmienia propozycję."""
    lots = [lot("A", model="RAV4"), lot("B", model="Camry"), lot("C", model="Corolla")]

    oferty = offers_from_lots(lots)

    assert [o["nazwa"].split()[-1] for o in oferty] == ["RAV4", "Camry", "Corolla"]


def test_offer_list_stops_at_four():
    """Więcej niż cztery pozycje paraliżują wybór — ta sama zasada co w mailu."""
    assert len(offers_from_lots([lot(str(i)) for i in range(9)])) == 4


def test_endpoint_refuses_when_nothing_can_be_priced(monkeypatch):
    """Bez ceny nie ma czego proponować — mówimy to wprost, zamiast wysyłać pustkę."""
    from fastapi.testclient import TestClient
    from api import main as api_main

    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", "")

    from sales import db as sales_db
    from sales.models import Lead

    lead = sales_db.create_lead(Lead(name="Wojciech", raw_request="Szukam Toyoty"))
    bez_ceny = {"source": "copart", "lot_id": "X", "url": "u", "make": "Toyota"}

    with TestClient(api_main.app) as client:
        response = client.post(
            f"/api/sales/leads/{lead.id}/offer", json={"lots": [bez_ceny]}
        )

    assert response.status_code == 422
    assert "ceny pod klucz" in response.json()["detail"]
