"""
Renders client_report.html.j2 and broker_report.html.j2 from AnalyzedLot data.
"""
import os
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from parser.models import AnalyzedLot, ClientCriteria
from pricing.import_calculator import (
    calculate_lot_import_costs,
    format_pln,
    format_usd,
    DEFAULT_USD_RATE,
    DEFAULT_EXCISE_RATE,
    AUCTION_FEE_RATE,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
)


def _t(value) -> str:
    if value is None or value == "":
        return "brak danych"
    return str(value)


def _mileage(value) -> str:
    if value is None:
        return "brak danych"
    try:
        return f"{int(value):,} mi".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _damage_str(lot) -> str:
    parts = [lot.damage_primary, lot.damage_secondary]
    return " + ".join(p for p in parts if p) or "brak danych"


def _location_str(lot) -> str:
    return ", ".join(p for p in [lot.location_city, lot.location_state] if p) or "brak danych"


def _engine_str(lot) -> str:
    parts = [lot.trim]
    return " ".join(p for p in parts if p) or ""


def _recommendation_css(recommendation: str) -> str:
    mapping = {
        "POLECAM": "polecam",
        "RYZYKO": "obserwuj",
        "ODRZUĆ": "odrzuc",
    }
    return mapping.get(recommendation, "obserwuj")


def _pill_style_for_score(score: float) -> str:
    if score >= 7:
        return "ok"
    if score >= 5:
        return "amber"
    return "blue"


def _build_pills(item: AnalyzedLot) -> list[dict]:
    lot = item.lot
    ai = item.analysis
    pills = []

    if ai.recommendation == "POLECAM":
        pills.append({"text": f"Wynik AI: {ai.score:.1f}/10", "style": "ok"})
    elif ai.recommendation == "RYZYKO":
        pills.append({"text": f"Wynik AI: {ai.score:.1f}/10", "style": "amber"})
    else:
        pills.append({"text": f"Wynik AI: {ai.score:.1f}/10", "style": "blue"})

    if lot.title_type:
        pills.append({"text": lot.title_type, "style": "blue"})

    if lot.keys is True:
        pills.append({"text": "Kluczyki", "style": "ok"})
    elif lot.keys is False:
        pills.append({"text": "Brak kluczyków", "style": "amber"})

    if lot.odometer_mi:
        pills.append({"text": _mileage(lot.odometer_mi), "style": "blue"})

    if lot.location_state:
        pills.append({"text": lot.location_state, "style": "blue"})

    return pills


def _build_spec_rows(item: AnalyzedLot) -> list[dict]:
    lot = item.lot
    rows = []

    if lot.odometer_mi:
        rows.append({
            "feature": f"Przebieg {_mileage(lot.odometer_mi)}",
            "benefit": "Znany rzeczywisty stan licznika z rynku USA",
        })

    if lot.damage_primary:
        rows.append({
            "feature": f"Uszkodzenie: {lot.damage_primary}",
            "benefit": "Konkretny zakres naprawy, bez ukrytych niespodzianek",
        })

    if lot.title_type:
        rows.append({
            "feature": f"Tytuł: {lot.title_type}",
            "benefit": "Znany status prawny pojazdu przed zakupem",
        })

    if lot.keys is True:
        rows.append({
            "feature": "Kluczyki obecne",
            "benefit": "Brak dodatkowych kosztów dorabiania kluczyków",
        })

    if lot.seller_type == "insurance":
        rows.append({
            "feature": "Sprzedawca: ubezpieczalnia",
            "benefit": "Pewna historia dokumentacyjna, brak ukrytych zastawów",
        })

    if lot.location_state:
        rows.append({
            "feature": f"Lokalizacja: {_location_str(lot)}",
            "benefit": "Znany koszt transportu do portu",
        })

    return rows


def _build_damage_ok_items(item: AnalyzedLot) -> list[dict]:
    lot = item.lot
    ok_items = []

    if lot.airbags_deployed is False:
        ok_items.append({
            "title": "Poduszki nierozbite",
            "body": "Brak konieczności wymiany — oszczędność ok. $2 000–$4 000",
        })
    elif lot.airbags_deployed is True:
        pass

    if lot.keys is True:
        ok_items.append({
            "title": "Kluczyki w komplecie",
            "body": "Nie ma potrzeby dorabiania — pojazd gotowy do uruchomienia",
        })

    if lot.title_type and "salvage" not in lot.title_type.lower():
        ok_items.append({
            "title": "Tytuł do rejestracji",
            "body": f"{lot.title_type} — możliwa rejestracja po naprawie",
        })

    if not ok_items:
        ok_items.append({
            "title": "Weryfikacja po zakupie",
            "body": "Pełna ocena po przeglądzie technicznym w Polsce",
        })

    return ok_items


def _build_timeline_steps() -> list[dict]:
    return [
        {"day": "1", "day_label": "Dzień 1", "label": "Wygranie aukcji", "desc": "Potwierdzenie wyniku i wpłata depozytu aukcyjnego"},
        {"day": "7", "day_label": "Tydzień 1", "label": "Transport do portu", "desc": "Załadunek i wysyłka z USA (RORO lub kontener)"},
        {"day": "30", "day_label": "Miesiąc 1–2", "label": "Odprawa celna w DE/PL", "desc": "Dokumenty, VAT, cło, akcyza — przy Pana/Pani obecności lub zdalnie"},
        {"day": "45", "day_label": "Tydzień 6–8", "label": "Naprawa i homologacja", "desc": "Warsztat, badanie techniczne, rejestracja w Polsce"},
        {"day": "60", "day_label": "Miesiąc 2–3", "label": "Odbiór pojazdu", "desc": "Auto gotowe do jazdy — zarejestrowane w Polsce"},
    ]


def _build_docs_list() -> list[str]:
    return [
        "Tytuł własności (Title) z USA",
        "Bill of Sale z aukcji",
        "Dokumenty odprawy celnej",
        "Potwierdzenie akcyzy i VAT",
        "Protokół badania technicznego",
        "Karta pojazdu (PL)",
    ]


def _build_cost_rows(costs: dict) -> list[dict]:
    usd = costs.get("usa_total_usd", 0)
    rate = costs.get("usd_rate", DEFAULT_USD_RATE)
    optimistic_factor = 0.85
    pessimistic_factor = 1.15

    rows = [
        {
            "label": "Cena wylicytowana (bid)",
            "optimistic": format_usd(costs.get("bid_usd", 0) * optimistic_factor),
            "pessimistic": format_usd(costs.get("bid_usd", 0) * pessimistic_factor),
        },
        {
            "label": "Opłata aukcyjna (~8%)",
            "optimistic": format_usd(costs.get("auction_fee_usd", 0) * optimistic_factor),
            "pessimistic": format_usd(costs.get("auction_fee_usd", 0) * pessimistic_factor),
        },
        {
            "label": "Transport lokalny (towing)",
            "optimistic": format_usd(costs.get("towing_usd", 0) * optimistic_factor),
            "pessimistic": format_usd(costs.get("towing_usd", 0) * pessimistic_factor),
        },
        {
            "label": "Załadunek + fracht morski",
            "optimistic": format_usd((costs.get("loading_usd", 560) + costs.get("freight_usd", 1050)) * optimistic_factor),
            "pessimistic": format_usd((costs.get("loading_usd", 560) + costs.get("freight_usd", 1050)) * pessimistic_factor),
        },
        {
            "label": "Cło + VAT DE + odprawa",
            "optimistic": format_pln(costs.get("private_de_fees_pln", 0) * optimistic_factor),
            "pessimistic": format_pln(costs.get("private_de_fees_pln", 0) * pessimistic_factor),
        },
        {
            "label": "Akcyza PL (3,1%)",
            "optimistic": format_pln(costs.get("private_excise_pln", 0) * optimistic_factor),
            "pessimistic": format_pln(costs.get("private_excise_pln", 0) * pessimistic_factor),
        },
    ]
    return rows


def _build_scoring_criteria(item: AnalyzedLot, costs: Optional[dict]) -> list[dict]:
    lot = item.lot
    ai = item.analysis
    rows = []

    if lot.location_state:
        eastern = {"NY", "NJ", "PA", "CT", "MA", "MD", "VA", "NC", "SC", "GA", "FL", "OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "KY", "TN", "AL", "MS"}
        western = {"CA", "WA", "OR", "NV", "AZ", "CO", "UT", "ID", "MT", "WY", "NM", "AK", "HI"}
        if lot.location_state in eastern:
            rows.append({"name": "Lokalizacja (Wschód USA)", "delta": "+1.5", "justification": "Niższy koszt transportu do portu"})
        elif lot.location_state in western:
            rows.append({"name": "Lokalizacja (Zachód USA)", "delta": "−1.0", "justification": "Wyższy koszt transportu do portu"})

    if lot.damage_primary:
        damage_lower = lot.damage_primary.lower()
        if any(w in damage_lower for w in ["flood", "fire", "burn"]):
            rows.append({"name": "Uszkodzenie krytyczne", "delta": "−3.0", "justification": "Automatyczne odrzucenie wg reguł"})
        elif any(w in damage_lower for w in ["front", "rear", "side"]):
            rows.append({"name": "Uszkodzenie karoserii", "delta": "−1.0", "justification": "Standardowa naprawa blacharsko-lakiernicza"})

    if lot.title_type:
        title_lower = lot.title_type.lower()
        if "salvage" in title_lower:
            rows.append({"name": "Tytuł Salvage", "delta": "−0.5", "justification": "Wymaga przerejestrowania w PL"})
        elif "clean" in title_lower:
            rows.append({"name": "Tytuł Clean", "delta": "+0.5", "justification": "Najprostszy import"})

    if lot.keys is True:
        rows.append({"name": "Kluczyki obecne", "delta": "+0.3", "justification": "Brak dodatkowych kosztów"})
    elif lot.keys is False:
        rows.append({"name": "Brak kluczyków", "delta": "−0.3", "justification": "Dodatkowy koszt dorabiania"})

    if lot.airbags_deployed is False:
        rows.append({"name": "Poduszki nierozbite", "delta": "+0.5", "justification": "Brak kosztownej wymiany"})
    elif lot.airbags_deployed is True:
        rows.append({"name": "Poduszki rozbite", "delta": "−1.0", "justification": "$2k–$4k dodatkowego kosztu"})

    rows.append({"name": "Wynik końcowy AI", "delta": f"{ai.score:.1f}/10", "justification": ai.recommendation})

    return rows


def _build_red_flags(item: AnalyzedLot) -> list[dict]:
    ai = item.analysis
    flags = []
    for flag in (ai.red_flags or []):
        flags.append({"level": "amber", "title": "Ryzyko", "description": flag})
    return flags


def _build_checklist(item: AnalyzedLot) -> list[dict]:
    lot = item.lot
    items = [
        {"action": "Sprawdź VIN w CarFax/AutoCheck", "prio_css": "red", "prio_label": "Wysoki"},
        {"action": "Weryfikacja tytułu własności (Title)", "prio_css": "red", "prio_label": "Wysoki"},
        {"action": "Przejrzyj zdjęcia wysokiej rozdzielczości", "prio_css": "red", "prio_label": "Wysoki"},
        {"action": "Potwierdź opłaty aukcyjne i storage", "prio_css": "amber", "prio_label": "Średni"},
        {"action": "Ustal limit bid przed aukcją", "prio_css": "amber", "prio_label": "Średni"},
        {"action": "Zweryfikuj dostępność części zamiennych", "prio_css": "amber", "prio_label": "Średni"},
    ]
    if lot.airbags_deployed is None:
        items.append({"action": "Sprawdź stan poduszek SRS", "prio_css": "red", "prio_label": "Wysoki"})
    if not lot.keys:
        items.append({"action": "Wycena dorobienia kluczyków", "prio_css": "amber", "prio_label": "Średni"})
    return items


def _build_notes(item: AnalyzedLot) -> dict:
    lot = item.lot
    ai = item.analysis
    name = f"{lot.year} {lot.make} {lot.model}"

    return {
        "offer_mode": "Oferta importu z aukcji USA",
        "main_trigger": ai.client_description_pl or f"Wyjątkowa okazja na {name} z aukcji USA",
        "headline_a": f"{name} z USA — transparentny import pod klucz",
        "headline_b": f"Oszczędź vs. rynek PL — {name} prosto z aukcji ubezpieczeniowej",
        "headline_c": f"Konkretna kalkulacja kosztów zamiast domysłów — {name}",
        "communication_risks": "Klient może obawiać się ukrytych kosztów i formalności — zaadresuj to w pierwszej wiadomości",
        "followup_48h": f"Aukcja {lot.auction_date or 'wkrótce'} — potrzebuję potwierdzenia limitu bidu do 24h przed końcem",
        "short_whatsapp": f"{name}, wynik AI {ai.score:.0f}/10. Warto? Mam pełną kalkulację.",
        "damaging_admission": "To auto ma uszkodzenia karoserii — piszę o tym otwarcie, bo ukrywanie tego nie ma sensu",
    }


def build_client_context(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None) -> dict:
    lot = item.lot
    ai = item.analysis
    costs = calculate_lot_import_costs(lot)

    total_cost_pln = format_pln(costs["private_total_pln"]) if costs else "brak danych"

    cta_headline = f"Zainteresowany tym {lot.make} {lot.model}?"
    cta_body = (
        "Odpiszcie do mnie — ustalimy limit licytacji, kalkulację importu "
        "i harmonogram. Aukcja jest konkretna, terminy napięte."
    )

    return {
        "make": _t(lot.make),
        "model": _t(lot.model),
        "year": _t(lot.year),
        "trim": lot.trim or "",
        "engine_str": _engine_str(lot),
        "hp": None,
        "drive": None,
        "location_state": lot.location_state or "",
        "auction_date": lot.auction_date or "",
        "pills": _build_pills(item),
        "photo_url": lot.images[0] if lot.images else None,
        "headline_text": ai.client_description_pl or f"Sprawdzony {lot.year} {lot.make} {lot.model} z aukcji USA",
        "subhead_text": f"Szacowany koszt w Polsce: {total_cost_pln}",
        "story_paragraphs": [
            ai.client_description_pl or f"Ten {lot.year} {lot.make} {lot.model} pochodzi z aukcji ubezpieczeniowej w USA.",
            f"Pojazd znajdował się w {_location_str(lot)}. "
            f"Uszkodzenie: {_damage_str(lot)}. "
            f"Przebieg: {_mileage(lot.odometer_mi)}.",
            "Każde auto przechodzi przez naszą analizę przed wysłaniem oferty. "
            "Podajemy tylko realne koszty — bez ukrytych opłat.",
        ],
        "spec_rows": _build_spec_rows(item),
        "damage_what": _damage_str(lot),
        "damage_repair": f"Szacowany koszt naprawy: {format_usd(ai.estimated_repair_usd)}" if ai.estimated_repair_usd else "Do wyceny po inspekcji",
        "damage_ok_items": _build_damage_ok_items(item),
        "timeline_steps": _build_timeline_steps(),
        "docs_list": _build_docs_list(),
        "cta_headline": cta_headline,
        "cta_body": cta_body,
        "auction_deadline": lot.auction_date or "",
        "scarcity_note": "Aukcja niepowtarzalna — każdy pojazd licytowany jest tylko raz",
        "vin": lot.vin or lot.full_vin or "",
        "lot_id": lot.lot_id,
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }


def build_broker_context(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None, lots_scanned: int = 0) -> dict:
    lot = item.lot
    ai = item.analysis
    costs = calculate_lot_import_costs(lot)

    bid = lot.current_bid_usd or lot.buy_now_price_usd or 0
    repair = ai.estimated_repair_usd or 0
    acv_usd = bid + repair

    criteria_summary = ""
    if criteria:
        parts = [criteria.make, criteria.model or ""]
        if criteria.year_from:
            parts.append(f"od {criteria.year_from}")
        if criteria.year_to:
            parts.append(f"do {criteria.year_to}")
        parts.append(f"budżet ${criteria.budget_usd:,.0f}")
        criteria_summary = " ".join(p for p in parts if p)

    cost_rows = _build_cost_rows(costs) if costs else []

    total_opt_usd = costs["usa_total_usd"] * 0.85 if costs else None
    total_pes_usd = costs["usa_total_usd"] * 1.15 if costs else None
    total_opt_pln = costs["private_total_pln"] * 0.85 if costs else None
    total_pes_pln = costs["private_total_pln"] * 1.15 if costs else None

    reserve = lot.seller_reserve_usd
    bid_breakeven = acv_usd * 0.6 if acv_usd else None
    bid_max = acv_usd * 0.55 if acv_usd else None

    raw_fields = [
        {"key": "source", "value": lot.source},
        {"key": "lot_id", "value": lot.lot_id},
        {"key": "vin", "value": lot.vin or ""},
        {"key": "full_vin", "value": lot.full_vin or ""},
        {"key": "year", "value": str(lot.year or "")},
        {"key": "make", "value": lot.make or ""},
        {"key": "model", "value": lot.model or ""},
        {"key": "trim", "value": lot.trim or ""},
        {"key": "odometer_mi", "value": str(lot.odometer_mi or "")},
        {"key": "damage_primary", "value": lot.damage_primary or ""},
        {"key": "damage_secondary", "value": lot.damage_secondary or ""},
        {"key": "title_type", "value": lot.title_type or ""},
        {"key": "current_bid_usd", "value": format_usd(lot.current_bid_usd)},
        {"key": "buy_now_price_usd", "value": format_usd(lot.buy_now_price_usd)},
        {"key": "seller_reserve_usd", "value": format_usd(lot.seller_reserve_usd)},
        {"key": "seller_type", "value": lot.seller_type or ""},
        {"key": "location_state", "value": lot.location_state or ""},
        {"key": "location_city", "value": lot.location_city or ""},
        {"key": "auction_date", "value": lot.auction_date or ""},
        {"key": "keys", "value": str(lot.keys)},
        {"key": "airbags_deployed", "value": str(lot.airbags_deployed)},
        {"key": "enriched_by_extension", "value": str(lot.enriched_by_extension)},
    ]

    pipeline_rules = [
        "seller_type: insurance",
        f"auction window: {criteria.year_from or '?'}–{criteria.year_to or '?'} rok",
        "damage priority: najmniejsze widoczne uszkodzenia",
        "details: otwierane tylko dla kandydatów po filtrach listy",
    ] if criteria else ["Brak kryteriów wyszukiwania"]

    excluded_damage = ", ".join(criteria.excluded_damage_types) if criteria and criteria.excluded_damage_types else "Flood, Fire"
    sources_str = ", ".join(criteria.sources).upper() if criteria and criteria.sources else "COPART, IAAI"

    return {
        "make": _t(lot.make),
        "model": _t(lot.model),
        "year": _t(lot.year),
        "trim": lot.trim or "",
        "lot_id": lot.lot_id,
        "source": (lot.source or "").upper(),
        "url": lot.url or "",
        "location_city": lot.location_city or "",
        "location_state": lot.location_state or "",
        "vin": lot.vin or "",
        "full_vin": lot.full_vin or "",
        "recommendation": ai.recommendation,
        "recommendation_css": _recommendation_css(ai.recommendation),
        "score": f"{ai.score:.1f}",
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "criteria_summary": criteria_summary or "Brak kryteriów",
        "sources_str": sources_str,
        "excluded_damage": excluded_damage,
        "lots_scanned": lots_scanned,
        "damage_score": _damage_str(lot),
        "acv_usd": format_usd(acv_usd) if acv_usd else "brak danych",
        "cost_optimistic_usd": format_usd(total_opt_usd),
        "cost_pessimistic_usd": format_usd(total_pes_usd),
        "criteria": criteria,
        "pipeline_rules": pipeline_rules,
        "lot_raw_fields": [f for f in raw_fields if f["value"]],
        "scoring_criteria": _build_scoring_criteria(item, costs),
        "cost_rows": cost_rows,
        "cost_total_optimistic_usd": format_usd(total_opt_usd),
        "cost_total_pessimistic_usd": format_usd(total_pes_usd),
        "cost_total_optimistic_pln": format_pln(total_opt_pln),
        "cost_total_pessimistic_pln": format_pln(total_pes_pln),
        "usd_pln_rate": str(costs.get("usd_rate", DEFAULT_USD_RATE)) if costs else str(DEFAULT_USD_RATE),
        "red_flags": _build_red_flags(item),
        "raw_api_fields": raw_fields,
        "bid_max_suggested": format_usd(bid_max),
        "bid_breakeven": format_usd(bid_breakeven),
        "bid_acv_warning": f"ACV szacowane na {format_usd(acv_usd)}" if acv_usd else "",
        "bid_reserve_note": f"Reserve: {format_usd(reserve)}" if reserve else "Reserve nieznany",
        "bid_last_ask_note": f"Ostatnia oferta: {format_usd(lot.current_bid_usd)}" if lot.current_bid_usd else "",
        "bid_recommendation": ai.ai_notes or "Ustal limit przed aukcją na podstawie pełnej kalkulacji",
        "checklist_items": _build_checklist(item),
        "notes": _build_notes(item),
        "ai_notes": ai.ai_notes or "",
        "client_description_pl": ai.client_description_pl or "",
        "red_flags_raw": ai.red_flags or [],
        "estimated_repair_usd": format_usd(ai.estimated_repair_usd),
        "estimated_total_cost_usd": format_usd(ai.estimated_total_cost_usd),
    }


def render_client_report(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None) -> str:
    ctx = build_client_context(item, criteria)
    tmpl = _jinja_env.get_template("client_report.html.j2")
    return tmpl.render(**ctx)


def render_broker_report(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None, lots_scanned: int = 0) -> str:
    ctx = build_broker_context(item, criteria, lots_scanned=lots_scanned)
    tmpl = _jinja_env.get_template("broker_report.html.j2")
    return tmpl.render(**ctx)
