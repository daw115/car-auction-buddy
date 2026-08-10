"""Deterministyczna ocena musi wygrywać z tą, którą policzył model."""
from parser.models import CarLot, ClientCriteria
from ai.analyzer import _attach_unified_scores, _results_from_analysis_data

CRITERIA = ClientCriteria(make="Toyota", sources=["manheim"])


def manheim_lot(lot_id="A1", **over) -> CarLot:
    listing = {
        "vin": "JTMRWRFV9PD204814",
        "conditionGrade": "4.8",
        "mmrPrice": 30000,
        "sellerRating": 4.2,
        "greenLight": True,
        "autocheck": {"titleAndProblemCheckOK": True},
    }
    listing.update(over.pop("listing", {}))
    base = dict(
        source="manheim", lot_id=lot_id, url="u", year=2022, make="Toyota", model="RAV4",
        odometer_mi=30_000, current_bid_usd=24_000, location_state="FL",
        seller_type="dealer", raw_data={"listing": listing},
    )
    base.update(over)
    return CarLot(**base)


def test_score_is_attached_before_the_model_is_called():
    """Model dostaje ocenę gotową w payloadzie, a nie liczy jej sam."""
    lot = manheim_lot()
    _attach_unified_scores([lot], CRITERIA)

    unified = lot.raw_data["unified_score"]
    assert unified["score"] > 7.0
    assert unified["components"], "rozbicie na składowe jest potrzebne do opisu"
    assert "Cena vs rynek" in unified["explain"]


def test_model_score_is_overridden_by_the_deterministic_one():
    """Model bywa niekonsekwentny między lotami tej samej jakości.

    Ranking ma być odtwarzalny, więc liczba z modelu jest ignorowana.
    """
    lot = manheim_lot()
    _attach_unified_scores([lot], CRITERIA)

    top, _ = _results_from_analysis_data(
        [{"lot_id": "A1", "score": 2.0, "recommendation": "ODRZUĆ",
          "reasoning_pl": "model twierdzi inaczej"}],
        [lot],
        top_n=4,
    )

    assert top[0].analysis.score == lot.raw_data["unified_score"]["score"]
    assert top[0].analysis.score > 7.0


def test_hard_disqualifier_forces_rejection_even_if_model_recommends():
    lot = manheim_lot(listing={"hasFrameDamage": True})
    _attach_unified_scores([lot], CRITERIA)

    top, _ = _results_from_analysis_data(
        [{"lot_id": "A1", "score": 9.5, "recommendation": "POLECAM",
          "reasoning_pl": "model zachwycony"}],
        [lot],
        top_n=4,
    )

    assert top[0].analysis.recommendation == "ODRZUĆ"
    assert top[0].analysis.score == 0.0
    assert any("konstrukcji" in flag for flag in top[0].analysis.red_flags)


def test_missing_scoring_module_does_not_break_analysis(monkeypatch):
    """Brak modułu nie może wywalić całej analizy — zostaje ocena z modelu."""
    lot = manheim_lot(raw_data={})
    monkeypatch.setitem(__import__("sys").modules, "scoring", None)
    _attach_unified_scores([lot], CRITERIA)
    assert "unified_score" not in lot.raw_data


def test_local_fallback_uses_the_same_scale(monkeypatch):
    """Awaria modelu nie może cicho zmienić kryteriów rankingu.

    Heurystyka lokalna startuje od 5.5 i dodaje własne korekty, więc "7.2" z tej
    ścieżki znaczyło co innego niż "7.2" ze scoringu.
    """
    from ai.analyzer import _analyze_lots_locally

    lot = manheim_lot()
    _attach_unified_scores([lot], CRITERIA)
    expected = lot.raw_data["unified_score"]["score"]

    top, _ = _analyze_lots_locally([lot], CRITERIA, top_n=4)

    # AIAnalysis zaokrągla ocenę do jednego miejsca.
    assert round(top[0].analysis.score, 1) == round(expected, 1)


def test_local_fallback_respects_hard_disqualifiers():
    from ai.analyzer import _analyze_lots_locally

    lot = manheim_lot(listing={"hasFrameDamage": True})
    _attach_unified_scores([lot], CRITERIA)

    top, all_results = _analyze_lots_locally([lot], CRITERIA, top_n=4)

    assert all_results[0].analysis.recommendation == "ODRZUĆ"
    assert any("konstrukcji" in flag for flag in all_results[0].analysis.red_flags)


def test_manheim_without_damage_text_is_not_flagged_as_vague():
    """Brak opisu szkód na rynku dealerskim to norma, nie brak danych."""
    from ai.analyzer import _estimate_repair_cost

    manheim = CarLot(source="manheim", lot_id="1", url="u")
    copart = CarLot(source="copart", lot_id="2", url="u")

    assert _estimate_repair_cost(manheim)[1] == []
    assert "Nieprecyzyjny opis uszkodzeń" in _estimate_repair_cost(copart)[1]
