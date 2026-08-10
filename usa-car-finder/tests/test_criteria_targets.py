"""Kryteria klienta na danych, które realnie przychodzą z arkusza leadów."""
import pytest
from pydantic import ValidationError

from parser.models import CarLot, ClientCriteria, SearchTarget
from scoring import OVER_BUDGET, profile_from_criteria, score_lot


def test_lead_with_several_models_becomes_several_search_targets():
    """Lead "karoq kodiaq, vw tiguan" — trzy modele z dwóch marek w jednym zleceniu.

    Wcześniej wymagało trzech osobnych wyszukiwań i trzech osobnych rankingów,
    więc ofert nie dało się porównać między sobą.
    """
    criteria = ClientCriteria(
        make="Skoda", model="Karoq",
        targets=[SearchTarget(make="Skoda", model="Kodiaq"),
                 SearchTarget(make="Volkswagen", model="Tiguan")],
    )

    targets = [(t.make, t.model) for t in criteria.search_targets()]
    assert targets == [("Skoda", "Karoq"), ("Skoda", "Kodiaq"), ("Volkswagen", "Tiguan")]


def test_primary_target_stays_first_and_duplicates_drop_out():
    criteria = ClientCriteria(
        make="Toyota", model="RAV4",
        targets=[SearchTarget(make="toyota", model="rav4"), SearchTarget(make="Honda")],
    )
    targets = [(t.make, t.model) for t in criteria.search_targets()]
    assert targets == [("Toyota", "RAV4"), ("Honda", None)]


def test_single_target_behaves_as_before():
    """Zachowanie sprzed wprowadzenia list musi zostać nietknięte."""
    criteria = ClientCriteria(make="BMW")
    assert [(t.make, t.model) for t in criteria.search_targets()] == [("BMW", None)]


def test_budget_is_taken_from_the_upper_bracket():
    """Klient mówi "50/60 tys" — szukamy do górnej granicy."""
    criteria = ClientCriteria(make="Ford", budget_pln_from=50_000, budget_pln_to=60_000)
    assert criteria.budget_pln() == 60_000

    assert ClientCriteria(make="Ford", budget_pln_from=50_000).budget_pln() == 50_000
    assert ClientCriteria(make="Ford").budget_pln() is None


def test_reversed_budget_bracket_is_rejected():
    with pytest.raises(ValidationError):
        ClientCriteria(make="Ford", budget_pln_from=60_000, budget_pln_to=50_000)


def test_settlement_must_be_a_known_variant():
    assert ClientCriteria(make="Ford", settlement="company").settlement == "company"
    with pytest.raises(ValidationError):
        ClientCriteria(make="Ford", settlement="barter")


def test_segment_is_context_not_a_filter():
    """Samo "suv" nie zawęzi wyszukiwania — służy agentowi do zaproponowania modeli."""
    criteria = ClientCriteria(make="Ford", model="Edge", segment="suv")
    assert criteria.segment == "suv"
    assert [(t.make, t.model) for t in criteria.search_targets()] == [("Ford", "Edge")]


def _lot(state: str, price: float) -> CarLot:
    return CarLot(
        source="manheim", lot_id="1", url="u", year=2020, make="Toyota", model="RAV4",
        odometer_mi=50_000, current_bid_usd=price, location_state=state,
        raw_data={"listing": {"conditionGrade": "4.5", "mmrPrice": 9000}},
    )


def test_budget_ceiling_differs_between_states():
    """Towing wchodzi do podstawy celnej, więc ten sam budżet daje inny sufit.

    Lot za 7 200 USD mieści się w 60 tys. zł z Florydy (sufit 7 534), ale nie
    z Kalifornii (sufit 6 926). Sufity liczone z prowizją — klient płaci ją razem z autem.
    """
    criteria = ClientCriteria(make="Toyota", budget_pln_to=60_000)
    profile = profile_from_criteria(criteria)

    floryda = score_lot(_lot("FL", 7_200), criteria, profile)
    kalifornia = score_lot(_lot("CA", 7_200), criteria, profile)

    assert not floryda.over_budget
    assert kalifornia.over_budget
    assert kalifornia.recommendation == OVER_BUDGET
    # Przekroczenie budżetu nie jest wadą auta: ocena zostaje policzona, żeby
    # broker widział, czy warto proponować klientowi dołożenie.
    assert kalifornia.score > 0
    assert not kalifornia.disqualifiers
    assert "ponad budżet" in kalifornia.budget.note()


def test_company_purchase_lowers_the_ceiling():
    """Firma płaci VAT od całości — mniej zostaje na samo auto."""
    prywatnie = ClientCriteria(make="Toyota", budget_pln_to=60_000, settlement="private")
    firma = ClientCriteria(make="Toyota", budget_pln_to=60_000, settlement="company")

    lot = _lot("FL", 7_000)
    assert not score_lot(lot, prywatnie, profile_from_criteria(prywatnie)).over_budget
    assert score_lot(lot, firma, profile_from_criteria(firma)).over_budget


def test_no_budget_means_no_ceiling():
    """Klient bez podanego budżetu nie może tracić lotów na filtrze ceny."""
    criteria = ClientCriteria(make="Toyota")
    result = score_lot(_lot("FL", 30_000), criteria, profile_from_criteria(criteria))
    assert result.recommendation != "ODRZUĆ"
    assert not result.over_budget
