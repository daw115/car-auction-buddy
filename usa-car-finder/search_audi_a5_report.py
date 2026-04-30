import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from ai.analyzer import analyze_lots
from parser.models import AnalyzedLot, ClientCriteria
from report.generator import generate_pdf_report
from scraper.automated_scraper import AutomatedScraper


TOP_RECOMMENDATIONS = int(os.getenv("CLIENT_TOP_N", "5"))
DETAILS_PER_SOURCE = int(os.getenv("CLIENT_DETAIL_PER_SOURCE", os.getenv("MAX_RESULTS_PER_SOURCE", "100")))
AUCTION_MIN_HOURS = int(os.getenv("CLIENT_AUCTION_MIN_HOURS", "12"))
AUCTION_MAX_HOURS = int(os.getenv("CLIENT_AUCTION_MAX_HOURS", "120"))
OUTPUT_DIR = Path("data/client_searches")


def lot_to_dict(item: AnalyzedLot) -> dict:
    lot = item.lot
    analysis = item.analysis
    return {
        "source": lot.source,
        "lot_id": lot.lot_id,
        "url": lot.url,
        "year": lot.year,
        "make": lot.make,
        "model": lot.model,
        "trim": lot.trim,
        "vin": lot.full_vin or lot.vin,
        "odometer_mi": lot.odometer_mi,
        "odometer_km": lot.odometer_km,
        "damage_primary": lot.damage_primary,
        "damage_secondary": lot.damage_secondary,
        "title_type": lot.title_type,
        "current_bid_usd": lot.current_bid_usd,
        "buy_now_price_usd": lot.buy_now_price_usd,
        "seller_reserve_usd": lot.seller_reserve_usd,
        "seller_type": lot.seller_type,
        "location_city": lot.location_city,
        "location_state": lot.location_state,
        "auction_date": lot.auction_date,
        "keys": lot.keys,
        "airbags_deployed": lot.airbags_deployed,
        "enriched_by_extension": lot.enriched_by_extension,
        "images": lot.images,
        "html_file": lot.html_file,
        "raw_data": lot.raw_data,
        "score": analysis.score,
        "recommendation": analysis.recommendation,
        "red_flags": analysis.red_flags,
        "estimated_repair_usd": analysis.estimated_repair_usd,
        "estimated_total_cost_usd": analysis.estimated_total_cost_usd,
        "client_description_pl": analysis.client_description_pl,
        "ai_notes": analysis.ai_notes,
    }


def lot_to_ai_input(lot) -> dict:
    return lot.model_dump(mode="json")


def build_ai_prompt(criteria: ClientCriteria, lots: list) -> str:
    payload = {
        "task": (
            "Przeanalizuj auta z aukcji USA dla klienta importowego. "
            "Wybierz najlepsze propozycje, uzasadnij ranking, ryzyka, koszty naprawy i transportu."
        ),
        "selection_pipeline": [
            f"auction window: {AUCTION_MIN_HOURS}h do {AUCTION_MAX_HOURS}h",
            "seller_type: insurance",
            "damage priority: najmniejsze i najbezpieczniejsze uszkodzenia pierwsze",
            "details: otwarte tylko dla kandydatów po filtrach listy",
        ],
        "criteria": criteria.model_dump(mode="json"),
        "lots": [lot_to_ai_input(lot) for lot in lots],
        "expected_output": {
            "language": "pl",
            "format": "JSON array",
            "fields": [
                "lot_id",
                "score",
                "recommendation",
                "why_selected",
                "risk_flags",
                "estimated_repair_usd",
                "estimated_total_cost_usd",
                "client_summary",
                "broker_notes",
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def search_source(source: str, criteria: ClientCriteria) -> list:
    scan_criteria = criteria.model_copy(update={"max_results": DETAILS_PER_SOURCE, "sources": [source]})

    scraper = AutomatedScraper()
    lots = await scraper.search_cars(
        scan_criteria,
        min_auction_window_hours=AUCTION_MIN_HOURS,
        auction_window_hours=AUCTION_MAX_HOURS,
    )

    if not lots:
        print(f"[ClientSearch] {source.upper()}: brak potwierdzonych lotów insurance")
        return []

    print(f"[ClientSearch] {source.upper()}: zebrano {len(lots)} lotów po filtrach listy")
    return lots


async def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    criteria = ClientCriteria(
        make="Audi",
        model="A5",
        year_from=2015,
        budget_usd=30000,
        max_results=TOP_RECOMMENDATIONS,
        sources=["copart", "iaai"],
    )

    all_lots = []
    per_source_counts: dict[str, int] = {}
    for source in ("copart", "iaai"):
        source_lots = await search_source(source, criteria)
        per_source_counts[source] = len(source_lots)
        all_lots.extend(source_lots)

    merged_input = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "criteria": {
            "make": "Audi",
            "model": "A5",
            "budget_usd": 30000,
            "year_from": 2015,
            "seller_type": "insurance",
            "auction_window_hours": {"min": AUCTION_MIN_HOURS, "max": AUCTION_MAX_HOURS},
            "details_per_source_limit": DETAILS_PER_SOURCE,
            "damage_prefilter": "exclude visible Flood/Fire; sort by lowest damage severity before details",
            "listing_prefilter_order": [
                "auction window",
                "insurance seller",
                "excluded/least damage",
                "open details",
            ],
        },
        "counts": per_source_counts,
        "lots": [lot_to_ai_input(lot) for lot in all_lots],
    }

    merged_path = OUTPUT_DIR / f"audi_a5_insurance_ai_input_{timestamp}.json"
    merged_path.write_text(json.dumps(merged_input, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ClientSearch] Jeden plik danych do AI: {merged_path}")

    prompt_path = OUTPUT_DIR / f"audi_a5_insurance_ai_prompt_{timestamp}.md"
    prompt_path.write_text(build_ai_prompt(criteria, all_lots), encoding="utf-8")
    print(f"[ClientSearch] Prompt/plik do wklejenia w AI: {prompt_path}")

    top_recommendations: list[AnalyzedLot] = []
    all_ranked: list[AnalyzedLot] = []
    if all_lots:
        top_recommendations, all_ranked = analyze_lots(
            all_lots,
            criteria,
            top_n=min(TOP_RECOMMENDATIONS, len(all_lots)),
        )
        for item in top_recommendations:
            item.included_in_report = True
    else:
        print("[ClientSearch] Brak lotów do analizy AI po filtrach listy.")

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "criteria": {
            "make": "Audi",
            "model": "A5",
            "budget_usd": 30000,
            "year_from": 2015,
            "seller_type": "insurance",
            "auction_window_hours": {"min": AUCTION_MIN_HOURS, "max": AUCTION_MAX_HOURS},
            "top_recommendations": TOP_RECOMMENDATIONS,
            "details_per_source_limit": DETAILS_PER_SOURCE,
            "listing_prefilter": "auction window → insurance → damage before opening detail pages",
        },
        "counts": per_source_counts,
        "ai_input_file": str(merged_path),
        "ai_prompt_file": str(prompt_path),
        "top_recommendations": [lot_to_dict(item) for item in top_recommendations],
        "results": [lot_to_dict(item) for item in all_ranked],
    }

    json_path = OUTPUT_DIR / f"audi_a5_insurance_{timestamp}.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ClientSearch] Dane JSON: {json_path}")

    report_path = None
    if top_recommendations:
        report_path = generate_pdf_report(
            top_recommendations,
            output_filename=f"raport_audi_a5_insurance_{timestamp}.pdf",
        )
        print(f"[ClientSearch] Raport PDF: {report_path}")
    else:
        print("[ClientSearch] Nie wygenerowano PDF, bo nie ma lotów spełniających filtr insurance.")

    print(
        json.dumps(
            {
                "json": str(json_path),
                "ai_input": str(merged_path),
                "ai_prompt": str(prompt_path),
                "pdf": str(report_path) if report_path else None,
                "counts": per_source_counts,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
