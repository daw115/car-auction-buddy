"""
Test scrapowania i parsowania danych z Copart i IAAI.
Sprawdza kompletność zebranych danych.
"""
import asyncio
import sys
from pathlib import Path
from scraper.automated_scraper import AutomatedScraper
from parser.models import ClientCriteria

def analyze_lot_completeness(lot, source_name):
    """Analizuje kompletność danych pojedynczego lota."""
    fields = {
        'lot_id': lot.lot_id,
        'url': lot.url,
        'make': lot.make,
        'model': lot.model,
        'year': lot.year,
        'vin': lot.vin,
        'full_vin': lot.full_vin,
        'odometer_mi': lot.odometer_mi,
        'damage_primary': lot.damage_primary,
        'title_type': lot.title_type,
        'current_bid_usd': lot.current_bid_usd,
        'location_city': lot.location_city,
        'location_state': lot.location_state,
        'auction_date': lot.auction_date,
        'seller_type': lot.seller_type,
        'seller_reserve_usd': lot.seller_reserve_usd,
        'images': len(lot.images) if lot.images else 0,
    }

    missing = [k for k, v in fields.items() if v is None or (k == 'images' and v == 0)]
    present = [k for k, v in fields.items() if v is not None and (k != 'images' or v > 0)]

    return fields, missing, present

async def test_source(source_name, criteria):
    """Testuje pojedyncze źródło."""
    print(f"\n{'='*60}")
    print(f"TEST: {source_name.upper()}")
    print(f"{'='*60}")

    scraper = AutomatedScraper()
    criteria.sources = [source_name]

    try:
        lots = await scraper.search_cars(criteria, auction_window_hours=168)

        if not lots:
            print(f"❌ Brak wyników dla {source_name}")
            return None

        print(f"\n✅ Znaleziono {len(lots)} lotów")

        # Statystyki kompletności
        stats = {
            'total': len(lots),
            'with_full_vin': 0,
            'with_seller_type': 0,
            'with_reserve': 0,
            'with_auction_date': 0,
            'enriched': 0,
            'insurance_only': 0,
        }

        for lot in lots:
            if lot.full_vin:
                stats['with_full_vin'] += 1
            if lot.seller_type:
                stats['with_seller_type'] += 1
                if lot.seller_type == 'insurance':
                    stats['insurance_only'] += 1
            if lot.seller_reserve_usd:
                stats['with_reserve'] += 1
            if lot.auction_date:
                stats['with_auction_date'] += 1
            if lot.enriched_by_extension:
                stats['enriched'] += 1

        print(f"\n=== STATYSTYKI KOMPLETNOŚCI ===")
        print(f"Pełny VIN:        {stats['with_full_vin']}/{stats['total']} ({stats['with_full_vin']/stats['total']*100:.1f}%)")
        print(f"Seller type:      {stats['with_seller_type']}/{stats['total']} ({stats['with_seller_type']/stats['total']*100:.1f}%)")
        print(f"  - Insurance:    {stats['insurance_only']}/{stats['with_seller_type']}")
        print(f"Seller reserve:   {stats['with_reserve']}/{stats['total']} ({stats['with_reserve']/stats['total']*100:.1f}%)")
        print(f"Data aukcji:      {stats['with_auction_date']}/{stats['total']} ({stats['with_auction_date']/stats['total']*100:.1f}%)")
        print(f"Wzbogacone:       {stats['enriched']}/{stats['total']} ({stats['enriched']/stats['total']*100:.1f}%)")

        # Szczegóły pierwszych 3 lotów
        print(f"\n=== PRZYKŁADOWE LOTY (pierwsze 3) ===")
        for i, lot in enumerate(lots[:3], 1):
            fields, missing, present = analyze_lot_completeness(lot, source_name)

            print(f"\n--- LOT #{i} ---")
            print(f"ID: {lot.lot_id}")
            print(f"Auto: {lot.year or '?'} {lot.make or '?'} {lot.model or '?'}")
            print(f"VIN: {lot.vin[:8] if lot.vin else 'brak'}... / Full: {lot.full_vin or 'brak'}")
            print(f"Przebieg: {lot.odometer_mi or '?'} mil")
            print(f"Uszkodzenie: {lot.damage_primary or 'brak'}")
            print(f"Cena: ${lot.current_bid_usd or 0:,.0f}")
            print(f"Lokalizacja: {lot.location_city or '?'}, {lot.location_state or '?'}")
            print(f"Data aukcji: {lot.auction_date or 'brak'}")
            print(f"Seller type: {lot.seller_type or 'brak'}")
            print(f"Seller reserve: ${lot.seller_reserve_usd or 0:,.0f}")
            print(f"Zdjęcia: {len(lot.images)}")
            print(f"Wzbogacone: {'TAK' if lot.enriched_by_extension else 'NIE'}")
            print(f"Brakujące pola ({len(missing)}): {', '.join(missing) if missing else 'brak'}")

        return stats

    except Exception as e:
        print(f"❌ Błąd podczas testu {source_name}: {e}")
        import traceback
        traceback.print_exc()
        return None

async def main():
    print("="*60)
    print("TEST SCRAPERÓW COPART I IAAI")
    print("="*60)

    # Kryteria testowe
    criteria = ClientCriteria(
        make='Toyota',
        model='Camry',
        year_from=2018,
        year_to=2024,
        budget_usd=15000,
        max_odometer_mi=100000,
        max_results=5,  # Tylko 5 lotów dla szybkiego testu
        sources=["copart"],  # placeholder, ustawiane dynamicznie w test_source()
        excluded_damage_types=['Flood', 'Fire'],
    )

    print(f"\nKryteria wyszukiwania:")
    print(f"  Marka: {criteria.make} {criteria.model}")
    print(f"  Lata: {criteria.year_from}-{criteria.year_to}")
    print(f"  Budżet: ${criteria.budget_usd:,.0f}")
    print(f"  Max przebieg: {criteria.max_odometer_mi:,} mil")
    print(f"  Limit wyników: {criteria.max_results}")
    print(f"  Okno aukcji: 168h (7 dni)")

    # Test Copart
    copart_stats = await test_source('copart', criteria)

    # Test IAAI
    iaai_stats = await test_source('iaai', criteria)

    # Podsumowanie
    print(f"\n{'='*60}")
    print("PODSUMOWANIE")
    print(f"{'='*60}")

    if copart_stats:
        print(f"\n✅ COPART: {copart_stats['total']} lotów")
        print(f"   Wzbogacone: {copart_stats['enriched']}/{copart_stats['total']}")
        print(f"   Pełny VIN: {copart_stats['with_full_vin']}/{copart_stats['total']}")
        print(f"   Seller type: {copart_stats['with_seller_type']}/{copart_stats['total']}")
    else:
        print("\n❌ COPART: test nieudany")

    if iaai_stats:
        print(f"\n✅ IAAI: {iaai_stats['total']} lotów")
        print(f"   Wzbogacone: {iaai_stats['enriched']}/{iaai_stats['total']}")
        print(f"   Pełny VIN: {iaai_stats['with_full_vin']}/{iaai_stats['total']}")
        print(f"   Seller type: {iaai_stats['with_seller_type']}/{iaai_stats['total']}")
    else:
        print("\n❌ IAAI: test nieudany")

    print(f"\n{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
