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
    # Dolar w treści jest, ale jako RÓWNOWARTOŚĆ kwoty pod klucz w nawiasie —
    # nigdy jako cena aukcyjna. Ta druga pokazywałaby klientowi marżę.
    assert "6 000 $" not in draft.text and "6000" not in draft.text
    assert "USD" not in draft.text
    # 6 000 USD z Florydy to ~52 tys. zł pod klucz (49 425 sprowadzenie + 2 804 prowizji),
    # nie 24 tys. z przeliczenia kursem.
    # Próg zamiast wpisanej liczby: kurs bierzemy z NBP, więc konkretna kwota zmienia
    # się co dzień. Test na "52" pilnowałby tabeli kursowej, a nie tego, co sprawdza.
    from pricing import fx

    # Dzielenie po myślniku wiązało test z interpunkcją wiadomości: zniknął myślnik
    # (klient nie ma go czytać) i test padał, choć kwota była poprawna.
    import re as _re

    dopasowanie = _re.search(r"([\d\u00a0 ]+)\s*zł", draft.text)
    assert dopasowanie, f"w wiadomości nie ma kwoty w zł: {draft.text!r}"
    kwota = int("".join(ch for ch in dopasowanie.group(1) if ch.isdigit()))
    assert kwota > 6000.0 * fx.current_rate() * 1.8


def test_price_includes_the_commission():
    """Prowizja doliczona po ofercie to dopłata po drodze, której obiecujemy nie robić."""
    from scoring.budget import landed_cost_for_lot

    # Porównanie idzie do wersji PER LOT, nie do `landed_cost_pln`. Odkąd cło zależy od
    # kraju montażu, a akcyza od rodzaju napędu, funkcja licząca z samej ceny i stanu nie
    # zna dość danych, żeby podać tę samą kwotę — i nie wolno jej używać tam, gdzie mamy
    # obiekt auta. Zgodność kanałów bierze się z jednego wejścia, a nie z dwóch przypadkiem
    # zbieżnych.
    auto = lot(price=6000.0)
    z_prowizja = landed_cost_for_lot(auto)
    assert z_prowizja > 6000.0 * 4
    assert f"{z_prowizja:,.0f}".replace(",", " ") in build_draft([auto]).text


def test_registration_is_not_promised_inside_the_price():
    """Kalkulator nie liczy rejestracji, więc nie wolno jej obiecywać w kwocie."""
    assert "rejestracja" not in build_draft([lot()]).text.lower()


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
    # Przebieg podajemy w kilometrach, mile w nawiasie; przecinek po nazwie
    # modelu ma przeżyć podmianę separatora tysięcy.
    assert "RAV4, 82 tys. km (51 tys. mil)" in line


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


def test_endpoint_without_phone_still_returns_the_text(monkeypatch):
    """Brak numeru nie może blokować treści — broker skopiuje ją ręcznie."""
    from fastapi.testclient import TestClient
    from api import main as api_main

    # Inne moduły testowe ustawiają token w środowisku — bez tego endpoint
    # odpowiada 401 i test mierzy autoryzację zamiast treści.
    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", "")
    response = TestClient(api_main.app).post(
        "/api/offers/whatsapp",
        json={"lots": [lot().model_dump()], "client": {"name": "Piotr"}},
    )

    body = response.json()
    assert body["text"] and body["waMeUrl"] is None


def test_endpoint_with_no_affordable_lots_returns_nothing_to_send(monkeypatch):
    from fastapi.testclient import TestClient
    from api import main as api_main

    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", "")
    response = TestClient(api_main.app).post("/api/offers/whatsapp", json={"lots": []})
    assert response.json() == {"text": None, "offers": 0, "waMeUrl": None}


def test_over_budget_lot_does_not_reach_the_client_by_default():
    """Auto droższe niż budżet nie ma prawa trafić do wiadomości samo z siebie."""
    tanie = lot(model="RAV4", price=6_000.0)
    drogie = lot(model="Highlander", price=30_000.0)

    draft = build_draft([tanie, drogie], client_name="Wojciech", budget_pln=60_000)

    assert draft.offers == 1
    assert "RAV4" in draft.text
    assert "Highlander" not in draft.text


def test_broker_can_add_an_over_budget_lot_and_it_is_named_as_such():
    """Gdy broker świadomie dobierze droższe auto, klient widzi to wprost."""
    draft = build_draft(
        [lot(model="Highlander", price=30_000.0)],
        client_name="Wojciech",
        budget_pln=60_000,
        allow_over_budget=True,
    )

    assert draft.offers == 1
    assert "powyżej budżetu" in draft.text
    # Nagłówek nie może twierdzić, że oferta mieści się w kwocie, której nie mieści.
    assert "pod Pana budżet" not in draft.text


def test_budget_claim_survives_when_everything_fits():
    draft = build_draft([lot(price=6_000.0)], client_name="Wojciech", budget_pln=60_000)
    assert "pod Pana budżet 60 tys. zł" in draft.text
    assert "powyżej budżetu" not in draft.text


def test_only_over_budget_lots_means_nothing_to_send():
    """Bez zgody brokera i bez ofert w budżecie nie ma wiadomości — nie ma czego wysłać."""
    assert build_draft([lot(price=30_000.0)], budget_pln=60_000) is None


def test_endpoint_passes_the_brokers_over_budget_decision(monkeypatch):
    from fastapi.testclient import TestClient
    from api import main as api_main

    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", "")
    payload = {
        "lots": [lot(model="Highlander", price=30_000.0).model_dump(mode="json")],
        "client": {"name": "Wojciech", "phone": "605083832"},
        "budgetPln": 60_000,
    }

    with TestClient(api_main.app) as client:
        bez_zgody = client.post("/api/offers/whatsapp", json=payload).json()
        z_zgoda = client.post(
            "/api/offers/whatsapp", json={**payload, "allowOverBudget": True}
        ).json()

    assert bez_zgody["text"] is None and bez_zgody["offers"] == 0
    assert z_zgoda["offers"] == 1
    assert "powyżej budżetu" in z_zgoda["text"]


def test_auction_trim_noise_does_not_eat_the_line():
    """Aukcje podają całą nazwę wersji wersalikami — klient nie mówi tak o aucie."""
    surowy = CarLot(
        source="iaai", lot_id="X", url="u", year=2023, make="AUDI",
        model="AUDI Q7 PREMIUM PLUS 45 TFSI QUATTRO TIPTRONIC",
        odometer_mi=45_000, current_bid_usd=19_975, location_state="NC",
    )

    linia = build_draft([surowy]).text

    assert "2023 Audi Q7 Premium Plus" in linia
    assert "TIPTRONIC" not in linia and "QUATTRO" not in linia


# ─────────────────────────────────────────── wywiad z klienta: nagranie -> kryteria


def test_voice_intake_refuses_when_there_is_no_transcription_engine(monkeypatch):
    """Bez silnika mówimy to wprost, zamiast udawać pustą transkrypcję."""
    import io

    from fastapi.testclient import TestClient
    from api import main as api_main
    from ai import transcribe as transcriber

    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", "")
    monkeypatch.setattr(transcriber, "is_available", lambda: False)

    with TestClient(api_main.app) as client:
        response = client.post(
            "/api/intake/voice", files={"file": ("nagranie.ogg", io.BytesIO(b"x"), "audio/ogg")}
        )

    assert response.status_code == 503
    assert "faster-whisper" in response.json()["detail"]


def test_voice_intake_returns_criteria_and_never_starts_a_scrape(monkeypatch):
    """Transkrypt bywa niedosłowny — broker ma go zobaczyć PRZED wyszukiwaniem.

    Wyszukiwanie trwa kilkanaście minut i kosztuje; uruchamianie go z automatu
    na podstawie tego, co system usłyszał, oznaczałoby palenie czasu na pomyłki.
    """
    import io

    from fastapi.testclient import TestClient
    from api import main as api_main
    from ai import transcribe as transcriber

    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", "")
    monkeypatch.setattr(transcriber, "is_available", lambda: True)
    monkeypatch.setattr(
        transcriber,
        "transcribe",
        lambda path, language=None: transcriber.Transcript(
            text="Szukam Audi Q7 z 2019 roku, budżet 200 tysięcy pod klucz.",
            language="pl", duration_s=12.0, model="small",
        ),
    )
    monkeypatch.setattr(
        "ai.message_parser.parse_client_message",
        lambda text: {
            "cars": [{"make": "Audi", "model": "Q7", "year_from": 2019}],
            "budget_pln_to": 200_000,
            "_summary": "Klient szuka Audi Q7",
        },
    )

    with TestClient(api_main.app) as client:
        response = client.post(
            "/api/intake/voice", files={"file": ("nagranie.ogg", io.BytesIO(b"x"), "audio/ogg")}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["criteria"]["make"] == "Audi"
    assert "Q7" in payload["transcript"]["text"]
    # Kontrakt: żadnego job_id — wyszukiwanie zleca człowiek.
    assert "job_id" not in payload and "jobId" not in payload


def test_whatsapp_intake_says_plainly_when_no_chat_is_open(monkeypatch):
    """Czytamy to, co broker otworzył — nie szukamy rozmów sami."""
    from fastapi.testclient import TestClient
    from api import main as api_main
    from scraper import whatsapp_reader

    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", "")

    async def brak():
        raise whatsapp_reader.WhatsappUnavailable("Żadna rozmowa nie jest otwarta")

    monkeypatch.setattr(whatsapp_reader, "read_open_conversation", brak)

    with TestClient(api_main.app) as client:
        response = client.post("/api/intake/whatsapp")

    assert response.status_code == 409
    assert "rozmowa" in response.json()["detail"].lower()


def test_conversation_is_rendered_for_the_requirements_parser():
    """Parser wymagań dostaje rozmowę z zaznaczonym, kto co powiedział."""
    from scraper.whatsapp_reader import Conversation

    rozmowa = Conversation(
        chat="+48 535 113 530",
        messages=[
            {"kierunek": "klient", "tekst": "Szukam Audi Q7"},
            {"kierunek": "broker", "tekst": "Jaki budżet?"},
            {"kierunek": "klient", "tekst": "Do 200 tysięcy pod klucz"},
        ],
        total=3,
    )

    tekst = rozmowa.as_text()

    assert tekst.startswith("klient: Szukam Audi Q7")
    assert "broker: Jaki budżet?" in tekst
