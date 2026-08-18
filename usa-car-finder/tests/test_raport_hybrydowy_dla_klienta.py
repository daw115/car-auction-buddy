"""Raport hybrydowy to DOMYŚLNY raport dla klienta (REPORTS_MODE=hybrid).

Mimo nazwy „RAPORT KLIENTA" pokazywał cenę aukcyjną, nasz wewnętrzny wynik
punktowy, werdykt POLECAM/RYZYKO, osobną pozycję „Prowizja" i link prosto na
aukcję. Każda z tych rzeczy jest wprost zakazana w `agent-oferta-auto-usa.md`:
klient dostaje JEDNĄ cenę pod drzwi i listę tego, co obejmuje, a rozbicie idzie
do briefu brokera.

Testy czytają sam szablon, nie wynik renderowania — render wymaga modelu
językowego i kluczy, a pytanie brzmi „czy szablon w ogóle sięga po te pola".
"""

import re
from pathlib import Path

SZABLON = (
    Path(__file__).resolve().parents[1] / "report" / "templates" / "hybrid" / "client_hybrid.html.j2"
)


def _tresc() -> str:
    return SZABLON.read_text(encoding="utf-8")


def test_nie_pokazuje_ceny_aukcyjnej() -> None:
    """Klient płaci kwotę pod drzwi. Cena z aukcji zaprasza go do liczenia marży."""
    tresc = _tresc()
    assert "current_bid_usd" not in tresc
    assert "cost.bid_usd" not in tresc
    assert "auction_fee_usd" not in tresc


def test_nie_pokazuje_wewnetrznego_wyniku_ani_werdyktu() -> None:
    """`ai.score` i POLECAM/RYZYKO to nasza metryka robocza, nie ocena dla klienta."""
    tresc = _tresc()
    assert "ai.score" not in tresc
    assert "ai.recommendation" not in tresc


def test_nie_wypisuje_prowizji_jako_osobnej_pozycji() -> None:
    assert "broker_fee_pln" not in _tresc()


def test_nie_linkuje_klienta_na_aukcje() -> None:
    """Link do lota prowadzi klienta prosto tam, gdzie licytuje broker."""
    assert "lot.url" not in _tresc()


def test_uszkodzenie_idzie_po_polsku() -> None:
    tresc = _tresc()
    assert "uszkodzenie_pl" in tresc
    assert not re.search(r"\{\{\s*lot\.damage_primary", tresc)


def test_cena_pod_drzwi_zostaje() -> None:
    """Zdejmujemy rozbicie, nie samą cenę — klient ma wiedzieć, ile zapłaci."""
    assert "grand_total_pln" in _tresc()


def test_nie_zdradza_ze_pisala_to_maszyna() -> None:
    """Nazwa dostawcy i modelu w stopce mówi klientowi, kto naprawdę pisał raport."""
    tresc = _tresc()
    assert "{{ provider }}" not in tresc
    assert "{{ model }}" not in tresc
