"""
Sufit ceny aukcyjnej wyliczony z budżetu klienta "pod drzwi" w PLN.

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

from pricing import fx as _fx
from pricing.import_calculator import (
    calculate_import_costs,
    calculate_lot_import_costs,
    client_price_pln as _client_price,
    state_median_towing,
)
Settlement = Literal["private", "company"]

# "Pod drzwi" znaczy: koszt sprowadzenia PLUS prowizja brokera. Definicja siedzi
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
    duty_rate: Optional[float] = None,
    fee_tier: str = "basic",
) -> BudgetCeiling:
    """Najwyższa cena aukcyjna mieszcząca się w budżecie 'pod drzwi'.

    Sufit zależy od STANU, bo towing wchodzi do podstawy celnej i mnoży się przez cło,
    VAT i akcyzę — różnica Floryda/Kalifornia to około 600 USD sufitu. Dlatego liczymy
    to per lot, a nie raz na wyszukiwanie.

    Prowizja wchodzi do sufitu, bo klient płaci ją razem z autem. Sufit liczony bez niej
    przepuszczał loty droższe od budżetu o 2 800-4 200 zł.

    STAWKA CŁA: podawaj ją, kiedy tylko znasz auto. Bez `duty_rate` liczymy zachowawczo
    po 10%, bo bez VIN-u nie wiemy, gdzie auto zmontowano — a sufit musi wtedy zgadzać
    się co do złotówki z `landed_cost_pln`, które jest równie ślepe. Rozjazd między tymi
    dwiema funkcjami to dwie różne kwoty za to samo auto, czyli dokładnie ta niespójność,
    której nie wolno pokazać klientowi.

    Zachowawczy sufit zaniża jednak liczbę aut uznanych za mieszczące się w budżecie:
    przy cle 0% klienta stać na wyraźnie więcej. Dlatego `scoring/unified.py` liczy
    sufit PER LOT i podaje tu stawkę wyprowadzoną z VIN-u tego konkretnego auta.
    Wtedy jest i spójnie, i prawdziwie.
    """
    towing = state_median_towing(state)
    extra: dict[str, float] = {"usd_rate": usd_rate or _fx.current_rate()}
    if duty_rate is not None:
        extra["duty_rate"] = duty_rate

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
    """Ile klient zapłaci w Polsce za lot kupiony po tej cenie — z prowizją.

    Wersja "po samej cenie i stanie": nie zna auta, więc nie zna ani kraju montażu,
    ani napędu. Cło liczy zachowawczo po 10%. Gdy masz obiekt lota, użyj
    `landed_cost_for_lot` — poda kwotę niższą i prawdziwą.
    """
    extra: dict[str, float] = {"usd_rate": usd_rate or _fx.current_rate()}
    if excise_rate is not None:
        extra["excise_rate"] = excise_rate
    costs = calculate_import_costs(
        bid_usd=bid_usd, towing_usd=state_median_towing(state), **extra
    )
    return _client_price(costs, settlement=settlement, fee_tier=fee_tier)


def landed_cost_for_lot(
    lot,
    *,
    settlement: Settlement = "private",
    fee_tier: str = "basic",
) -> Optional[float]:
    """Cena pod drzwi dla konkretnego auta — jedyna wersja, którą wolno pokazać klientowi.

    Różnica wobec `landed_cost_pln` to cło i akcyza wyprowadzone z danych auta: kraj
    montażu z VIN-u i rodzaj napędu z opisu wersji. Na aucie zmontowanym w USA jest to
    kilka tysięcy złotych mniej, a to zwykle cała przewaga nad ofertą konkurencji.

    None, gdy lot nie ma ceny — auto bez stawki nie ma ceny pod drzwi.
    """
    costs = calculate_lot_import_costs(lot)
    if not costs:
        return None
    return _client_price(costs, settlement=settlement, fee_tier=fee_tier)
