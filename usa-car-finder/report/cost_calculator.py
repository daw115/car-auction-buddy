"""Koszty importu dla raportów per lot — nakładka na kalkulator z arkusza.

Wcześniej ten moduł liczył import po własnym, podręcznikowym modelu (cło + akcyza + VAT
płacone w Polsce, homologacja, tłumaczenia, rejestracja) i wychodziły z niego kwoty o 9-25%
wyższe niż z `pricing/import_calculator.py`, czyli z kalkulatora przepisanego z arkusza.
Skutek: raport per lot pokazywał inną cenę tego samego auta niż mail ofertowy i wiadomość
na WhatsAppie. Dwie ceny za jedno auto to nie jest rozbieżność do wyjaśnienia w rozmowie,
tylko podważona wiarygodność całej oferty.

Teraz wszystko liczy `pricing/import_calculator.py`, a ten moduł tylko rozkłada wynik na
pozycje, których oczekują szablony Jinja2. Nie ma tu żadnej własnej arytmetyki podatkowej.

Ścieżka kosztów w arkuszu (prywatnie): zakup + opłata aukcyjna + transport z placu
+ załadunek + fracht → odprawa w Niemczech (cło, VAT niemiecki, obsługa) → transport
DE→PL → akcyza w Polsce. Rejestracji, homologacji ani naprawy arkusz nie liczy, więc nie
ma ich w kwocie — a nie da się ich dopisać "na oko", bo to właśnie one robiły różnicę.
"""
from __future__ import annotations

from typing import Optional

from pricing import fx as _fx
from pricing.import_calculator import (
    CLEARANCE_DE_PLN,
    CUSTOMS_DUTY_RATE,
    DE_VAT_RATE,
    PL_VAT_RATE,
    TRANSPORT_COMPANY_PLN,
    TRANSPORT_PRIVATE_PLN,
    calculate_import_costs,
    client_price_pln,
    excise_rate_for,
    state_median_towing,
    towing_for_location,
)


def calculate_full_cost(
    bid_usd: float,
    engine_liters: Optional[float] = None,
    location_state: Optional[str] = None,
    repair_estimate_usd: Optional[float] = None,
    *,
    location_city: Optional[str] = None,
    settlement: str = "private",
    fee_tier: str = "basic",
    electric: bool = False,
    lot: Optional[object] = None,
) -> dict:
    """Pełny koszt sprowadzenia auta rozbity na pozycje do szablonu.

    `grand_total_pln` to cena dla klienta: sprowadzenie plus prowizja. Naprawa stoi
    OBOK sumy, nie w niej — szacunek AI nie jest kosztem, który ktokolwiek zafakturuje,
    a wliczony po cichu rozjeżdżałby raport z ofertą.

    Podaj `lot`, jeśli go masz. Wtedy cło i akcyza wychodzą z danych auta — kraju montażu
    z VIN-u i rodzaju napędu — zamiast z domyślnych stawek. Bez lota liczymy zachowawczo
    (cło 10%), bo to samo robi `landed_cost_pln`, a te dwie ścieżki muszą podawać
    identyczną kwotę: raport per lot i mail ofertowy opisują to samo auto.
    """
    bid = max(0.0, float(bid_usd or 0))
    towing = (
        towing_for_location(location_state, location_city)
        if location_city
        else state_median_towing(location_state)
    )

    rates = None
    if lot is not None:
        from pricing.tariff import rates_for_lot

        rates = rates_for_lot(lot)

    if rates is not None:
        excise_rate = rates.excise_rate
        duty_rate = rates.duty_rate
    else:
        excise_rate = excise_rate_for(engine_liters, electric=electric)
        duty_rate = CUSTOMS_DUTY_RATE

    costs = calculate_import_costs(
        bid_usd=bid,
        towing_usd=towing,
        excise_rate=excise_rate,
        duty_rate=duty_rate,
        usd_rate=_fx.current_rate(),
    )

    rate = float(costs["usd_rate"])
    private = settlement == "private"
    duty_pln = costs["private_duty_pln"] if private else costs["company_duty_pln"]
    excise_pln = costs["private_excise_pln"] if private else costs["company_excise_pln"]
    # Prywatnie VAT płacimy w Niemczech (21%), firmowo w Polsce (23%) od całości.
    vat_pln = costs["private_vat_de_pln"] if private else (costs["company_net_pln"] * PL_VAT_RATE)
    vat_pct = round((DE_VAT_RATE if private else PL_VAT_RATE) * 100)
    customs_base_pln = costs["private_customs_base_pln"] if private else costs["usa_total_pln"]
    transport_pl_pln = TRANSPORT_PRIVATE_PLN if private else TRANSPORT_COMPANY_PLN

    landed_pln = float(costs["private_total_pln" if private else "company_gross_pln"])
    fee_pln = float(costs["broker_basic_gross_pln" if fee_tier == "basic" else "broker_premium_gross_pln"])
    total_pln = client_price_pln(costs, settlement=settlement, fee_tier=fee_tier)
    repair_pln = round(float(repair_estimate_usd or 0) * rate)

    return {
        # USA
        "bid_usd": int(bid),
        "auction_fee_usd": int(costs["auction_fee_usd"]),
        "towing_usd": int(costs["towing_usd"]),
        "loading_usd": int(costs["loading_usd"]),
        "freight_usd": int(costs["freight_usd"]),
        "additional_usd": int(costs["additional_costs_usd"]),
        "usa_total_usd": int(costs["usa_total_usd"]),
        "usa_total_pln": int(costs["usa_total_pln"]),
        # Odprawa i podatki
        "customs_base_pln": int(customs_base_pln),
        "duty_pln": int(duty_pln),
        "duty_pct": round(duty_rate * 100),
        "vat_pln": int(vat_pln),
        "vat_pct": vat_pct,
        "vat_where": "DE" if private else "PL",
        "clearance_de_pln": int(CLEARANCE_DE_PLN),
        "transport_pl_pln": int(transport_pl_pln),
        "excise_pln": int(excise_pln),
        "excise_pct": round(excise_rate * 100, 1),
        # Suma
        "landed_pln": int(landed_pln),
        "broker_fee_pln": int(fee_pln),
        "fee_tier": fee_tier,
        "settlement": settlement,
        "grand_total_pln": int(round(total_pln)),
        "grand_total_usd": int(round(total_pln / rate)) if rate else 0,
        # Poza ceną
        "repair_usd": int(float(repair_estimate_usd or 0)),
        "repair_pln": int(repair_pln),
        # Meta
        "usd_pln": round(rate, 2),
        "engine_liters_assumed": engine_liters,
    }
