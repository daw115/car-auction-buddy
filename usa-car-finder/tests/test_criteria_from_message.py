"""Notatka brokera albo wiadomość z WhatsAppa -> kryteria wyszukiwania."""
from ai.criteria_from_message import criteria_from_parsed


def parsed(**over) -> dict:
    base = {
        "cars": [{"make": "Ford", "model": "Edge"}],
        "segment": None, "budget_pln_from": None, "budget_pln_to": None,
        "settlement": None, "risk": None, "_summary": "", "_warnings": [],
    }
    base.update(over)
    return base


def test_note_with_several_models_becomes_targets():
    """Notatka "karoq kodiaq, vw tiguan" — trzy cele w jednym zleceniu."""
    result = criteria_from_parsed(parsed(cars=[
        {"make": "Skoda", "model": "Karoq"},
        {"make": "Skoda", "model": "Kodiaq"},
        {"make": "Volkswagen", "model": "Tiguan"},
    ]))

    assert [(t.make, t.model) for t in result.criteria.search_targets()] == [
        ("Skoda", "Karoq"), ("Skoda", "Kodiaq"), ("Volkswagen", "Tiguan"),
    ]


def test_budget_stays_in_pln_and_is_not_converted():
    """Kwota od klienta to budżet pod drzwi, nie cena aukcyjna.

    Przeliczanie jej kursem dawało sufit ponad dwa razy za wysoki.
    """
    result = criteria_from_parsed(parsed(budget_pln_from=50_000, budget_pln_to=60_000))

    assert result.criteria.budget_pln() == 60_000
    assert result.criteria.budget_usd is None


def test_unconfirmed_fields_are_reported_for_the_follow_up_call():
    """Formularz ma pokazać, co zostało zgadnięte — broker wie, o co dopytać."""
    result = criteria_from_parsed(parsed())

    assert "budżet" in result.assumed
    assert any("forma zakupu" in item for item in result.assumed)
    assert any("ryzyko" in item for item in result.assumed)
    assert "rocznik" in result.assumed


def test_confirmed_fields_are_not_reported_as_assumed():
    result = criteria_from_parsed(parsed(
        cars=[{"make": "Ford", "model": "Edge", "year_from": 2018, "year_to": 2021,
               "max_odometer_mi": 90_000}],
        budget_pln_to=60_000, settlement="company", risk="none",
    ))

    assert result.assumed == []
    assert result.criteria.settlement == "company"


def test_settlement_defaults_to_private_but_is_flagged():
    """Domyślna wartość jest zaznaczona, ale oznaczona jako niepotwierdzona."""
    result = criteria_from_parsed(parsed())
    assert result.criteria.settlement == "private"
    assert any("forma zakupu" in item for item in result.assumed)


def test_flood_and_fire_are_excluded_by_default():
    result = criteria_from_parsed(parsed())
    assert result.criteria.excluded_damage_types == ["Flood", "Fire"]


def test_segment_is_carried_over_as_context():
    result = criteria_from_parsed(parsed(segment="suv"))
    assert result.criteria.segment == "suv"


def test_message_without_a_make_yields_nothing():
    """Zgadywanie marki z samego segmentu należy do agenta, nie do konwersji."""
    assert criteria_from_parsed(parsed(cars=[], segment="suv")) is None
    assert criteria_from_parsed(parsed(cars=[{"model": "Edge"}])) is None
