"""Wiadomość WhatsApp dla klienta — generowana, wysyłana ręcznie przez brokera."""
from urllib.parse import unquote

import pytest

from parser.models import CarLot
from report.whatsapp import MAX_OFFERS, build_draft


def lot(model="RAV4", price=6000.0, state="FL", odo=51_000, year=2019) -> CarLot:
    return CarLot(
        source="manheim", lot_id=model, url="u", year=year, make="Toyota", model=model,
        odometer_mi=odo, current_bid_usd=price, location_state=state,
    )


def test_prices_are_landed_pln_not_auction_usd():
    """Klient myśli w złotówkach pod klucz — cena aukcyjna w USD nic mu nie mówi."""
    draft = build_draft([lot(price=6000.0)], client_name="Wojciech Beyger")

    assert "zł" in draft.text
    assert "USD" not in draft.text and "$" not in draft.text
    # 6 000 USD z Florydy to ~49 tys. zł pod klucz, nie 24 tys. z przeliczenia kursem.
    assert "49" in draft.text or "48" in draft.text


def test_no_internal_score_leaks_to_the_client():
    draft = build_draft([lot()], client_name="Wojciech")
    lowered = draft.text.lower()
    assert "score" not in lowered and "/10" not in lowered and "ai" not in lowered.split()


def test_caps_at_four_offers():
    """Więcej pozycji paraliżuje wybór."""
    draft = build_draft([lot(model=f"M{i}", price=5000 + i * 100) for i in range(9)])
    assert draft.offers == MAX_OFFERS
    assert draft.text.count("•") == MAX_OFFERS


def test_returns_nothing_when_there_is_nothing_to_offer():
    """Pusta wiadomość jest gorsza niż jej brak."""
    assert build_draft([]) is None
    assert build_draft([CarLot(source="manheim", lot_id="1", url="u")]) is None


def test_greeting_uses_the_first_name_only():
    assert build_draft([lot()], client_name="Wojciech Beyger").text.startswith(
        "Dzień dobry, Wojciech"
    )
    # Bez nazwiska wiadomość nadal brzmi naturalnie, tylko bez imienia.
    bez_imienia = build_draft([lot()]).text
    assert bez_imienia.startswith("Dzień dobry, mam")
    assert "Wojciech" not in bez_imienia


def test_model_name_keeps_its_comma_before_mileage():
    """Regresja: zamiana przecinków w całej linii zjadała ten po nazwie modelu."""
    line = build_draft([lot(odo=51_000)]).text
    assert "RAV4, 51 tys. mil" in line


def test_budget_is_mentioned_when_known():
    draft = build_draft([lot()], client_name="Piotr", budget_pln=60_000)
    assert "60 tys. zł" in draft.text


def test_message_ends_with_a_question():
    """Celem wiadomości jest rozmowa, nie zamknięcie sprzedaży."""
    assert build_draft([lot()]).text.rstrip().endswith("?")


def test_wa_me_link_carries_the_text_and_normalises_the_number():
    """Numer z arkusza jest krajowy, bez kierunkowego."""
    draft = build_draft([lot()], client_name="Marek")
    url = draft.wa_me_url("605083832")

    assert url.startswith("https://wa.me/48605083832?text=")
    assert "Dzień dobry, Marek" in unquote(url)


def test_company_settlement_gives_higher_landed_price():
    """Firma płaci VAT od całości — ta sama aukcja kosztuje więcej pod klucz."""
    prywatnie = build_draft([lot(price=6000.0)], settlement="private")
    firma = build_draft([lot(price=6000.0)], settlement="company")
    assert prywatnie.text != firma.text


def test_offer_notes_carry_the_real_message_not_a_placeholder():
    """Oferta niesie treść gotową do wysłania, nie zaślepkę z wewnętrzną oceną."""
    from report.html_reports import _whatsapp_line

    text = _whatsapp_line(lot(price=6000.0))

    assert "zł" in text
    assert "/10" not in text and "score" not in text.lower()
    assert text.rstrip().endswith("?")


def test_offer_notes_fall_back_when_price_is_unknown():
    """Lot bez ceny nie może wywalić generowania oferty."""
    from report.html_reports import _whatsapp_line

    bez_ceny = CarLot(source="manheim", lot_id="1", url="u", year=2019, make="Toyota", model="RAV4")
    text = _whatsapp_line(bez_ceny)

    assert "Toyota RAV4" in text
    assert text.rstrip().endswith("?")


def test_endpoint_returns_text_and_link_but_sends_nothing(monkeypatch):
    """Backend oddaje treść brokerowi — wysyłka zostaje decyzją człowieka."""
    from fastapi.testclient import TestClient
    from api import main as api_main

    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", "")
    payload = {
        "lots": [lot(price=6000.0).model_dump()],
        "client": {"name": "Wojciech Beyger", "phone": "605083832"},
        "budgetPln": 60_000,
        "settlement": "private",
    }

    response = TestClient(api_main.app).post("/api/offers/whatsapp", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["offers"] == 1
    assert "zł" in body["text"] and "/10" not in body["text"]
    assert body["waMeUrl"].startswith("https://wa.me/48605083832?text=")


def test_endpoint_without_phone_still_returns_the_text():
    """Brak numeru nie może blokować treści — broker skopiuje ją ręcznie."""
    from fastapi.testclient import TestClient
    from api import main as api_main

    response = TestClient(api_main.app).post(
        "/api/offers/whatsapp",
        json={"lots": [lot().model_dump()], "client": {"name": "Piotr"}},
    )

    body = response.json()
    assert body["text"] and body["waMeUrl"] is None


def test_endpoint_with_no_affordable_lots_returns_nothing_to_send():
    from fastapi.testclient import TestClient
    from api import main as api_main

    response = TestClient(api_main.app).post("/api/offers/whatsapp", json={"lots": []})
    assert response.json() == {"text": None, "offers": 0, "waMeUrl": None}
