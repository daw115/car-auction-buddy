"""Auto, którego model nie opisał, ma zostać w wynikach.

`_results_from_analysis_data` iterowało po ANALIZACH, nie po lotach, więc lot
bez wpisu w odpowiedzi modelu po prostu do wyników nie wchodził. A wpisu potrafi
zabraknąć z powodów niezwiązanych z autem: pominięty chunk po dwukrotnym błędzie
parsowania (`analyzer.py` robi to po cichu), model gubiący pozycję przy dłuższej
liście, ucięta odpowiedź. Broker dostawał krótszą listę i nie miał jak poznać,
że czegoś na niej brakuje.

Ranking jest deterministyczny i policzony ZANIM model cokolwiek powie — model
dokłada tylko prozę — więc takie auto da się uszeregować normalnie.
"""

from parser.models import CarLot
from ai.analyzer import _results_from_analysis_data


def _lot(lot_id: str, *, score: float = 7.0, **unified_extra) -> CarLot:
    unified = {"score": score, "disqualifiers": [], "recommendation": "POLECAM", **unified_extra}
    return CarLot(
        source="copart",
        lot_id=lot_id,
        url=f"https://x/{lot_id}",
        year=2021,
        make="BMW",
        model="X5",
        raw_data={"unified_score": unified},
    )


def test_lot_pominiety_przez_model_zostaje_w_wynikach() -> None:
    loty = [_lot("A", score=8.0), _lot("B", score=6.0)]
    # model opisał tylko jeden z dwóch
    analizy = [{"lot_id": "A", "score": 8.0, "recommendation": "POLECAM",
                "client_description_pl": "opis"}]

    top, reszta = _results_from_analysis_data(analizy, loty, top_n=5)
    wszystkie = {a.lot.lot_id for a in top + reszta}
    assert wszystkie == {"A", "B"}, "auto bez opisu modelu wypadło z wyników"


def test_odzyskany_lot_niesie_ocene_deterministyczna() -> None:
    loty = [_lot("B", score=6.4)]
    top, reszta = _results_from_analysis_data([], loty, top_n=5)
    odzyskany = (top + reszta)[0]
    assert odzyskany.analysis.score == 6.4
    assert "deterministycznie" in (odzyskany.analysis.ai_notes or "")


def test_dyskwalifikacja_z_oceny_deterministycznej_jest_respektowana() -> None:
    """Auto po powodzi nie może wrócić do wyników jako POLECAM tylko dlatego,
    że model go nie opisał."""
    loty = [_lot("C", score=0.0, disqualifiers=["Zalane"], recommendation="ODRZUĆ")]
    top, reszta = _results_from_analysis_data([], loty, top_n=5)
    odzyskany = (top + reszta)[0]
    assert odzyskany.analysis.recommendation == "ODRZUĆ"
    assert "Zalane" in odzyskany.analysis.red_flags


def test_lot_bez_zadnej_oceny_nie_jest_zmyslany() -> None:
    """Bez oceny deterministycznej nie ma z czego zbudować pozycji — wtedy
    wypada, ale zostaje po tym ślad w logu."""
    lot = CarLot(source="copart", lot_id="D", url="https://x/D", year=2021, make="BMW", model="X5")
    top, reszta = _results_from_analysis_data([], [lot], top_n=5)
    assert not (top + reszta)
