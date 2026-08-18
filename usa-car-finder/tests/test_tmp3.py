import pytest
from fastapi.testclient import TestClient
TOKEN = "test-token"

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

def _setup(client, auth, monkeypatch, kandydaci, oferta):
    from sales import db
    from sales.models import Lead
    lid = db.create_lead(Lead(name="X", phone="605083832", raw_request="RAV4")).id
    sid = db.start_lead_search(lid, {"make":"Toyota"})
    db.finish_lead_search(sid, job_id="j", candidates=[{"lot": l, "score": 8.0} for l in kandydaci])
    r = client.post(f"/api/sales/leads/{lid}/sprawa/oferta", json={"lots": oferta}, headers=auth)
    assert r.status_code == 200, r.text
    return lid, r.json()

def _stub(monkeypatch, wyslij_padnie=False):
    from report import pdf_export
    from notify import wysylka
    monkeypatch.setattr(pdf_export, "dostepny", lambda: True)
    monkeypatch.setattr(pdf_export, "html_na_pdf", lambda html: b"%PDF")
    monkeypatch.setattr(wysylka, "odbiorcy", lambda: [1])
    if wyslij_padnie:
        def boom(*a, **k):
            raise wysylka.NicNieDoszlo("bot padl")
        monkeypatch.setattr(wysylka, "wyslij_plik", boom)
    else:
        monkeypatch.setattr(wysylka, "wyslij_plik", lambda *a, **k: 1)

A = {"source":"copart","lot_id":"A1","vin":"V1","year":2021,"make":"Toyota","model":"RAV4"}
B = {"source":"manheim","year":2022,"make":"Kia","model":"Sportage"}
C = {"source":"manheim","year":2020,"make":"Ford","model":"Escape"}

def test_szczesliwa_sciezka(client, auth, monkeypatch):
    lid, s = _setup(client, auth, monkeypatch, [A], [A])
    _stub(monkeypatch)
    r = client.post(f"/api/sales/leads/{lid}/sprawa/raport-szczegolowy", json={"numery":[1]}, headers=auth)
    print("HAPPY:", r.status_code, str(r.content)[:300])

def test_zly_samochod(client, auth, monkeypatch):
    # C jest kandydatem #1 (bez lot_id), B kandydatem #3 (bez lot_id).
    lid, s = _setup(client, auth, monkeypatch, [C, A, B], [B])
    print("klucz w ofercie:", s["wyslane"][0]["klucz"], "=", s["wyslane"][0]["nazwa"])
    _stub(monkeypatch)
    r = client.post(f"/api/sales/leads/{lid}/sprawa/raport-szczegolowy", json={"numery":[1]}, headers=auth)
    print("ZLY:", r.status_code, str(r.content)[:300])

def test_czesciowe_dopasowanie(client, auth, monkeypatch):
    lid, s = _setup(client, auth, monkeypatch, [A, B], [A, B])
    print("klucze:", [w["klucz"] for w in s["wyslane"]])
    _stub(monkeypatch)
    r = client.post(f"/api/sales/leads/{lid}/sprawa/raport-szczegolowy", json={"numery":[1,2]}, headers=auth)
    print("CZESC:", r.status_code, str(r.content)[:400])

def test_padnieta_wysylka(client, auth, monkeypatch):
    lid, s = _setup(client, auth, monkeypatch, [A], [A])
    _stub(monkeypatch, wyslij_padnie=True)
    r = client.post(f"/api/sales/leads/{lid}/sprawa/raport-szczegolowy", json={"numery":[1]}, headers=auth)
    print("PAD:", r.status_code, str(r.content)[:200])
    print("STAN:", client.get(f"/api/sales/leads/{lid}/sprawa", headers=auth).json())
