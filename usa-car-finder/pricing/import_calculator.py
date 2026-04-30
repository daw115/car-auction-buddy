import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


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
    topup_pln: float = 0,
) -> dict[str, float]:
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
    private_duty_pln = private_customs_base_pln * CUSTOMS_DUTY_RATE
    private_vat_de_pln = (private_customs_base_pln + private_duty_pln) * DE_VAT_RATE
    private_de_fees_pln = CLEARANCE_DE_PLN + private_duty_pln + private_vat_de_pln + TRANSPORT_PRIVATE_PLN
    private_before_excise_pln = usa_total_pln + private_de_fees_pln
    private_excise_pln = (private_before_excise_pln * 0.5) * excise_rate
    private_total_pln = private_before_excise_pln + private_excise_pln

    company_duty_pln = usa_total_pln * CUSTOMS_DUTY_RATE
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


def calculate_lot_import_costs(lot: Any, *, excise_rate: float = DEFAULT_EXCISE_RATE) -> Optional[dict[str, float]]:
    bid_usd = lot.current_bid_usd or lot.buy_now_price_usd
    if not bid_usd:
        return None

    towing_usd = towing_for_location(lot.location_state, lot.location_city)
    return calculate_import_costs(
        bid_usd=float(bid_usd),
        towing_usd=towing_usd,
        excise_rate=excise_rate,
    )


def format_usd(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"${round(value):,}".replace(",", " ")


def format_pln(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{round(value):,} PLN".replace(",", " ")


def format_percent(value: float) -> str:
    rounded = round(value * 100, 1)
    text = f"{rounded:.0f}" if rounded.is_integer() else f"{rounded:.1f}"
    return text.replace(".", ",") + "%"
