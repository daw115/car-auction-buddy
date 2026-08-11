"""
Most między leadem a pipeline'em aukcyjnym — ostatnie brakujące ogniwo agenta.

Agent zbierał leada, oceniał go i pisał wiadomości, ale nigdy nie uruchamiał
wyszukiwania: marka, model, rocznik i budżet leżały w bazie, a broker i tak
przepisywał je ręcznie do formularza. Etap SZUKANIE istniał w modelu i nic go
nie wypełniało.

Te testy pilnują trzech rzeczy:
  1. że kryteria powstają z leada bez gubienia budżetu pod klucz,
  2. że wyszukiwanie zostawia ślad także wtedy, gdy padnie — inaczej lead wisi
     w stanie "trwa" i nikt się nie dowie,
  3. że nie da się puścić dwóch scrape'ów dla tego samego leada.
"""
import pytest
from fastapi.testclient import TestClient

from sales import db
from sales.models import Lead, Stage
from sales.search import MAX_CANDIDATES, criteria_from_lead, readiness

TOKEN = "test-token"


def lead(**over) -> Lead:
    base = dict(
        name="Marek Kowalski",
        phone="48605083832",
        make="BMW",
        model="X5",
        year_from=2022,
        budget_pln=350_000.0,
        max_odometer_mi=60_000,
        damage_ok=True,
        timeline_days=30,
    )
    base.update(over)
    return Lead(**base)


# ─────────────────────────────────────────────────────── lead → kryteria


def test_kryteria_powstaja_z_danych_leada():
    c = criteria_from_lead(lead())
    assert c.make == "BMW"
    assert c.model == "X5"
    assert c.year_from == 2022
    assert c.max_odometer_mi == 60_000


def test_budzet_idzie_jako_kwota_pod_klucz_a_nie_jako_dolary():
    """Sufit ceny aukcyjnej liczy `scoring/budget.py` osobno dla każdego stanu USA.

    Przeliczenie budżetu na dolary tutaj oznaczałoby zgadywanie kursu i kosztów
    transportu w miejscu, które ich nie zna — i dwie różne kwoty za to samo auto.
    """
    c = criteria_from_lead(lead(budget_pln=350_000.0))
    assert c.budget_pln_to == 350_000.0
    assert c.budget_usd is None


def test_forma_rozliczenia_przechodzi_do_kryteriow():
    """Firma wobec osoby prywatnej przesuwa sufit o ponad tysiąc dolarów."""
    assert criteria_from_lead(lead(settlement="company")).settlement == "company"


def test_bez_marki_nie_ma_czego_szukac():
    assert criteria_from_lead(lead(make=None)) is None
    assert not readiness(lead(make=None)).ready


def test_brak_budzetu_nie_blokuje_ale_jest_zgloszony():
    """Bez budżetu scoring nie odróżni auta w zasięgu klienta od dwa razy za drogiego."""
    gotowosc = readiness(lead(budget_pln=None))
    assert gotowosc.ready
    assert "budżet pod klucz" in gotowosc.missing


def test_liczba_kandydatow_jest_ograniczona():
    """Więcej niż tuzin kart nikt nie ogląda."""
    assert criteria_from_lead(lead()).max_results == MAX_CANDIDATES


# ────────────────────────────────────────────────── ślad po wyszukiwaniu


def test_wyszukiwanie_zostawia_slad_zanim_ruszy(tmp_path):
    """Wiersz powstaje ZANIM scrape wystartuje — inaczej broker patrzy na pustkę
    przez kilka minut i uruchamia wyszukiwanie drugi raz."""
    zapisany = db.create_lead(lead())
    db.start_lead_search(zapisany.id, {"make": "BMW"})

    biezace = db.latest_lead_search(zapisany.id)
    assert biezace["status"] == "running"
    assert db.running_search(zapisany.id)


def test_zakonczone_wyszukiwanie_niesie_kandydatow():
    zapisany = db.create_lead(lead())
    sid = db.start_lead_search(zapisany.id, {"make": "BMW"})
    db.finish_lead_search(sid, job_id="job-1", candidates=[{"lot": {"lot_id": "A"}, "score": 8.1}])

    wynik = db.latest_lead_search(zapisany.id)
    assert wynik["status"] == "done"
    assert wynik["job_id"] == "job-1"
    assert len(wynik["candidates"]) == 1
    assert not db.running_search(zapisany.id)


def test_bledne_wyszukiwanie_nie_zostawia_leada_w_stanie_trwa():
    """Scrape leci w tle, więc wyjątek nie ma komu wypłynąć.

    Bez zapisu błędu lead zostawałby na zawsze jako trwające zadanie.
    """
    zapisany = db.create_lead(lead())
    sid = db.start_lead_search(zapisany.id, {})
    db.fail_lead_search(sid, "scraper padł na CAPTCHA")

    wynik = db.latest_lead_search(zapisany.id)
    assert wynik["status"] == "error"
    assert "CAPTCHA" in wynik["error"]
    assert not db.running_search(zapisany.id)


def test_historia_wyszukiwan_zostaje():
    """Dla jednego klienta puszcza się scrape wielokrotnie — po korekcie budżetu,
    po przegranej licytacji. Nadpisywanie kasowałoby ślad tego, co już pokazaliśmy."""
    zapisany = db.create_lead(lead())
    for _ in range(3):
        sid = db.start_lead_search(zapisany.id, {})
        db.finish_lead_search(sid, job_id=None, candidates=[])
    assert len(db.lead_searches(zapisany.id)) == 3


# ──────────────────────────────────────────────────────────── endpointy


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAPER_API_TOKEN", TOKEN)
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    from api import main as api_main
    from api import sales_routes

    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", TOKEN)
    # Scrape trwa minuty i chodzi po sieci — testujemy bramki wokół niego,
    # nie sam scraper. Ten ma własne testy.
    monkeypatch.setattr(sales_routes, "_run_lead_search", lambda lead_id: None)
    sales_routes._hits.clear()
    return TestClient(api_main.app)


@pytest.fixture()
def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_wyszukiwanie_wymaga_tokena(client):
    assert client.post("/api/sales/leads/1/search").status_code == 401
    assert client.get("/api/sales/leads/1/candidates").status_code == 401


def test_start_wyszukiwania_wraca_od_razu(client, auth):
    """Endpoint nie może czekać na scrape — ten trwa minuty."""
    zapisany = db.create_lead(lead())
    r = client.post(f"/api/sales/leads/{zapisany.id}/search", headers=auth)
    assert r.status_code == 200
    assert r.json()["started"] is True


def test_lead_bez_marki_dostaje_czytelna_odmowe(client, auth):
    zapisany = db.create_lead(lead(make=None, model=None))
    r = client.post(f"/api/sales/leads/{zapisany.id}/search", headers=auth)
    assert r.status_code == 422
    assert "marka" in r.json()["detail"]


def test_brak_budzetu_przechodzi_ale_z_ostrzezeniem(client, auth):
    zapisany = db.create_lead(lead(budget_pln=None))
    r = client.post(f"/api/sales/leads/{zapisany.id}/search", headers=auth)
    assert r.status_code == 200
    assert "budżet pod klucz" in r.json()["warnings"]


def test_drugi_scrape_dla_tego_samego_leada_jest_odrzucany(client, auth):
    """Zajmowałby kolejkę i dał ten sam wynik."""
    zapisany = db.create_lead(lead())
    db.start_lead_search(zapisany.id, {})
    r = client.post(f"/api/sales/leads/{zapisany.id}/search", headers=auth)
    assert r.status_code == 409


def test_kandydaci_rozrozniaja_brak_wynikow_od_trwajacego_szukania(client, auth):
    """To są dwie różne sytuacje i panel nie ma ich zgadywać z pustej listy."""
    zapisany = db.create_lead(lead())

    pusto = client.get(f"/api/sales/leads/{zapisany.id}/candidates", headers=auth).json()
    assert pusto["status"] == "brak"
    assert pusto["offer_ready"] is False

    sid = db.start_lead_search(zapisany.id, {})
    trwa = client.get(f"/api/sales/leads/{zapisany.id}/candidates", headers=auth).json()
    assert trwa["status"] == "running"
    assert trwa["offer_ready"] is False

    db.finish_lead_search(sid, job_id="j", candidates=[{"lot": {"lot_id": "A"}}])
    gotowe = client.get(f"/api/sales/leads/{zapisany.id}/candidates", headers=auth).json()
    assert gotowe["status"] == "done"
    assert gotowe["offer_ready"] is True


def test_wyszukiwanie_bez_wynikow_nie_jest_gotowe_do_oferty(client, auth):
    zapisany = db.create_lead(lead())
    sid = db.start_lead_search(zapisany.id, {})
    db.finish_lead_search(sid, job_id="j", candidates=[])
    body = client.get(f"/api/sales/leads/{zapisany.id}/candidates", headers=auth).json()
    assert body["status"] == "done"
    assert body["offer_ready"] is False


def test_nieistniejacy_lead_to_404(client, auth):
    assert client.post("/api/sales/leads/9999/search", headers=auth).status_code == 404
    assert client.get("/api/sales/leads/9999/candidates", headers=auth).status_code == 404
