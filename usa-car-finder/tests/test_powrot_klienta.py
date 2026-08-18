"""Klient, który wraca, musi być widoczny dla brokera.

Lead zamknięty (`stracony`, `wygrana`) jest odfiltrowany ze skrzynki i z listy
leadów — `db.list_leads` woła się wszędzie z `only_open=True` — a agent dla tych
etapów świadomie nie pisze propozycji. Powtórne zgłoszenie z formularza doklejało
się więc do takiego leada i znikało: treść siedziała w bazie, broker nie widział
jej nigdzie, a formularz odpowiadał klientowi „ok".

Najboleśniejszy przypadek to `wygrana`: klient, który już raz kupił, wraca po
drugie auto — czyli najlepszy lead, jaki może przyjść.
"""

import pytest

from sales import db, intake
from sales.models import Stage


@pytest.fixture(autouse=True)
def baza(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SALES_AGENT_MODEL_ENABLED", "false")
    monkeypatch.setenv("SALES_PARSER_ENABLED", "false")
    db.init_db()


def _zgloszenie(tresc: str):
    return intake.submit(raw_request=tresc, phone="600100200", make_draft=False)


@pytest.mark.parametrize("zamkniety", [Stage.STRACONY, Stage.WYGRANA])
def test_powrot_wznawia_sprawe(zamkniety: Stage) -> None:
    wynik = _zgloszenie("Szukam BMW X5 do 200 tysięcy")
    lead_id = wynik.lead.id

    lead = db.get_lead(lead_id)
    lead.stage = zamkniety
    db.update_lead(lead)
    assert db.list_leads(only_open=True) == [], "warunek wstępny: lead jest niewidoczny"

    _zgloszenie("Wracam, mam teraz 450 tysięcy, szukam Jeepa Wranglera")

    widoczne = [l.id for l in db.list_leads(only_open=True)]
    assert lead_id in widoczne, "powracający klient nadal niewidoczny dla brokera"
    assert db.get_lead(lead_id).stage is Stage.NOWY


def test_nowa_tresc_zostaje_w_historii() -> None:
    """Wznowienie nie może zjeść tego, z czym klient wrócił."""
    lead_id = _zgloszenie("Szukam BMW X5").lead.id
    lead = db.get_lead(lead_id)
    lead.stage = Stage.STRACONY
    db.update_lead(lead)

    _zgloszenie("Wracam, teraz Jeep Wrangler")

    tresci = " ".join(m.text for m in db.messages(lead_id))
    assert "Jeep" in tresci
    assert "Jeep" in db.get_lead(lead_id).raw_request


def test_lead_w_toku_nie_jest_cofany() -> None:
    """Wznawiamy tylko sprawy zamknięte — cofnięcie leada w rozmowie na „nowy"
    kasowałoby kontekst, który broker już zbudował."""
    lead_id = _zgloszenie("Szukam BMW X5").lead.id
    lead = db.get_lead(lead_id)
    lead.stage = Stage.SZUKANIE
    db.update_lead(lead)

    _zgloszenie("Jeszcze jedno pytanie")
    assert db.get_lead(lead_id).stage is Stage.SZUKANIE
