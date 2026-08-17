import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

# Akcyza: 3,1% do 2000 cm³, 18,6% powyżej, 0% dla elektryków. Silnik "2.0" ma w praktyce
# 1984-1998 cm³, więc mieści się w niższej stawce — próg stawiamy POWYŻEJ 2,0 l.
EXCISE_SMALL = 0.031
EXCISE_LARGE = 0.186
EXCISE_EV = 0.0

_ENGINE_LITERS_RE = re.compile(r"(\d[.,]\d)\s*[lt]?\b", re.IGNORECASE)


DEFAULT_ADDITIONAL_COSTS_USD = 300
DEFAULT_LOADING_USD = 560
DEFAULT_FREIGHT_USD = 1050
DEFAULT_USD_RATE = 4
DEFAULT_EXCISE_RATE = 0.031

AUCTION_FEE_RATE = 0.08
SERVICE_INSURANCE_RATE = 0.02
PRIVATE_CUSTOMS_BASE_RATE = 0.4
FIXED_EXCISE_BASE_USD = 550
CUSTOMS_DUTY_RATE = 0.1
DE_VAT_RATE = 0.21
PL_VAT_RATE = 0.23
CLEARANCE_DE_PLN = 3000
TRANSPORT_PRIVATE_PLN = 2500
TRANSPORT_COMPANY_PLN = 2100

BROKER_BASIC_BASE_PLN = 1800
BROKER_BASIC_RATE = 0.02
BROKER_PREMIUM_BASE_PLN = 3600
BROKER_PREMIUM_RATE = 0.04
EMPLOYEE_BASIC_SHARE = 0.4
EMPLOYEE_PREMIUM_SHARE = 0.3
EMPLOYEE_TOPUP_SHARE = 0.2
EMPLOYEE_FIXED_PLN = 150


# Która pozycja kalkulatora jest kosztem sprowadzenia dla danej formy zakupu.
SETTLEMENT_TOTAL_KEY: dict[str, str] = {
    "private": "private_total_pln",
    "company": "company_gross_pln",
}

# Prowizja brokera brutto w dwóch wariantach obsługi.
BROKER_FEE_KEY: dict[str, str] = {
    "basic": "broker_basic_gross_pln",
    "premium": "broker_premium_gross_pln",
}


def engine_liters_from_trim(*sources: Optional[str]) -> Optional[float]:
    """Pojemność silnika z wersji wyposażenia ('3.0 TDI', '2.0T'). None = nie wiemy."""
    for source in sources:
        if not source:
            continue
        match = _ENGINE_LITERS_RE.search(source)
        if not match:
            continue
        try:
            value = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        if 0.8 <= value <= 8.5:
            return value
    return None


def excise_rate_for(engine_liters: Optional[float], *, electric: bool = False) -> float:
    """Stawka akcyzy dla auta o tej pojemności.

    Przy nieznanej pojemności bierzemy stawkę wyższą. W aukcjach z USA silnik poniżej
    2,0 l to wyjątek, a pomyłka w drugą stronę zaniża cenę klienta o ~5 000 zł przy
    locie za 10 000 USD — czyli o kwotę, którą ktoś musiałby dopłacić po fakcie.
    """
    if electric:
        return EXCISE_EV
    if engine_liters is not None and engine_liters <= 2.0:
        return EXCISE_SMALL
    return EXCISE_LARGE


def client_price_pln(
    costs: dict[str, float],
    *,
    settlement: str = "private",
    fee_tier: str = "basic",
) -> float:
    """Kwota, którą zapłaci klient: sprowadzenie plus nasza prowizja.

    Jedyna definicja ceny końcowej w całym systemie. Liczą z niej: sufit budżetu
    (scoring/budget.py), wiadomość WhatsApp, mail ofertowy i raport per lot — żeby
    klient nigdy nie zobaczył dwóch różnych kwot za to samo auto.

    private_total_pln / company_gross_pln to KOSZT SPROWADZENIA, nie cena sprzedaży.
    Pokazanie go jako "pod drzwi" zaniża ofertę o wysokość prowizji, czyli o 2 800-4 200 zł
    w typowym zakresie cen.
    """
    return float(costs[SETTLEMENT_TOTAL_KEY[settlement]]) + float(costs[BROKER_FEE_KEY[fee_tier]])


def _static_calculator_data_path() -> Path:
    return Path(__file__).resolve().parent.parent / "api" / "static" / "calculator-data.js"


@lru_cache(maxsize=1)
def towing_locations() -> list[dict[str, Any]]:
    """Load the generated towing table used by the browser calculator."""
    path = _static_calculator_data_path()
    text = path.read_text(encoding="utf-8")
    match = re.search(r"window\.TOWING_LOCATIONS\s*=\s*(\[.*\]);", text, re.S)
    if not match:
        return []
    return json.loads(match.group(1))


def state_median_towing(state: Optional[str]) -> int:
    values = sorted(
        int(item["towingUsd"])
        for item in towing_locations()
        if item.get("state") == state
    )
    if not values:
        return 1000
    return values[len(values) // 2]


def towing_for_location(state: Optional[str], city: Optional[str]) -> int:
    if not state:
        return 1000

    if city:
        city_normalized = city.strip().upper()
        for item in towing_locations():
            if item.get("state") == state and item.get("city", "").strip().upper() == city_normalized:
                return int(item["towingUsd"])

    return state_median_towing(state)


def calculate_import_costs(
    *,
    bid_usd: float,
    additional_costs_usd: float = DEFAULT_ADDITIONAL_COSTS_USD,
    towing_usd: float = 1000,
    loading_usd: float = DEFAULT_LOADING_USD,
    freight_usd: float = DEFAULT_FREIGHT_USD,
    usd_rate: float = DEFAULT_USD_RATE,
    excise_rate: float = DEFAULT_EXCISE_RATE,
    duty_rate: float = CUSTOMS_DUTY_RATE,
    topup_pln: float = 0,
) -> dict[str, float]:
    """Czysta arytmetyka importu. Stawki przychodzą z zewnątrz.

    `duty_rate` jest parametrem od sierpnia 2026, bo cło przestało być stałą: auta
    zmontowane w USA mają 0% (rozporządzenie UE 2026/1455), reszta nadal 10%. Który
    wariant dotyczy konkretnego auta, rozstrzyga `pricing/tariff.py` — tutaj wchodzi
    już gotowa liczba, żeby wzory dały się testować bez znajomości przepisów.

    Domyślne 10% jest celowo zachowawcze: wywołanie bez podanej stawki liczy drożej,
    więc pominięcie parametru w nowym kodzie zawyży wycenę, zamiast ją po cichu zaniżyć.
    """
    auction_fee_usd = bid_usd * AUCTION_FEE_RATE
    usa_total_usd = (
        additional_costs_usd
        + bid_usd
        + auction_fee_usd
        + towing_usd
        + loading_usd
        + freight_usd
    )
    usa_total_pln = usa_total_usd * usd_rate

    service_insurance_usd = usa_total_usd * SERVICE_INSURANCE_RATE
    claim_service_usd = service_insurance_usd / 2

    private_customs_base_pln = (usa_total_pln * PRIVATE_CUSTOMS_BASE_RATE) + (FIXED_EXCISE_BASE_USD * usd_rate)
    private_duty_pln = private_customs_base_pln * duty_rate
    private_vat_de_pln = (private_customs_base_pln + private_duty_pln) * DE_VAT_RATE
    private_de_fees_pln = CLEARANCE_DE_PLN + private_duty_pln + private_vat_de_pln + TRANSPORT_PRIVATE_PLN
    private_before_excise_pln = usa_total_pln + private_de_fees_pln
    private_excise_pln = (private_before_excise_pln * 0.5) * excise_rate
    private_total_pln = private_before_excise_pln + private_excise_pln

    company_duty_pln = usa_total_pln * duty_rate
    company_de_fees_pln = CLEARANCE_DE_PLN + company_duty_pln
    company_excise_pln = ((bid_usd + FIXED_EXCISE_BASE_USD) * usd_rate) * excise_rate
    company_net_pln = usa_total_pln + company_de_fees_pln + company_excise_pln
    company_gross_pln = (company_net_pln * (1 + PL_VAT_RATE)) + TRANSPORT_COMPANY_PLN

    broker_basic_net_pln = (bid_usd * BROKER_BASIC_RATE * usd_rate) + BROKER_BASIC_BASE_PLN
    broker_premium_net_pln = (bid_usd * BROKER_PREMIUM_RATE * usd_rate) + BROKER_PREMIUM_BASE_PLN
    broker_basic_gross_pln = broker_basic_net_pln * (1 + PL_VAT_RATE)
    broker_premium_gross_pln = broker_premium_net_pln * (1 + PL_VAT_RATE)
    employee_basic_pln = (
        broker_basic_net_pln * EMPLOYEE_BASIC_SHARE
        + topup_pln * EMPLOYEE_TOPUP_SHARE
        + EMPLOYEE_FIXED_PLN
    )
    employee_premium_pln = (
        broker_premium_net_pln * EMPLOYEE_PREMIUM_SHARE
        + topup_pln * EMPLOYEE_TOPUP_SHARE
    )

    return {
        "bid_usd": bid_usd,
        "additional_costs_usd": additional_costs_usd,
        "towing_usd": towing_usd,
        "loading_usd": loading_usd,
        "freight_usd": freight_usd,
        "usd_rate": usd_rate,
        "excise_rate": excise_rate,
        "duty_rate": duty_rate,
        "auction_fee_usd": auction_fee_usd,
        "usa_total_usd": usa_total_usd,
        "usa_total_pln": usa_total_pln,
        "service_insurance_usd": service_insurance_usd,
        "claim_service_usd": claim_service_usd,
        "service_insurance_total_usd": service_insurance_usd + claim_service_usd,
        "private_customs_base_pln": private_customs_base_pln,
        "private_duty_pln": private_duty_pln,
        "private_vat_de_pln": private_vat_de_pln,
        "private_de_fees_pln": private_de_fees_pln,
        "private_before_excise_pln": private_before_excise_pln,
        "private_excise_pln": private_excise_pln,
        "private_total_pln": private_total_pln,
        "company_duty_pln": company_duty_pln,
        "company_de_fees_pln": company_de_fees_pln,
        "company_excise_pln": company_excise_pln,
        "company_net_pln": company_net_pln,
        "company_gross_pln": company_gross_pln,
        "broker_basic_net_pln": broker_basic_net_pln,
        "broker_basic_gross_pln": broker_basic_gross_pln,
        "broker_premium_net_pln": broker_premium_net_pln,
        "broker_premium_gross_pln": broker_premium_gross_pln,
        "employee_basic_pln": employee_basic_pln,
        "employee_premium_pln": employee_premium_pln,
    }


def calculate_lot_import_costs(
    lot: Any,
    *,
    excise_rate: Optional[float] = None,
    duty_rate: Optional[float] = None,
    usd_rate: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Koszty importu konkretnego lota — ze stawkami wyprowadzonymi z jego danych.

    To jest wąskie gardło całej aplikacji: liczą z niego raporty, mail ofertowy,
    wiadomość WhatsApp i artefakty klienta. Dlatego stawki wybierane są tutaj, raz,
    a nie w każdym z tych miejsc osobno — inaczej klient zobaczyłby dwie różne kwoty
    za to samo auto, zależnie od tego, którym kanałem przyszła.

    Wyprowadzamy trzy rzeczy, których wcześniej nie było:

      * cło — 0% dla aut zmontowanych w USA, 10% dla reszty i dla elektryków
        (`pricing/tariff.py`, kraj montażu z pierwszego znaku VIN-u),
      * akcyzę — z uwzględnieniem stawek hybrydowych 1,55% i 9,3%,
      * kurs dolara — z NBP z narzutem, zamiast wpisanych na sztywno 4,00 zł.

    Każdy z tych parametrów da się nadpisać. Jawnie podana stawka wygrywa z wyliczoną,
    bo broker, który sprawdził VIN u agencji celnej, wie więcej niż nasz parser.

    Zwracany słownik niesie dodatkowo `duty_reason`, `excise_reason` i `pricing_assumptions`
    — to materiał do briefu brokera, nie do oferty klienta.
    """
    bid_usd = lot.current_bid_usd or lot.buy_now_price_usd
    if not bid_usd:
        return None

    # Import lokalny: tariff sięga po engine_liters_from_trim z tego modułu, więc
    # zależność na poziomie modułu zamknęłaby cykl.
    from pricing import fx
    from pricing.tariff import rates_for_lot

    rates = rates_for_lot(lot)
    rate_info = fx.usd_rate() if usd_rate is None else None

    towing_usd = towing_for_location(lot.location_state, lot.location_city)
    costs = calculate_import_costs(
        bid_usd=float(bid_usd),
        towing_usd=towing_usd,
        excise_rate=rates.excise_rate if excise_rate is None else excise_rate,
        duty_rate=rates.duty_rate if duty_rate is None else duty_rate,
        usd_rate=rate_info.rate if rate_info is not None else float(usd_rate),
    )

    costs["duty_reason"] = rates.duty_reason
    costs["excise_reason"] = rates.excise_reason
    costs["drivetrain"] = rates.drivetrain.value
    costs["assembly_country"] = rates.country_name
    costs["pricing_assumptions"] = list(rates.assumptions)
    costs["fx_source"] = rate_info.summary() if rate_info is not None else "kurs podany jawnie"
    return costs


def format_usd(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"${round(value):,}".replace(",", " ")


def format_pln(value: Optional[float]) -> str:
    if value is None:
        return "—"
    # „zł", nie „PLN". Kod waluty jest z faktury i z tabeli kursowej; człowiek
    # czytający ofertę widzi w nim ślad tłumaczenia.
    return f"{round(value):,} zł".replace(",", " ")


def format_percent(value: float) -> str:
    rounded = round(value * 100, 1)
    text = f"{rounded:.0f}" if rounded.is_integer() else f"{rounded:.1f}"
    return text.replace(".", ",") + "%"
