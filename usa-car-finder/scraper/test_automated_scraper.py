"""
Test Automated Scraper - automatyczne wyszukiwanie z mock danych.
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.automated_scraper import AutomatedScraper
from parser.models import ClientCriteria


async def test_automated_search():
    """Test automatycznego wyszukiwania."""
    print("=== Test Automated Scraper ===\n")

    # Kryteria wyszukiwania
    criteria = ClientCriteria(
        make="Toyota",
        model="Camry",
        year_from=2018,
        year_to=2020,
        budget_usd=12000,
        max_odometer_mi=100000,
        max_results=10,
        sources=["copart", "iaai"],
        excluded_damage_types=["Flood", "Fire"]
    )

    print(f"Kryteria wyszukiwania:")
    print(f"  Marka: {criteria.make} {criteria.model}")
    print(f"  Rocznik: {criteria.year_from}-{criteria.year_to}")
    print(f"  Budżet: ${criteria.budget_usd}")
    print(f"  Max przebieg: {criteria.max_odometer_mi} mil")
    print(f"  Źródła: {', '.join(criteria.sources)}")
    print("\n" + "="*50 + "\n")

    # UWAGA: Ten test używa MOCK danych, nie prawdziwego scrapingu
    # Aby użyć prawdziwego scrapingu, odkomentuj poniższy kod

    # scraper = AutomatedScraper()
    # lots = await scraper.search_cars(criteria)

    # print(f"\n✅ Znaleziono {len(lots)} lotów")
    # for lot in lots[:3]:
    #     print(f"  - {lot.year} {lot.make} {lot.model} | ${lot.current_bid_usd} | {lot.location_state}")

    # Dla testu używamy mock danych
    from scraper.mock_data import get_mock_lots
    lots = get_mock_lots(criteria)

    print(f"✅ Mock: Znaleziono {len(lots)} lotów")
    for lot in lots[:5]:
        print(f"  - {lot.year} {lot.make} {lot.model} | ${lot.current_bid_usd} | {lot.location_state}")


if __name__ == "__main__":
    asyncio.run(test_automated_search())
