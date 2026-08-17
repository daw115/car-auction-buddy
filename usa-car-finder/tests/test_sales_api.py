"""
Endpointy agenta sprzedażowego — przede wszystkim to, kto może co zobaczyć.

UWAGA NA BAZĘ. `api/main.py` woła `load_dotenv(override=True)`, więc wartości z `.env`
BIJĄ zmienne wyeksportowane w powłoce. Ustawienie `APP_DATABASE_PATH` przed
uruchomieniem testów nie działa — testy pisałyby do produkcyjnej bazy aplikacji.
Dlatego podmieniamy ją monkeypatchem PO imporcie aplikacji, a nie przed.
"""
import pytest
from fastapi.testclient import TestClient

TOKEN = "test-token"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAPER_API_TOKEN", TOKEN)
    monkeypatch.setenv("USE_MOCK_DATA", "true")

    from api import main as api_main
    from api import sales_routes

    # Token czytany jest do stałej modułu przy imporcie, więc sama zmienna środowiskowa
    # by nie wystarczyła — aplikacja jest zaimportowana raz na całą sesję pytest.
    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", TOKEN)
    monkeypatch.setenv("APP_DATABASE_PATH", str(tmp_path / "app.db"))
    sales_routes._hits.clear()

    return TestClient(api_main.app)


@pytest.fixture()
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


# Budżet powyżej progu sita (`sales/gate.MIN_BUDGET_PLN`) świadomie: te testy sprawdzają
# przepływ zatwierdzania i wysyłki, a nie filtrowanie. Lead poniżej progu trafiłby na
# parking i połowa asercji tutaj mierzyłaby próg zamiast tego, co ma mierzyć.
# Samo sito ma własną suitę: `tests/test_gate_and_vincheck.py`.
ZGLOSZENIE = {
    "message": "Szukam BMW X5 2022+, budżet 350 tys. pod drzwi. "
               "Wiem, że to auta powypadkowe. Potrzebuję na już.",
    "name": "Marek Kowalski",
    "phone": "605083832",
}


# ─────────────────────────────────────────────────────────────────── dostęp


def test_formularz_dziala_bez_tokena(client):
    """Landing page nie ma jak nosić tokena — ten endpoint musi być otwarty."""
    response = client.post("/api/public/leads", json=ZGLOSZENIE)
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_skrzynka_brokera_wymaga_tokena(client):
    """Rozmowy z klientami nie mogą być publiczne."""
    assert client.get("/api/sales/inbox").status_code == 401
    assert client.get("/api/sales/leads").status_code == 401
    assert client.get("/api/sales/leads/1").status_code == 401


def test_zly_token_nie_wpuszcza(client):
    response = client.get("/api/sales/inbox", headers={"Authorization": "Bearer nie-ten"})
    assert response.status_code == 403


def test_formularz_nie_zdradza_oceny_leada(client):
    """Ocena i powód odrzucenia to nasza kuchnia — z ulicy nie widać, jak kwalifikujemy."""
    body = client.post("/api/public/leads", json=ZGLOSZENIE).json()
    assert set(body) <= {"ok", "lead_id"}


# ─────────────────────────────────────────────────────────────── ochrona wejścia


def test_honeypot_odrzuca_bota_nie_mowiac_o_tym(client, auth):
    """Odpowiedź jak przy sukcesie — inaczej bot wie, które pole pominąć."""
    response = client.post(
        "/api/public/leads",
        json={**ZGLOSZENIE, "phone": "600999888", "website": "http://spam.example"},
    )
    assert response.status_code == 200
    assert client.get("/api/sales/leads", headers=auth).json()["count"] == 0


def test_limit_zapytan_zatrzymuje_zalew(client, monkeypatch):
    from api import sales_routes

    monkeypatch.setattr(sales_routes, "RATE_LIMIT_MAX", 3)
    for _ in range(3):
        assert client.post("/api/public/leads", json=ZGLOSZENIE).status_code == 200
    assert client.post("/api/public/leads", json=ZGLOSZENIE).status_code == 429


def test_puste_zgloszenie_bez_kontaktu_jest_odrzucane(client):
    assert client.post("/api/public/leads", json={"message": ""}).status_code == 400


# ──────────────────────────────────────────────────────────── skrzynka i wysyłka


def test_lead_bez_propozycji_i_tak_jest_widoczny(client, auth, monkeypatch):
    """Model bywa niedostępny. Lead, dla którego nie powstał draft, nie może zniknąć —
    cisza wygląda wtedy jak brak zgłoszeń i nikt się nie zorientuje.

    Symulujemy awarię, wyłączając zadanie w tle: to jest dokładnie ten stan, w którym
    lead ma kartotekę i nie ma propozycji.
    """
    from api import sales_routes

    monkeypatch.setattr(sales_routes, "_generate_draft_later", lambda lead_id: None)

    client.post("/api/public/leads", json=ZGLOSZENIE)
    inbox = client.get("/api/sales/inbox", headers=auth).json()
    assert inbox["count"] == 0
    assert len(inbox["needs_attention"]) == 1
    assert inbox["needs_attention"][0]["score"]["segment"] == "A"


def _pierwszy_draft(client, auth):
    """Zgłoszenie z formularza i propozycja, którą przygotowało zadanie w tle."""
    client.post("/api/public/leads", json=ZGLOSZENIE)
    inbox = client.get("/api/sales/inbox", headers=auth).json()
    assert inbox["count"] == 1, "zadanie w tle miało przygotować propozycję"
    return inbox["items"][0]


def test_pelna_sciezka_od_zgloszenia_do_zgody(client, auth):
    """Zgłoszenie → propozycja → zgoda brokera → link do wysłania."""
    from sales import db

    pozycja = _pierwszy_draft(client, auth)
    assert pozycja["wa_me"].startswith("https://wa.me/48605083832?text=")

    lead_id = pozycja["lead_id"]
    # Do tego momentu w wątku nie ma ani jednej wysłanej wiadomości od nas.
    assert all(m.author.value != "broker" for m in db.messages(lead_id))

    response = client.post(f"/api/sales/drafts/{pozycja['id']}/approve", json={}, headers=auth)
    assert response.status_code == 200
    assert response.json()["sent"] is True
    assert any(m.author.value == "broker" for m in db.messages(lead_id))


def test_druga_zgoda_na_ten_sam_draft_konczy_sie_konfliktem(client, auth):
    """Panel bywa klikany dwa razy — klient nie może dostać dubla."""
    draft_id = _pierwszy_draft(client, auth)["id"]
    assert client.post(f"/api/sales/drafts/{draft_id}/approve", json={}, headers=auth).status_code == 200
    assert client.post(f"/api/sales/drafts/{draft_id}/approve", json={}, headers=auth).status_code == 409


def test_broker_moze_poprawic_tresc_przed_wyslaniem(client, auth):
    draft = _pierwszy_draft(client, auth)

    response = client.post(
        f"/api/sales/drafts/{draft['id']}/approve",
        json={"edited_text": "Moja wersja."},
        headers=auth,
    )
    assert response.json()["text"] == "Moja wersja."
    assert "Moja%20wersja." in response.json()["wa_me"]


def test_ten_sam_numer_nie_zaklada_drugiego_leada(client, auth):
    client.post("/api/public/leads", json=ZGLOSZENIE)
    client.post("/api/public/leads", json={**ZGLOSZENIE, "message": "jeszcze raz pytam"})
    assert client.get("/api/sales/leads", headers=auth).json()["count"] == 1


def test_szczegoly_leada_niosa_ocene_i_rozmowe(client, auth):
    from sales import db

    client.post("/api/public/leads", json=ZGLOSZENIE)
    lead_id = db.list_leads()[0].id

    body = client.get(f"/api/sales/leads/{lead_id}", headers=auth).json()
    assert body["score"]["segment"] == "A"
    assert body["budget_pln"] == 350_000
    assert body["year_from"] == 2022
    assert body["damage_ok"] is True
    assert len(body["messages"]) == 1
    assert body["messages"][0]["author"] == "klient"


def test_nieistniejacy_lead_to_404(client, auth):
    assert client.get("/api/sales/leads/9999", headers=auth).status_code == 404
