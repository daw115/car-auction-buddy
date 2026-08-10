"""
Sufit ceny aukcyjnej wyliczony z budżetu klienta "pod klucz" w PLN.

Klient mówi "50/60 tysięcy" i ma na myśli kwotę, którą zapłaci w Polsce — nie cenę
na aukcji. Naiwne przeliczenie 60 000 PLN / 4,0 = 15 000 USD pokazałoby auta ponad
dwa razy droższe, niż go stać: przy stawkach z pricing/import_calculator.py lot za
10 000 USD z Florydy to 69 296 PLN dla osoby prywatnej.

Sufit liczymy bisekcją, a nie wzorem. Kalkulator jest dziś liniowy względem ceny, więc
wzór dałoby się wyprowadzić — ale akcyza bywa progowa i wtedy wzór skłamałby po cichu,
a bisekcja po prostu znajdzie inny punkt. Dwadzieścia iteracji czystej funkcji to koszt
pomijalny wobec jednego zapytania do giełdy.
"""
from dataclasses import dataclass
from typing import Literal, Optional

from pricing.import_calculator import (
    calculate_import_costs,
    client_price_pln as _client_price,
    state_median_towing,
)

Settlement = Literal["private", "company"]

# "Pod klucz" znaczy: koszt sprowadzenia PLUS prowizja brokera. Definicja siedzi
# w pricing/import_calculator.client_price_pln i jest wspólna dla wszystkich kanałów.
# UWAGA: broker_basic_gross_pln to sama PROWIZJA (3 198 PLN przy locie za 10 000),
# a nie kwota końcowa — pomylenie tych pól zawyża sufit kilkukrotnie.
_MAX_BID_USD = 200_000.0
_ITERATIONS = 40


@dataclass(frozen=True)
class BudgetCeiling:
    """Ile wolno zalicytować, żeby zmieścić się w budżecie klienta."""

    max_bid_usd: float
    budget_pln: float
    settlement: Settlement
    towing_usd: int
    state: Optional[str]


def max_bid_for_budget(
    budget_pln: float,
    *,
    settlement: Settlement = "private",
    state: Optional[str] = None,
    usd_rate: Optional[float] = None,
    fee_tier: str = "basic",
) -> BudgetCeiling:
    """Najwyższa cena aukcyjna mieszcząca się w budżecie 'pod klucz'.

    Sufit zależy od STANU, bo towing wchodzi do podstawy celnej i mnoży się przez cło,
    VAT i akcyzę — różnica Floryda/Kalifornia to około 600 USD sufitu. Dlatego liczymy
    to per lot, a nie raz na wyszukiwanie.

    Prowizja wchodzi do sufitu, bo klient płaci ją razem z autem. Sufit liczony bez niej
    przepuszczał loty droższe od budżetu o 2 800-4 200 zł.
    """
    towing = state_median_towing(state)
    extra = {"usd_rate": usd_rate} if usd_rate else {}

    low, high = 0.0, _MAX_BID_USD
    for _ in range(_ITERATIONS):
        mid = (low + high) / 2
        costs = calculate_import_costs(bid_usd=mid, towing_usd=towing, **extra)
        landed = _client_price(costs, settlement=settlement, fee_tier=fee_tier)
        if landed <= budget_pln:
            low = mid
        else:
            high = mid

    return BudgetCeiling(
        max_bid_usd=low,
        budget_pln=budget_pln,
        settlement=settlement,
        towing_usd=towing,
        state=state,
    )


def landed_cost_pln(
    bid_usd: float,
    *,
    settlement: Settlement = "private",
    state: Optional[str] = None,
    usd_rate: Optional[float] = None,
    excise_rate: Optional[float] = None,
    fee_tier: str = "basic",
) -> float:
    """Ile klient zapłaci w Polsce za lot kupiony po tej cenie — z prowizją."""
    extra: dict[str, float] = {}
    if usd_rate:
        extra["usd_rate"] = usd_rate
    if excise_rate is not None:
        extra["excise_rate"] = excise_rate
    costs = calculate_import_costs(
        bid_usd=bid_usd, towing_usd=state_median_towing(state), **extra
    )
    return _client_price(costs, settlement=settlement, fee_tier=fee_tier)
