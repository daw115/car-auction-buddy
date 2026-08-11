"""
Sito przed skrzynką i publiczny checker VIN.

Oba wynikają z jednej arytmetyki: przy prowizji 3,6 tys. zł na aucie za $15 000
i koszcie pozyskania rzędu 3-6 tys. zł masowy lead jest stratą, a nie szansą.
Dlatego checker jest otwarty (ma filtrować przez samoselekcję, nie łapać każdego),
a przed skrzynką stoi sito (broker ma widzieć tych, na których zarobi).
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from sales.gate import MIN_BUDGET_PLN, MIN_SCORE, check, worth_model_call
from sales.models import Lead, Stage
from sales.qualification import score_lead

TOKEN = "test-token"


def lead(**over) -> Lead:
    base = dict(
        name="Marek Kowalski",
        phone="48605083832",
        raw_request="szukam auta",
        make="BMW",
        model="X5",
        year_from=2022,
        budget_pln=350_000.0,
        timeline_days=30,
        damage_ok=True,
        max_odometer_mi=60_000,
        last_client_message_at=datetime.now(timezone.utc),
    )
    base.update(over)
    return Lead(**base)


def verdict(l: Lead):
    return check(l, score_lead(l))


# ────────────────────────────────────────────────────────────────── sito


def test_klient_z_gornej_polki_przechodzi():
    assert verdict(lead()).passes


def test_budzet_ponizej_progu_trafia_na_parking():
    """Przy prowizji z małego auta koszt pozyskania zjada całą marżę."""
    w = verdict(lead(budget_pln=MIN_BUDGET_PLN - 50_000))
    assert not w.passes
    assert any("poniżej progu" in r for r in w.reasons)


def test_odrzucenie_zawsze_mowi_co_musi_sie_zmienic():
    """Parking to wstrzymanie, nie skreślenie — lead ma wrócić, gdy warunek zniknie."""
    w = verdict(lead(budget_pln=80_000.0))
    assert w.unlock
    assert not w.passes


def test_polecenie_przechodzi_mimo_niskiego_budzetu():
    """CAC polecenia to zero, więc arytmetyka uzasadniająca sito do niego nie stosuje się.

    Odrzucenie polecenia psuje przy okazji źródło, z którego przyszło.
    """
    assert verdict(lead(budget_pln=80_000.0, referred_by="Adam K.")).passes


def test_klient_powracajacy_przechodzi_mimo_niskiego_budzetu():
    assert verdict(lead(budget_pln=80_000.0, bought_before=True)).passes


def test_brak_kontaktu_to_inny_rodzaj_odrzucenia():
    """Lead bez telefonu nie jest słaby — jest nieobsługiwalny."""
    w = verdict(lead(phone=None, email=None))
    assert not w.passes
    assert any("kontakt" in r for r in w.reasons)


def test_odmowa_auta_po_szkodzie_zatrzymuje_lead():
    w = verdict(lead(damage_ok=False))
    assert not w.passes
    assert any("po szkodzie" in r for r in w.reasons)


def test_niska_ocena_zatrzymuje_mimo_budzetu():
    ubogi = lead(budget_pln=400_000.0, make=None, model=None, year_from=None,
                 timeline_days=None, damage_ok=None, phone=None, email="x@example.com",
                 last_client_message_at=None)
    if score_lead(ubogi).score < MIN_SCORE:
        assert not check(ubogi, score_lead(ubogi)).passes


# ─────────────────────────────────────────── kiedy wolno wołać model


def test_model_nie_pracuje_dla_leada_z_parkingu():
    """Wywołanie kosztuje i trwa; dla parkingu wystarcza wariant regułowy."""
    maly = lead(budget_pln=80_000.0)
    assert not worth_model_call(maly, score_lead(maly))


def test_model_pracuje_przy_odmowie_auta_po_szkodzie():
    """Jedna dobra wiadomość odwraca najczęstszy powód traconych leadów — to się zwraca."""
    l = lead(damage_ok=False)
    assert worth_model_call(l, score_lead(l))


def test_model_milczy_przy_sprawie_zamknietej_i_bez_kontaktu():
    assert not worth_model_call(lead(stage=Stage.STRACONY), score_lead(lead()))
    bez = lead(phone=None, email=None)
    assert not worth_model_call(bez, score_lead(bez))


# ──────────────────────────────────────────────── publiczny checker VIN


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAPER_API_TOKEN", TOKEN)
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    from api import main as api_main
    from api import sales_routes

    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", TOKEN)
    sales_routes._hits.clear()
    return TestClient(api_main.app)


X7 = {"vin": "5UX33EM0XV9489441", "bid_usd": 80_000, "state": "PA",
      "make": "BMW", "model": "X7", "trim": "M60i 4.4L V8"}


def test_checker_dziala_bez_tokena_i_bez_podawania_kontaktu(client):
    """Otwarty świadomie: ma filtrować przez samoselekcję, nie zbierać numery."""
    r = client.post("/api/public/vin-check", json=X7)
    assert r.status_code == 200
    assert "phone" not in r.json()


def test_checker_rozpoznaje_montaz_w_usa_i_liczy_oszczednosc(client):
    d = client.post("/api/public/vin-check", json=X7).json()
    assert d["assembled_in_usa"] is True
    assert d["duty_rate_pct"] == 0.0
    assert d["saving_pln"] > 10_000
    assert d["landed_if_duty_10_pln"] > d["landed_pln"]


def test_checker_nie_daje_zerowego_cla_autu_z_meksyku(client):
    d = client.post(
        "/api/public/vin-check",
        json={"vin": "3VW217AU9JM123456", "bid_usd": 30_000, "make": "AUDI", "model": "Q5"},
    ).json()
    assert d["duty_rate_pct"] == 10.0
    assert d["saving_pln"] == 0


def test_elektryk_z_usa_placi_clo_ale_nie_akcyze(client):
    """Elektryki są wyłączone ze zniesienia ceł — montaż we Fremont nic tu nie zmienia."""
    d = client.post(
        "/api/public/vin-check",
        json={"vin": "5YJ3E1EA7LF123456", "bid_usd": 25_000, "make": "TESLA", "model": "MODEL 3"},
    ).json()
    assert d["assembled_in_usa"] is True
    assert d["duty_rate_pct"] == 10.0
    assert d["excise_rate_pct"] == 0.0


def test_nierozpoznane_auto_przy_zerowym_cle_daje_ostrzezenie(client):
    """Jedyne założenie, które ZANIŻA cenę — musi być powiedziane wprost.

    Bez marki i modelu detektor widzi samą wersję ("Long Range") i bierze Teslę za
    spalinową, co daje 0% zamiast 10% cła.
    """
    d = client.post(
        "/api/public/vin-check",
        json={"vin": "5YJ3E1EA7LF123456", "bid_usd": 25_000, "trim": "Long Range"},
    ).json()
    assert d["duty_rate_pct"] == 0.0
    assert not d["drivetrain_confident"]
    assert any("elektryk" in a.lower() for a in d["assumptions"])


def test_rozpoznane_auto_spalinowe_nie_straszy_elektrykiem(client):
    """Ostrzeżenie widoczne zawsze przestaje być ostrzeżeniem.

    Przy komplecie marki i modelu odpalałoby się na każdym spalinowym aucie i nauczyłoby
    wszystkich je pomijać — łącznie z tym jednym razem, kiedy naprawdę coś znaczy.
    """
    d = client.post("/api/public/vin-check", json=X7).json()
    assert d["duty_rate_pct"] == 0.0
    assert not any("elektryk" in a.lower() for a in d["assumptions"])


def test_checker_dziala_na_samym_vinie_bez_ceny(client):
    """Sprawdzenie cła nie wymaga znajomości stawki — to najczęstszy przypadek użycia."""
    d = client.post("/api/public/vin-check", json={"vin": "1FMSK8DH1NG123456"}).json()
    assert d["duty_rate_pct"] == 0.0
    assert "landed_pln" not in d


def test_zly_vin_tlumaczy_co_jest_nie_tak(client):
    r = client.post("/api/public/vin-check", json={"vin": "NIEPOPRAWNY"})
    assert r.status_code == 422
    assert "VIN" in r.json()["detail"]


def test_checker_ma_wlasny_wyzszy_limit_niz_formularz(client, monkeypatch):
    """Sprawdzenie kilkunastu lotów pod rząd to normalna praca kupującego."""
    from api import sales_routes

    assert sales_routes.VIN_CHECK_RATE_LIMIT > sales_routes.RATE_LIMIT_MAX
    monkeypatch.setattr(sales_routes, "VIN_CHECK_RATE_LIMIT", 2)
    sales_routes._hits.clear()
    assert client.post("/api/public/vin-check", json=X7).status_code == 200
    assert client.post("/api/public/vin-check", json=X7).status_code == 200
    assert client.post("/api/public/vin-check", json=X7).status_code == 429


def test_skrzynka_rozdziela_przechodzacych_i_parking(client):
    from sales import db
    from sales.agent import propose_reply
    from sales.models import Channel

    duzy = db.create_lead(lead(budget_pln=350_000.0))
    maly = db.create_lead(lead(name="Jan", phone="48600100200", budget_pln=80_000.0))
    for l in (duzy, maly):
        d = propose_reply(l, [])
        if d and d.text:
            db.save_draft(d)

    inbox = client.get("/api/sales/inbox", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert any(p["lead_id"] == duzy.id for p in inbox["items"])
    parked_ids = {p["lead_id"] for p in inbox["parked"]}
    assert maly.id in parked_ids
    assert inbox["gate"]["min_budget_pln"] == MIN_BUDGET_PLN


def test_odrzucony_lead_nie_znika_ze_skrzynki(client):
    """Ukrywanie odrzuconych zamieniłoby filtr w cichą utratę klienta."""
    from sales import db

    maly = db.create_lead(lead(name="Jan", phone="48600100200", budget_pln=80_000.0))
    inbox = client.get("/api/sales/inbox", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    wpis = next(p for p in inbox["parked"] if p["lead_id"] == maly.id)
    assert wpis["parked_reasons"]
    assert wpis["unlock"]
