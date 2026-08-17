"""Cztery kroki sprawy — stan, który przeżywa restart i nie gubi kontekstu."""
import pytest

from sales import db, pipeline


@pytest.fixture(autouse=True)
def baza(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_PATH", str(tmp_path / "app.db"))
    db.init_db()
    pipeline.init()


def _lead() -> int:
    return db.create_lead(db.Lead(name="Jan", phone="601234567", raw_request="RAV4")).id


def test_nowa_sprawa_zaczyna_sie_na_kroku_pierwszym():
    # Każda sprawa jest na jakimś etapie, także zanim ktoś ją tknie.
    assert pipeline.stan(_lead()).krok == 1


def test_oferta_zapisuje_co_poszlo_i_przesuwa_na_wybor():
    lid = _lead()
    loty = [
        {"lot_id": "A1", "source": "copart", "year": 2024, "make": "Toyota", "model": "RAV4"},
        {"lot_id": "B2", "source": "iaai", "year": 2023, "make": "Toyota", "model": "RAV4"},
    ]
    s = pipeline.zapisz_oferte(lid, loty)
    assert s.krok == 2
    assert [w["lot_id"] for w in s.wyslane] == ["A1", "B2"]
    assert s.wyslane[0]["nazwa"] == "2024 Toyota RAV4"


def test_wybor_bierze_opis_z_wyslanych():
    lid = _lead()
    pipeline.zapisz_oferte(lid, [{"lot_id": "A1", "year": 2024, "make": "Toyota", "model": "RAV4"}])
    s = pipeline.zapisz_wybor(lid, ["A1"])
    assert s.krok == 3
    assert s.wybrane[0]["nazwa"] == "2024 Toyota RAV4"


def test_wybor_spoza_oferty_zostawia_slad():
    # Klient bywa, że wskaże auto znalezione sam. Zgubienie tego znaczyłoby,
    # że broker nie wie, o czym rozmawia.
    lid = _lead()
    pipeline.zapisz_oferte(lid, [{"lot_id": "A1", "make": "Toyota"}])
    s = pipeline.zapisz_wybor(lid, ["ZZZ"])
    assert s.wybrane[0]["lot_id"] == "ZZZ"
    assert s.wybrane[0]["nazwa"] == "spoza oferty"


def test_raporty_nie_dubluja_sie():
    lid = _lead()
    pipeline.zapisz_raport(lid, "rav4-raport.pdf")
    s = pipeline.zapisz_raport(lid, "rav4-raport.pdf")
    assert s.raporty == ["rav4-raport.pdf"]
    assert s.krok == 4


def test_decyzja_przyjmuje_tylko_dwie_wartosci():
    lid = _lead()
    assert pipeline.zapisz_decyzje(lid, "kupuje").decyzja == "kupuje"
    with pytest.raises(ValueError):
        pipeline.zapisz_decyzje(lid, "zastanawia sie")


def test_krok_nie_cofa_sie_przy_powtorzonej_ofercie():
    # Broker bywa, że wyśle drugą ofertę po odrzuceniu pierwszej. Sprawa nie może
    # wtedy wrócić do etapu, z którego już wyszła.
    lid = _lead()
    pipeline.zapisz_raport(lid, "x.pdf")
    s = pipeline.zapisz_oferte(lid, [{"lot_id": "C3"}])
    assert s.krok == 4
