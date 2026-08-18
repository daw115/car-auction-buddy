import pytest
from fastapi.testclient import TestClient
from parser.models import CarLot
TOKEN = "test-token"

def L(**kw):
    d = dict(source="copart", lot_id="A1", url="https://x/1", vin="1FTFW1E50NF123456",
             year=2021, make="Toyota", model="RAV4", odometer_mi=30000,
             current_bid_usd=12000.0, damage_primary="Front End", title_type="Salvage")
    d.update(kw)
    return CarLot(**d).model_dump(mode="json")

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAPER_API_TOKEN", TOKEN)
    monkeypatch.setenv("USE_MOCK_DATA", "true")
    from api import main as api_main
    from api import sales_routes
    monkeypatch.setattr(api_main, "SCRAPER_API_TOKEN", TOKEN)
    monkeypatch.setenv("APP_DATABASE_PATH", str(tmp_path / "app.db"))
    sales_routes._hits.clear()
    return TestClient(api_main.app, raise_server_exceptions=False)

@pytest.fixture()
def auth():
    return {"Authorization": f"Bearer {TOKEN}"}

def _setup(client, auth, kandydaci, oferta):
    from sales import db
    from sales.models import Lead
    lid = db.create_lead(Lead(name="X", phone="605083832", raw_request="RAV4")).id
    sid = db.start_lead_search(lid, {"make":"Toyota"})
    db.finish_lead_search(sid, job_id="j",
        candidates=[{"lot": l, "score": 8.0, "recommendation":"kup", "reasoning":"ok", "is_top":False} for l in kandydaci])
    r = client.post(f"/api/sales/leads/{lid}/sprawa/oferta", json={"lots": oferta}, headers=auth)
    assert r.status_code == 200, r.text
    return lid, r.json()

def _stub(monkeypatch, padnie_po=None):
    from report import pdf_export
    from notify import wysylka
    stan = {"n": 0}
    monkeypatch.setattr(pdf_export, "dostepny", lambda: True)
    monkeypatch.setattr(pdf_export, "html_na_pdf", lambda html: b"%PDF")
    monkeypatch.setattr(wysylka, "odbiorcy", lambda: [1])
    def wyslij(*a, **k):
        stan["n"] += 1
        if padnie_po is not None and stan["n"] > padnie_po:
            raise wysylka.NicNieDoszlo("bot padl")
        return 1
    monkeypatch.setattr(wysylka, "wyslij_plik", wyslij)
    return stan

A = L()
B = L(source="manheim", lot_id="VINKIA123", vin="VINKIA123", year=2022, make="Kia", model="Sportage", url="https://m/2")

def test_happy(client, auth, monkeypatch):
    lid, s = _setup(client, auth, [A], [A])
    _stub(monkeypatch)
    r = client.post(f"/api/sales/leads/{lid}/sprawa/raport-szczegolowy", json={"numery":[1]}, headers=auth)
    print("HAPPY:", r.status_code, str(r.content)[:400])
    print("STAN:", client.get(f"/api/sales/leads/{lid}/sprawa", headers=auth).json())

def test_dwa_razy(client, auth, monkeypatch):
    lid, s = _setup(client, auth, [A, B], [A, B])
    _stub(monkeypatch)
    r1 = client.post(f"/api/sales/leads/{lid}/sprawa/raport-szczegolowy", json={"numery":[1]}, headers=auth)
    print("1szy:", r1.status_code, r1.json().get("pliki"))
    r2 = client.post(f"/api/sales/leads/{lid}/sprawa/raport-szczegolowy", json={"numery":[2]}, headers=auth)
    print("2gi:", r2.status_code, r2.json().get("pliki"))
    print("STAN:", client.get(f"/api/sales/leads/{lid}/sprawa", headers=auth).json())

def test_polowa_sie_nie_dopasowala(client, auth, monkeypatch):
    # B jest w ofercie, ale nie ma go w ostatnim wyszukiwaniu (nowe szukanie)
    lid, s = _setup(client, auth, [A], [A, B])
    _stub(monkeypatch)
    r = client.post(f"/api/sales/leads/{lid}/sprawa/raport-szczegolowy", json={"numery":[1,2]}, headers=auth)
    print("POLOWA:", r.status_code, r.json().get("pliki"))
    print("STAN:", client.get(f"/api/sales/leads/{lid}/sprawa", headers=auth).json())

def test_telegram_pada_w_polowie(client, auth, monkeypatch):
    lid, s = _setup(client, auth, [A, B], [A, B])
    _stub(monkeypatch, padnie_po=2)   # pierwsze auto przechodzi, drugie pada
    r = client.post(f"/api/sales/leads/{lid}/sprawa/raport-szczegolowy", json={"numery":[1,2]}, headers=auth)
    print("PAD:", r.status_code, str(r.content)[:200])
    print("STAN:", client.get(f"/api/sales/leads/{lid}/sprawa", headers=auth).json())
