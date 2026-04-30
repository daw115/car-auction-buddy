import os
from pathlib import Path
from typing import List, Optional
from parser.models import CarLot, ClientCriteria

# Testowe dane - mockowane loty do testowania aplikacji
MOCK_LOTS = [
    {
        "source": "copart",
        "lot_id": "12345678",
        "url": "https://www.copart.com/lot/12345678",
        "vin": "1HGBH41JXMN109186",
        "year": 2018,
        "make": "Toyota",
        "model": "Camry",
        "odometer_mi": 45000,
        "odometer_km": 72420,
        "damage_primary": "Front End",
        "title_type": "Salvage",
        "current_bid_usd": 4500.0,
        "location_state": "TX",
        "location_city": "Dallas",
        "keys": True,
        "airbags_deployed": False,
        "images": ["https://placehold.co/400x300/png?text=Toyota+Camry+2018"]
    },
    {
        "source": "copart",
        "lot_id": "23456789",
        "url": "https://www.copart.com/lot/23456789",
        "vin": "4T1BF1FK5HU123456",
        "year": 2017,
        "make": "Toyota",
        "model": "Camry",
        "odometer_mi": 62000,
        "odometer_km": 99779,
        "damage_primary": "Rear End",
        "title_type": "Salvage",
        "current_bid_usd": 3800.0,
        "location_state": "CA",
        "location_city": "Los Angeles",
        "keys": True,
        "airbags_deployed": True,
        "images": ["https://placehold.co/400x300/png?text=Toyota+Camry+2017"]
    },
    {
        "source": "iaai",
        "lot_id": "34567890",
        "url": "https://www.iaai.com/vehicle/34567890",
        "vin": "4T1BF1FK6HU234567",
        "year": 2019,
        "make": "Toyota",
        "model": "Camry",
        "odometer_mi": 38000,
        "odometer_km": 61155,
        "damage_primary": "Side",
        "title_type": "Clean",
        "current_bid_usd": 6200.0,
        "location_state": "FL",
        "location_city": "Miami",
        "keys": True,
        "airbags_deployed": False,
        "images": ["https://placehold.co/400x300/png?text=Toyota+Camry+2019"]
    },
    {
        "source": "copart",
        "lot_id": "45678901",
        "url": "https://www.copart.com/lot/45678901",
        "vin": "4T1BF1FK7HU345678",
        "year": 2016,
        "make": "Toyota",
        "model": "Camry",
        "odometer_mi": 78000,
        "odometer_km": 125529,
        "damage_primary": "Hail",
        "title_type": "Salvage",
        "current_bid_usd": 3200.0,
        "location_state": "TX",
        "location_city": "Houston",
        "keys": False,
        "airbags_deployed": False,
        "images": ["https://placehold.co/400x300/png?text=Toyota+Camry+2016"]
    },
    {
        "source": "iaai",
        "lot_id": "56789012",
        "url": "https://www.iaai.com/vehicle/56789012",
        "vin": "4T1BF1FK8HU456789",
        "full_vin": "4T1BF1FK8HU456789ABC",  # Pełny VIN z rozszerzenia
        "year": 2018,
        "make": "Toyota",
        "model": "Camry",
        "odometer_mi": 52000,
        "odometer_km": 83686,
        "damage_primary": "Front End",
        "title_type": "Salvage",
        "current_bid_usd": 4800.0,
        "seller_reserve_usd": 5500.0,  # Z AuctionGate
        "seller_type": "insurance",  # Z AuctionGate
        "delivery_cost_estimate_usd": 1650.0,  # Z AuctionGate
        "location_state": "AZ",
        "location_city": "Phoenix",
        "keys": True,
        "airbags_deployed": True,
        "images": ["https://placehold.co/400x300/png?text=Toyota+Camry+2018"],
        "enriched_by_extension": True
    },
    {
        "source": "copart",
        "lot_id": "67890123",
        "url": "https://www.copart.com/lot/67890123",
        "vin": "4T1BF1FK9HU567890",
        "year": 2019,
        "make": "Toyota",
        "model": "Camry",
        "odometer_mi": 41000,
        "odometer_km": 65983,
        "damage_primary": "Minor Dent/Scratches",
        "title_type": "Clean",
        "current_bid_usd": 7500.0,
        "location_state": "NV",
        "location_city": "Las Vegas",
        "keys": True,
        "airbags_deployed": False,
        "images": ["https://placehold.co/400x300/png?text=Toyota+Camry+2019"]
    },
    {
        "source": "iaai",
        "lot_id": "78901234",
        "url": "https://www.iaai.com/vehicle/78901234",
        "vin": "4T1BF1FK0HU678901",
        "year": 2017,
        "make": "Toyota",
        "model": "Camry",
        "odometer_mi": 68000,
        "odometer_km": 109435,
        "damage_primary": "Mechanical",
        "title_type": "Salvage",
        "current_bid_usd": 2900.0,
        "location_state": "GA",
        "location_city": "Atlanta",
        "keys": True,
        "airbags_deployed": False,
        "images": ["https://placehold.co/400x300/png?text=Toyota+Camry+2017"]
    },
    {
        "source": "copart",
        "lot_id": "89012345",
        "url": "https://www.copart.com/lot/89012345",
        "vin": "4T1BF1FK1HU789012",
        "full_vin": "4T1BF1FK1HU789012XYZ",  # Pełny VIN z rozszerzenia
        "year": 2020,
        "make": "Toyota",
        "model": "Camry",
        "odometer_mi": 28000,
        "odometer_km": 45062,
        "damage_primary": "Front End",
        "title_type": "Salvage",
        "current_bid_usd": 8200.0,
        "seller_reserve_usd": 9000.0,  # Z AutoHelperBot
        "seller_type": "dealer",  # Z AutoHelperBot
        "delivery_cost_estimate_usd": 1800.0,  # Z AutoHelperBot
        "location_state": "NY",
        "location_city": "New York",
        "keys": True,
        "airbags_deployed": True,
        "images": ["https://placehold.co/400x300/png?text=Toyota+Camry+2020"],
        "enriched_by_extension": True
    }
]


def get_mock_lots(criteria: ClientCriteria) -> List[CarLot]:
    """Zwraca mockowane loty do testowania aplikacji"""
    lots = []

    for mock_data in MOCK_LOTS[:criteria.max_results]:
        # Filtruj po marce i modelu
        if mock_data["make"].lower() != criteria.make.lower():
            continue
        if criteria.model and mock_data["model"].lower() != criteria.model.lower():
            continue

        # Filtruj po roczniku
        if criteria.year_from and mock_data["year"] < criteria.year_from:
            continue
        if criteria.year_to and mock_data["year"] > criteria.year_to:
            continue

        # Filtruj po przebiegu
        if criteria.max_odometer_mi and mock_data["odometer_mi"] > criteria.max_odometer_mi:
            continue

        lot = CarLot(**mock_data)
        lots.append(lot)

    return lots
