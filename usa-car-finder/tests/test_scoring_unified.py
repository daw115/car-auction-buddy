"""Ujednolicona ocena lotów — wspólna dla Copart, IAAI i Manheim."""
import pytest

from parser.models import CarLot, ClientCriteria
from scoring import OVER_BUDGET, ClientProfile, max_bid_for_budget, rank_lots, score_lot
from scoring.budget import landed_cost_pln

CRITERIA = ClientCriteria(make="Toyota", sources=["manheim"])


def manheim_lot(**over) -> CarLot:
    """Kształt pól wzięty z realnej odpowiedzi onesearch-api.manheim.com."""
    listing = {
        "vin": "JTMRWRFV9PD204814",
        "conditionGrade": "4.8",
        "mmrPrice": 30000,
        "sellerRating": 4.2,
        "greenLight": True,
        "hasFrameDamage": False,
        "salvageVehicle": False,
        "asIs": False,
        "autocheck": {"titleAndProblemCheckOK": True},
    }
    listing.update(over.pop("listing", {}))
    base = dict(
        source="manheim", lot_id="OVE.FAAO.1", url="u", year=2022, make="Toyota",
        model="RAV4", odometer_mi=30_000, current_bid_usd=24_000,
        location_state="FL", seller_type="dealer", raw_data={"listing": listing},
    )
    base.update(over)
    return CarLot(**base)


def salvage_lot(**over) -> CarLot:
    base = dict(
        source="copart", lot_id="1", url="u", year=2020, make="Toyota", model="RAV4",
        odometer_mi=40_000, current_bid_usd=8_000, location_state="FL",
        damage_primary="Minor Dent/Scratches", title_type="Clean",
        seller_type="insurance",
    )
    base.update(over)
    return CarLot(**base)


def test_intact_manheim_car_is_not_penalised_for_lacking_damage():
    """Sedno usterki: auto bez szkód wypadało gorzej niż rozbite.

    Stary scoring nie dopasowywał słowa kluczowego szkody, wpadał w gałąź "nieprecyzyjny
    opis" i odejmował punkty za to, że pojazd jest cały.
    """
    result = score_lot(manheim_lot(), CRITERIA)

    assert result.recommendation == "POLECAM"
    assert result.score >= 8.0
    condition = next(c for c in result.components if c.key == "condition")
    assert condition.value > 0.8
    assert "ride & drive" in condition.detail


def test_price_below_mmr_beats_price_above_mmr():
    """MMR to benchmark rynkowy — okazja musi wygrywać z ofertą powyżej rynku."""
    okazja = score_lot(manheim_lot(current_bid_usd=24_000), CRITERIA)  # -20% do MMR
    drogie = score_lot(manheim_lot(current_bid_usd=33_000), CRITERIA)  # +10% powyżej

    assert okazja.score > drogie.score
    assert okazja.components[0].value > drogie.components[0].value


def test_missing_signal_does_not_lower_the_score():
    """Copart nie publikuje MMR — brak sygnału nie może karać źródła.

    Waga składowej bez danych rozkłada się na pozostałe, więc suma wag zawsze wynosi 1.
    """
    bez_mmr = manheim_lot(listing={"mmrPrice": None})
    result = score_lot(bez_mmr, CRITERIA)

    assert "Cena vs rynek" in result.skipped
    assert sum(c.weight for c in result.components) == pytest.approx(1.0)
    assert result.score >= 8.0


def test_hard_disqualifiers_beat_a_great_price():
    """Dyskwalifikator przekreśla lot — dobra cena nie może przegłosować szkody."""
    for override, expected in (
        ({"listing": {"hasFrameDamage": True}}, "uszkodzenie konstrukcji"),
        ({"damage_primary": "Flood"}, "zalanie lub pożar"),
    ):
        result = score_lot(manheim_lot(current_bid_usd=1_000, **override), CRITERIA)
        assert result.score == 0.0
        assert result.recommendation == "ODRZUĆ"
        assert any(expected in reason for reason in result.disqualifiers)


def test_salvage_blocks_only_when_client_wants_clean_title():
    lot = manheim_lot(listing={"salvageVehicle": True})

    assert score_lot(lot, CRITERIA).recommendation != "ODRZUĆ"
    strict = score_lot(lot, CRITERIA, ClientProfile(require_clean_title=True))
    assert "salvage" in " ".join(strict.disqualifiers)


def test_budget_ceiling_uses_landed_cost_not_naive_conversion():
    """60 tys PLN pod klucz to ~8 tys USD ceny aukcyjnej, nie 15 tys.

    Naiwne dzielenie budżetu przez kurs pokazywałoby auta dwa razy za drogie.
    """
    ceiling = max_bid_for_budget(60_000, settlement="private", state="FL")
    assert 7_500 < ceiling.max_bid_usd < 8_500
    assert landed_cost_pln(ceiling.max_bid_usd, state="FL") == pytest.approx(60_000, abs=50)

    # Zachód jest droższy w transporcie, więc sufit jest niższy przy tym samym budżecie.
    west = max_bid_for_budget(60_000, settlement="private", state="CA")
    assert west.max_bid_usd < ceiling.max_bid_usd

    # Firma płaci VAT od całości — sufit jeszcze niższy.
    firma = max_bid_for_budget(60_000, settlement="company", state="FL")
    assert firma.max_bid_usd < ceiling.max_bid_usd


def test_lot_above_budget_is_flagged_but_keeps_its_score():
    """Ponad budżet to nie wyrok o aucie — to informacja o cenie.

    Auto zostaje na liście z policzoną oceną i czytelnym powodem, żeby broker
    mógł je świadomie zaproponować, zamiast dowiadywać się, że coś zniknęło.
    """
    profile = ClientProfile(budget=max_bid_for_budget(60_000, state="FL"))
    result = score_lot(manheim_lot(current_bid_usd=30_000), CRITERIA, profile)

    assert result.over_budget
    assert result.recommendation == OVER_BUDGET
    assert not result.disqualifiers
    assert result.score > 0
    assert "ponad" in result.budget.note()


def test_flood_still_rejects_regardless_of_budget():
    """Twardy dyskwalifikator zostaje twardy — nie zamienił się w flagę."""
    lot = manheim_lot(current_bid_usd=3_000, damage_primary="Flood/water damage")
    result = score_lot(lot, CRITERIA, ClientProfile(budget=max_bid_for_budget(60_000, state="FL")))

    assert result.recommendation == "ODRZUĆ"
    assert result.score == 0.0
    assert "zalanie lub pożar" in result.disqualifiers


def test_over_budget_lots_stay_out_of_the_offer_unless_asked_for():
    """rank_lots buduje ofertę dla klienta, więc auta ponad budżet do niej nie wchodzą."""
    profile = ClientProfile(budget=max_bid_for_budget(60_000, state="FL"))
    tanie = manheim_lot(lot_id="tanie", current_bid_usd=6_000)
    drogie = manheim_lot(lot_id="drogie", current_bid_usd=30_000)

    domyslnie = rank_lots([tanie, drogie], CRITERIA, profile)
    assert [lot.lot_id for lot, _ in domyslnie] == ["tanie"]

    z_dopuszczeniem = rank_lots([tanie, drogie], CRITERIA, profile, include_over_budget=True)
    # Ponad budżet ląduje na końcu, za wszystkim, co się mieści.
    assert [lot.lot_id for lot, _ in z_dopuszczeniem] == ["tanie", "drogie"]


def test_eastern_states_beat_western_at_equal_everything_else():
    east = score_lot(manheim_lot(location_state="FL"), CRITERIA)
    west = score_lot(manheim_lot(location_state="CA"), CRITERIA)
    assert east.score > west.score


def test_sources_are_comparable():
    """To samo auto o podobnym profilu ma dostać zbliżoną ocenę z obu giełd."""
    manheim = score_lot(manheim_lot(), CRITERIA)
    copart = score_lot(salvage_lot(), ClientCriteria(make="Toyota", sources=["copart"]))
    assert abs(manheim.score - copart.score) < 2.0


def test_ranking_returns_at_most_four_and_drops_weak_lots():
    """Klient dostaje 3-4 oferty, nigdy zapchajdziury poniżej progu."""
    dobre = [manheim_lot(lot_id=str(i), current_bid_usd=22_000 + i * 100) for i in range(6)]
    slabe = manheim_lot(lot_id="slaby", listing={"conditionGrade": "2.1"}, current_bid_usd=33_000)

    ranked = rank_lots(dobre + [slabe], CRITERIA, limit=4)

    assert len(ranked) == 4
    assert all(score.score >= 5.0 for _, score in ranked)
    assert [s.score for _, s in ranked] == sorted((s.score for _, s in ranked), reverse=True)
    assert "slaby" not in [lot.lot_id for lot, _ in ranked]


def test_explanation_shows_every_component_contribution():
    """Broker ma widzieć DLACZEGO, nie samą liczbę."""
    text = score_lot(manheim_lot(), CRITERIA).explain()
    assert "Cena vs rynek" in text and "Stan techniczny" in text and "×" in text


def test_model_gets_the_same_budget_the_scoring_uses():
    """Model i scoring muszą mierzyć tym samym: kwotą pod klucz w PLN.

    Wcześniej prompt podawał budżet w USD "łącznie z transportem i naprawą",
    więc model oceniał dopasowanie według innej definicji niż ta, z której
    powstaje unified_score.over_budget.
    """
    from ai.analyzer import _budget_line

    linia = _budget_line(ClientCriteria(make="Toyota", budget_pln_to=60_000))

    assert "zł pod klucz" in linia
    assert "USD" not in linia
    # Przecinki w wyliczeniu muszą przeżyć formatowanie liczby.
    assert "zakup, transport, cło" in linia


def test_budget_line_falls_back_to_usd_only_when_pln_is_missing():
    from ai.analyzer import _budget_line

    assert "USD" in _budget_line(ClientCriteria(make="Toyota", budget_usd=9_000))
    assert "bez limitu" in _budget_line(ClientCriteria(make="Toyota"))


def test_opening_bid_is_not_a_bargain():
    """Lot ze stawką 100 USD dostawał 8,8/10 i stawał na szczycie listy.

    Składowa „cena wobec rynku" widziała okazję życia tam, gdzie po prostu nikt
    jeszcze nie licytował. To przekłamywało ranking pokazywany klientowi.
    """
    from scoring.unified import _lot_price

    assert _lot_price(manheim_lot(current_bid_usd=100)) is None
    assert _lot_price(manheim_lot(current_bid_usd=0)) is None
    assert _lot_price(manheim_lot(current_bid_usd=6_000)) == 6_000


def test_lot_without_a_price_scores_on_everything_else():
    """Brak ceny pomija składową cenową, a jej waga idzie na pozostałe —
    nie zeruje lota i nie wynosi go na szczyt."""
    bez_ceny = score_lot(manheim_lot(current_bid_usd=0), CRITERIA)

    assert bez_ceny.score > 0, "auto bez otwartej licytacji nadal da się ocenić"
    assert any("cena" in s.lower() for s in bez_ceny.skipped), "składowa cenowa pominięta"


def test_a_lot_without_a_price_is_never_over_budget():
    """Bez ceny nie ma jak stwierdzić, że przekracza budżet — i nie zgadujemy."""
    profile = ClientProfile(budget=max_bid_for_budget(60_000, state="FL"))

    assert not score_lot(manheim_lot(current_bid_usd=0), CRITERIA, profile).over_budget
