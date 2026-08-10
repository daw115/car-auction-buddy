"""Jedna cena za jedno auto — niezależnie od tego, którą ścieżką ją policzymy.

Klient dostaje wiadomość na WhatsAppie, mail ofertowy i link do raportu per lot.
Trzy różne kwoty za to samo auto to nie rozbieżność do wyjaśnienia w rozmowie,
tylko podważona wiarygodność całej oferty.
"""
import pytest

from parser.models import CarLot
from pricing.import_calculator import (
    EXCISE_EV,
    EXCISE_LARGE,
    EXCISE_SMALL,
    calculate_import_costs,
    client_price_pln,
    engine_liters_from_trim,
    excise_rate_for,
)
from report.cost_calculator import calculate_full_cost
from report.offer_agent import build_car
from scoring.budget import landed_cost_pln, max_bid_for_budget


def lot(bid=10_000.0, state="FL", city="MIAMI SOUTH", trim="3.0 TDI") -> CarLot:
    return CarLot(
        source="copart", lot_id="L1", url="u", year=2019, make="BMW", model="X5",
        trim=trim, odometer_mi=60_000, current_bid_usd=bid,
        location_state=state, location_city=city,
    )


def test_client_price_is_import_cost_plus_commission():
    costs = calculate_import_costs(bid_usd=10_000, towing_usd=980)
    assert client_price_pln(costs) == pytest.approx(
        costs["private_total_pln"] + costs["broker_basic_gross_pln"]
    )
    assert client_price_pln(costs, fee_tier="premium") > client_price_pln(costs)
    assert client_price_pln(costs, settlement="company") > client_price_pln(costs)


def test_offer_and_per_lot_report_quote_the_same_number():
    """Mail ofertowy i raport per lot liczą z tego samego kalkulatora z arkusza."""
    car = build_car(lot())
    report = calculate_full_cost(
        bid_usd=10_000, engine_liters=3.0, location_state="FL",
        location_city="MIAMI SOUTH", repair_estimate_usd=1_200,
    )
    assert report["grand_total_pln"] == round(car.client_price_pln)


def test_whatsapp_and_offer_quote_the_same_number():
    """Ta sama stawka, ta sama kwota — kanały nie mogą się różnić o prowizję."""
    car = build_car(lot(trim="1.6 TDI", city=None))
    assert landed_cost_pln(10_000, state="FL", excise_rate=EXCISE_SMALL) == pytest.approx(
        car.client_price_pln
    )


def test_repair_estimate_stays_outside_the_price():
    """Szacunek naprawy to nie kwota, którą ktokolwiek zafakturuje."""
    bez = calculate_full_cost(10_000, engine_liters=2.0, location_state="FL")
    z_naprawa = calculate_full_cost(10_000, engine_liters=2.0, location_state="FL",
                                    repair_estimate_usd=1_200)
    assert bez["grand_total_pln"] == z_naprawa["grand_total_pln"]
    assert z_naprawa["repair_pln"] > 0


def test_budget_ceiling_leaves_room_for_the_commission():
    """Sufit liczony bez prowizji przepuszczał auta ponad budżet klienta."""
    ceiling = max_bid_for_budget(60_000, state="FL")
    assert landed_cost_pln(ceiling.max_bid_usd, state="FL") == pytest.approx(60_000, abs=50)


@pytest.mark.parametrize(
    "liters, expected",
    [
        (1.6, EXCISE_SMALL),
        (2.0, EXCISE_SMALL),   # "2.0" to w praktyce 1984-1998 cm³, czyli poniżej progu
        (2.5, EXCISE_LARGE),
        (None, EXCISE_LARGE),  # nie wiemy = liczymy drożej, żeby nie dopłacać po fakcie
    ],
)
def test_excise_rate_follows_engine_size(liters, expected):
    assert excise_rate_for(liters) == expected


def test_electric_pays_no_excise():
    assert excise_rate_for(None, electric=True) == EXCISE_EV


@pytest.mark.parametrize(
    "trim, expected",
    [("3.0 TDI", 3.0), ("2.0T", 2.0), ("1,4 TSI", 1.4), ("xDrive40i", None), (None, None)],
)
def test_engine_size_is_read_from_the_trim(trim, expected):
    assert engine_liters_from_trim(trim) == expected


def test_report_breakdown_sums_up_to_the_quoted_price():
    """Rozbicie w raporcie musi się zgadzać z sumą — inaczej broker traci zaufanie do tabeli."""
    cost = calculate_full_cost(10_000, engine_liters=3.0, location_state="FL")
    pozycje = (
        cost["usa_total_pln"] + cost["duty_pln"] + cost["vat_pln"]
        + cost["clearance_de_pln"] + cost["transport_pl_pln"] + cost["excise_pln"]
    )
    assert pozycje == pytest.approx(cost["landed_pln"], abs=2)
    assert cost["landed_pln"] + cost["broker_fee_pln"] == pytest.approx(
        cost["grand_total_pln"], abs=2
    )
