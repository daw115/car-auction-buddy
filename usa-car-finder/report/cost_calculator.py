"""Deterministyczny kalkulator kosztów importu auta z USA do Polski.

Eliminuje konieczność dawania LLM-owi tych liczb — wszystko liczymy w Pythonie
i wstawiamy w template Jinja2. LLM zajmuje się tylko storytellingiem.

Wartości referencyjne (2025/2026, można dostroić przez env):
- USD/PLN: ~4.05
- Auction fee Copart/IAAI: ~$600 + 10% bid (uproszczone)
- Transport USA dom→port: $400-800 (zal. od stanu)
- Ocean freight East Coast → Gdynia: ~$1100
- Cło UE (10% wartości CIF dla aut osobowych)
- Akcyza PL: 3.1% (silnik <2.0L) / 18.6% (silnik >=2.0L)
- VAT PL: 23% wartości (cło + akcyza włączone)
- Homologacja + tłumaczenia + rejestracja: ~3500 PLN
- Transport krajowy: ~800 PLN
"""
from __future__ import annotations

import os
from typing import Optional


def _f(env: str, default: float) -> float:
    try:
        return float(os.getenv(env, str(default)))
    except (TypeError, ValueError):
        return default


def _state_to_port_usd(state: Optional[str]) -> int:
    """Heurystyka: stan USA → koszt transportu lądowego w USD."""
    if not state:
        return 700
    east = {"NY", "NJ", "PA", "MD", "VA", "NC", "SC", "GA", "FL", "MA", "CT", "RI", "ME", "NH", "VT", "DE"}
    central = {"OH", "MI", "IN", "IL", "WI", "KY", "TN", "AL", "MS", "LA", "MO", "AR", "IA", "MN"}
    west = {"CA", "OR", "WA", "NV", "AZ", "UT", "ID", "MT", "WY", "CO", "NM"}
    s = state.upper()
    if s in east:
        return 500
    if s in central:
        return 750
    if s in west:
        return 1100
    return 800  # default mid


def calculate_full_cost(
    bid_usd: float,
    engine_liters: Optional[float] = 2.0,
    location_state: Optional[str] = None,
    repair_estimate_usd: Optional[float] = None,
) -> dict:
    """Liczy pełny koszt sprowadzenia auta do PL.

    Zwraca dict ze wszystkimi pozycjami w USD i PLN + suma. Można przekazać
    do template Jinja2 jako jeden obiekt.
    """
    usd_pln = _f("USD_PLN_RATE", 4.05)
    bid = max(0.0, float(bid_usd or 0))

    # 1. Koszty USA (USD)
    auction_fee_usd = round(_f("AUCTION_FEE_BASE_USD", 600) + bid * _f("AUCTION_FEE_PCT", 0.10), 0)
    transport_us_usd = _state_to_port_usd(location_state)
    ocean_freight_usd = _f("OCEAN_FREIGHT_USD", 1100)
    title_handling_usd = _f("TITLE_HANDLING_USD", 250)

    total_us_usd = bid + auction_fee_usd + transport_us_usd + ocean_freight_usd + title_handling_usd

    # 2. CIF (cło bazą) = bid + freight (uproszczenie, bez auction fee)
    cif_usd = bid + transport_us_usd + ocean_freight_usd
    cif_pln = cif_usd * usd_pln

    # 3. Cło 10% (UE, auta osobowe)
    duty_pct = _f("DUTY_PCT", 0.10)
    duty_pln = round(cif_pln * duty_pct, 0)

    # 4. Akcyza (3.1% silnik <2L, 18.6% >=2L)
    if engine_liters is None:
        engine_liters = 2.0
    excise_pct = _f("EXCISE_PCT_BIG", 0.186) if engine_liters >= 2.0 else _f("EXCISE_PCT_SMALL", 0.031)
    excise_base_pln = cif_pln + duty_pln
    excise_pln = round(excise_base_pln * excise_pct, 0)

    # 5. VAT 23% (na CIF + cło + akcyza)
    vat_pct = _f("VAT_PCT", 0.23)
    vat_base_pln = cif_pln + duty_pln + excise_pln
    vat_pln = round(vat_base_pln * vat_pct, 0)

    # 6. Koszty PL po dotarciu
    homologation_pln = _f("HOMOLOGATION_PLN", 1500)
    translation_pln = _f("TRANSLATION_PLN", 800)
    registration_pln = _f("REGISTRATION_PLN", 1200)
    transport_pl_pln = _f("TRANSPORT_PL_PLN", 800)

    total_pl_pln = duty_pln + excise_pln + vat_pln + homologation_pln + translation_pln + registration_pln + transport_pl_pln

    # 7. Total
    repair_pln = round(float(repair_estimate_usd or 0) * usd_pln, 0)
    grand_total_pln = round(total_us_usd * usd_pln + total_pl_pln + repair_pln, 0)
    grand_total_usd = round(grand_total_pln / usd_pln, 0)

    return {
        # USA
        "bid_usd": int(bid),
        "auction_fee_usd": int(auction_fee_usd),
        "transport_us_usd": int(transport_us_usd),
        "ocean_freight_usd": int(ocean_freight_usd),
        "title_handling_usd": int(title_handling_usd),
        "total_us_usd": int(total_us_usd),
        "total_us_pln": int(total_us_usd * usd_pln),
        # CIF
        "cif_usd": int(cif_usd),
        "cif_pln": int(cif_pln),
        # PL taxes & fees
        "duty_pln": int(duty_pln),
        "duty_pct": int(duty_pct * 100),
        "excise_pln": int(excise_pln),
        "excise_pct": round(excise_pct * 100, 1),
        "vat_pln": int(vat_pln),
        "vat_pct": int(vat_pct * 100),
        "homologation_pln": int(homologation_pln),
        "translation_pln": int(translation_pln),
        "registration_pln": int(registration_pln),
        "transport_pl_pln": int(transport_pl_pln),
        "total_pl_pln": int(total_pl_pln),
        # Repair (jeśli AI oszacowało)
        "repair_usd": int(float(repair_estimate_usd or 0)),
        "repair_pln": int(repair_pln),
        # Grand total
        "grand_total_pln": int(grand_total_pln),
        "grand_total_usd": int(grand_total_usd),
        # Meta
        "usd_pln": round(usd_pln, 2),
        "engine_liters_assumed": engine_liters,
    }
