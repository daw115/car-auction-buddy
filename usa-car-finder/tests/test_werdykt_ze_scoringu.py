"""Werdykt pochodzi ze scoringu, nie od modelu.

`ai/analyzer.py` nadpisywał deterministyczną oceną tylko `score`, a etykietę
zostawiał modelowi — i to ONA decyduje o wszystkim dalej: showcase filtruje po
dokładnym `== "POLECAM"`, ranking sortuje po niej PRZED oceną, liczniki i oferta
dla klienta też idą po etykiecie.

Skutki szły w obie strony i żaden nie dawał sygnału: auto z oceną 9,7 lądowało
w gorszym koszyku (model pominął pole → domyślne „RYZYKO"), a auto z oceną 5,2
wchodziło do oferty, bo model napisał „POLECAM". Panel pokazywał wysoką ocenę
obok złej etykiety i nic nie wyglądało na awarię.
"""

from parser.models import CarLot
from ai.analyzer import _results_from_analysis_data


def _lot(lot_id: str, score: float, recommendation: str, **extra) -> CarLot:
    return CarLot(
        source="copart", lot_id=lot_id, url=f"https://x/{lot_id}",
        year=2021, make="BMW", model="X5",
        raw_data={"unified_score": {
            "score": score, "recommendation": recommendation,
            "disqualifiers": [], **extra,
        }},
    )


def _werdykt(analizy, loty):
    top, reszta = _results_from_analysis_data(analizy, loty, top_n=5)
    return {a.lot.lot_id: a.analysis.recommendation for a in top + reszta}


def test_model_pomijajacy_pole_nie_degraduje_dobrego_auta() -> None:
    """Brak `recommendation` w JSON-ie modelu dawał domyślne „RYZYKO"."""
    loty = [_lot("A", 9.7, "POLECAM")]
    analizy = [{"lot_id": "A", "score": 9.7, "client_description_pl": "opis"}]
    assert _werdykt(analizy, loty)["A"] == "POLECAM"


def test_model_nie_awansuje_slabego_auta_do_oferty() -> None:
    """Kierunek groźniejszy: auto ocenione na 5,2 szło do klienta jako POLECAM."""
    loty = [_lot("B", 5.2, "RYZYKO")]
    analizy = [{"lot_id": "B", "score": 5.2, "recommendation": "POLECAM",
                "client_description_pl": "opis"}]
    assert _werdykt(analizy, loty)["B"] == "RYZYKO"


def test_etykieta_spoza_slownika_nie_wypada_z_koszykow() -> None:
    """„Polecam (z zastrzeżeniami)" nie pasuje do żadnego filtra, więc auto
    znikało z showcase'u, z liczników i z rankingu naraz."""
    loty = [_lot("C", 8.1, "POLECAM")]
    analizy = [{"lot_id": "C", "score": 8.1, "recommendation": "Polecam (z zastrzeżeniami)",
                "client_description_pl": "opis"}]
    assert _werdykt(analizy, loty)["C"] == "POLECAM"


def test_dyskwalifikator_nadal_wygrywa_ze_wszystkim() -> None:
    lot = _lot("D", 0.0, "POLECAM")
    lot.raw_data["unified_score"]["disqualifiers"] = ["Zalane"]
    analizy = [{"lot_id": "D", "score": 9.0, "recommendation": "POLECAM",
                "client_description_pl": "opis"}]
    assert _werdykt(analizy, [lot])["D"] == "ODRZUĆ"


def test_ponad_budzet_nadal_wygrywa_z_modelem() -> None:
    lot = _lot("E", 8.0, "POLECAM", over_budget=True, budget={"note": "o 12 tys. zł za drogo"})
    analizy = [{"lot_id": "E", "score": 8.0, "recommendation": "POLECAM",
                "client_description_pl": "opis"}]
    assert _werdykt(analizy, [lot])["E"] == "PONAD BUDŻET"
