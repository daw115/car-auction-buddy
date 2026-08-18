"""Zepsuty JSON od modelu ma być ponawiany, bo mija za drugim razem.

W logu produkcyjnym 34 raporty nie powstały, bo pętla ponawiania rozpoznawała
awarie po fragmentach tekstu w komunikacie („timeout", „503"). Komunikat
o niedającym się sparsować JSON-ie nie zawierał żadnego z tych słów, więc
wyjątek leciał bez drugiej próby — choć ten sam lot i te same dane dawały za
drugim razem poprawną odpowiedź (sprawdzone na locie 46182357).
"""

import json

import pytest

from report import hybrid_reports
from report.hybrid_reports import OdpowiedzNieDoOdczytania, _parse_json_loose


def test_zepsuty_json_daje_wlasny_typ_wyjatku() -> None:
    """Po typie, nie po treści komunikatu — dopasowywanie po napisach jest tym,
    przez co ta luka w ogóle powstała."""
    with pytest.raises(OdpowiedzNieDoOdczytania):
        _parse_json_loose('{"a": "niedomkniety cudzyslow}')


def test_komunikat_pokazuje_okolice_usterki() -> None:
    """Przy błędzie na znaku 4015 początek dokumentu nie mówi nic."""
    zepsuty = '{"tekst": "' + ("x" * 4000) + '" "brak przecinka": 1}'
    with pytest.raises(OdpowiedzNieDoOdczytania) as blad:
        _parse_json_loose(zepsuty)
    tresc = str(blad.value)
    assert "wokol_bledu" in tresc
    assert "dlugosc=" in tresc


def test_druga_proba_ratuje_raport(monkeypatch) -> None:
    proby = {"n": 0}

    def raz_zle_raz_dobrze(system, user, max_tokens=1500):
        proby["n"] += 1
        if proby["n"] == 1:
            return _parse_json_loose('{"zepsute": "bez domkniecia}')
        return json.loads('{"ok": true}')

    monkeypatch.setattr(hybrid_reports, "_provider", lambda: "claude")
    monkeypatch.setattr(hybrid_reports, "_call_claude_json", raz_zle_raz_dobrze)
    monkeypatch.setenv("LLM_REPORTS_MAX_RETRIES", "2")
    monkeypatch.setattr(hybrid_reports.time, "sleep", lambda _s: None)

    assert hybrid_reports._call_llm_json("sys", "user") == {"ok": True}
    assert proby["n"] == 2, "druga próba nie doszła do skutku"


def test_uporczywa_awaria_nadal_konczy_sie_wyjatkiem(monkeypatch) -> None:
    """Ponawianie nie może zamieniać trwałej awarii w ciszę — od tego jest
    zejście na szablon w api/main.py, a nie udawanie sukcesu tutaj."""

    def zawsze_zle(system, user, max_tokens=1500):
        return _parse_json_loose("{to nie jest json")

    monkeypatch.setattr(hybrid_reports, "_provider", lambda: "claude")
    monkeypatch.setattr(hybrid_reports, "_call_claude_json", zawsze_zle)
    monkeypatch.setenv("LLM_REPORTS_MAX_RETRIES", "2")
    monkeypatch.setattr(hybrid_reports.time, "sleep", lambda _s: None)

    with pytest.raises(OdpowiedzNieDoOdczytania):
        hybrid_reports._call_llm_json("sys", "user")
