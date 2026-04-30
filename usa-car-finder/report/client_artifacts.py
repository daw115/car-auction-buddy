import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from parser.models import AnalyzedLot, ClientCriteria
from pricing.import_calculator import calculate_lot_import_costs, format_pln, format_usd


def lot_title(item: AnalyzedLot) -> str:
    lot = item.lot
    return " ".join(
        str(part)
        for part in [lot.year, lot.make, lot.model, lot.trim]
        if part not in (None, "")
    ) or f"Lot {lot.lot_id}"


def safe_text(value) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def auction_price(item: AnalyzedLot) -> str:
    lot = item.lot
    if lot.current_bid_usd:
        return format_usd(lot.current_bid_usd)
    if lot.buy_now_price_usd:
        return f"Buy Now {format_usd(lot.buy_now_price_usd)}"
    return "-"


def total_cost_text(item: AnalyzedLot) -> str:
    try:
        costs = calculate_lot_import_costs(item.lot)
    except Exception:
        costs = None
    if not costs:
        return "-"
    return format_pln(costs["private_total_pln"])


def markdown_table(items: Iterable[AnalyzedLot]) -> list[str]:
    lines = [
        "| # | Auto | Aukcja | Score | Cena | Uszkodzenie | Lokalizacja | Koszt PL |",
        "|---|------|--------|-------|------|-------------|-------------|----------|",
    ]
    for index, item in enumerate(items, start=1):
        lot = item.lot
        title = lot_title(item).replace("|", "/")
        auction = f"{lot.source.upper()} {lot.lot_id}".replace("|", "/")
        damage = safe_text(lot.damage_primary).replace("|", "/")
        location = ", ".join(part for part in [lot.location_city, lot.location_state] if part) or "-"
        lines.append(
            "| {index} | {title} | {auction} | {score:.1f} | {price} | {damage} | {location} | {cost} |".format(
                index=index,
                title=title,
                auction=auction,
                score=item.analysis.score,
                price=auction_price(item),
                damage=damage,
                location=location.replace("|", "/"),
                cost=total_cost_text(item),
            )
        )
    return lines


def detail_section(item: AnalyzedLot, index: int) -> list[str]:
    lot = item.lot
    ai = item.analysis
    lines = [
        f"## {index}. {lot_title(item)}",
        "",
        f"- Źródło: {lot.source.upper()}",
        f"- Lot: {lot.lot_id}",
        f"- VIN: {safe_text(lot.full_vin or lot.vin)}",
        f"- Link: {lot.url}",
        f"- Aukcja: {safe_text(lot.auction_date)}",
        f"- Cena: {auction_price(item)}",
        f"- Seller type: {safe_text(lot.seller_type)}",
        f"- Damage: {safe_text(lot.damage_primary)} / {safe_text(lot.damage_secondary)}",
        f"- Tytuł: {safe_text(lot.title_type)}",
        f"- Przebieg: {safe_text(lot.odometer_mi)} mi",
        f"- Lokalizacja: {', '.join(part for part in [lot.location_city, lot.location_state] if part) or '-'}",
        f"- Szacowany koszt w PL: {total_cost_text(item)}",
        f"- Rekomendacja AI: {ai.recommendation}, score {ai.score:.1f}/10",
        "",
        "### Uzasadnienie",
        "",
        ai.client_description_pl.strip() or "-",
        "",
    ]
    if ai.red_flags:
        lines.extend(["### Ryzyka", ""])
        lines.extend(f"- {flag}" for flag in ai.red_flags)
        lines.append("")
    if ai.ai_notes:
        lines.extend(["### Notatki brokerskie", "", ai.ai_notes.strip(), ""])
    return lines


def write_client_artifacts(
    *,
    criteria: ClientCriteria,
    top_recommendations: list[AnalyzedLot],
    ranked_results: list[AnalyzedLot],
    output_dir: Path,
    slug: str,
) -> tuple[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().isoformat(timespec="seconds")

    analysis_path = (output_dir / f"{slug}_analysis.json").resolve()
    analysis_payload = {
        "generated_at": generated_at,
        "criteria": criteria.model_dump(mode="json"),
        "top_recommendations": [item.model_dump(mode="json") for item in top_recommendations],
        "ranked_results": [item.model_dump(mode="json") for item in ranked_results],
    }
    analysis_path.write_text(json.dumps(analysis_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = (output_dir / f"{slug}_client_report.md").resolve()
    lines = [
        "# Raport ofertowy USA Car Finder",
        "",
        f"Wygenerowano: {generated_at}",
        "",
        "## Kryteria klienta",
        "",
        f"- Marka/model: {criteria.make} {criteria.model or ''}".rstrip(),
        f"- Rocznik: od {safe_text(criteria.year_from)} do {safe_text(criteria.year_to)}",
        f"- Budżet: {format_usd(criteria.budget_usd)}",
        f"- Maksymalny przebieg: {safe_text(criteria.max_odometer_mi)} mi",
        f"- Źródła: {', '.join(criteria.sources)}",
        "",
        "## Zasada selekcji",
        "",
        "Najpierw filtrowane są aukcje według okna zakończenia, seller type insurance, budżetu i typu uszkodzenia. "
        "Dopiero kandydaci po tych filtrach są otwierani w szczegółach i wzbogacani danymi dodatkowymi. "
        "TOP 5 powstaje po analizie AI z uwzględnieniem kosztu importu, ryzyka naprawy i kompletności danych.",
        "",
        "## TOP rekomendacje",
        "",
    ]
    lines.extend(markdown_table(top_recommendations))
    lines.append("")

    for index, item in enumerate(top_recommendations, start=1):
        lines.extend(detail_section(item, index))

    other_results = [item for item in ranked_results if not item.is_top_recommendation][:10]
    if other_results:
        lines.extend(["## Pozostałe sprawdzone auta", ""])
        lines.extend(markdown_table(other_results))
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return str(analysis_path), str(report_path)
