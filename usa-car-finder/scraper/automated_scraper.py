"""
Automated Scraper - automatyczne wyszukiwanie aut na podstawie parametrów.
Integruje istniejące scrapery Copart i IAAI z wzbogacaniem danych z botów.
"""
import os
import asyncio
import re
import math
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

# Import istniejących modułów
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from parser.models import CarLot, ClientCriteria
from scraper.base import BaseScraper
from scraper.copart import CopartScraper
from scraper.iaai import IAAIScraper
from parser.copart_parser import parse_copart_html
from parser.iaai_parser import parse_iaai_html
from scraper.extension_enricher import ExtensionEnricher


class AutomatedScraper:
    """Automatyczny scraper z wzbogacaniem danych."""

    def __init__(self):
        self.html_cache_dir = Path(os.getenv("HTML_CACHE_DIR", "./data/html_cache"))
        self.use_extensions = os.getenv("USE_EXTENSIONS", "false").lower() == "true"
        self.filter_insurance_only = os.getenv("FILTER_SELLER_INSURANCE_ONLY", "false").lower() == "true"
        self.min_auction_window_hours = int(os.getenv("MIN_AUCTION_WINDOW_HOURS", "12"))
        self.max_auction_window_hours = int(os.getenv("MAX_AUCTION_WINDOW_HOURS", "120"))
        self.collect_all_prefiltered_results = (
            os.getenv("COLLECT_ALL_PREFILTERED_RESULTS", "true").lower() == "true"
        )

    async def search_cars(
        self,
        criteria: ClientCriteria,
        auction_window_hours: Optional[int] = None,
        min_auction_window_hours: Optional[int] = None,
    ) -> List[CarLot]:
        """
        Automatyczne wyszukiwanie aut na podstawie kryteriów.

        Args:
            criteria: Parametry wyszukiwania
            auction_window_hours: Górna granica okna aukcji w godzinach (np. 120 = 5 dni).
            min_auction_window_hours: Dolna granica okna aukcji (np. 12h).

        Returns:
            Lista znalezionych lotów z wzbogaconymi danymi
        """
        all_lots = []
        strict_scan_threshold = max(0, int(os.getenv("STRICT_SCAN_MAX_RESULTS_THRESHOLD", "3")))
        strict_scan = bool(strict_scan_threshold and criteria.max_results <= strict_scan_threshold)
        selected_sources = [source for source in ("copart", "iaai") if source in criteria.sources]
        max_window_hours = auction_window_hours if auction_window_hours is not None else self.max_auction_window_hours
        min_window_hours = (
            min_auction_window_hours
            if min_auction_window_hours is not None
            else self.min_auction_window_hours
        )

        def source_criteria(remaining_sources: int) -> ClientCriteria:
            if not strict_scan:
                return criteria

            remaining_budget = max(1, criteria.max_results - len(all_lots))
            source_limit = max(1, math.ceil(remaining_budget / max(1, remaining_sources)))
            return criteria.model_copy(update={"max_results": source_limit})

        # 1. Scraping Copart
        if "copart" in criteria.sources:
            print(f"[AutoScraper] Scrapuję Copart dla {criteria.make} {criteria.model or ''}...")
            try:
                scraper = CopartScraper()
                saved_files = await scraper.scrape(
                    source_criteria(len(selected_sources)),
                    min_auction_window_hours=min_window_hours,
                    auction_window_hours=max_window_hours,
                    insurance_only=self.filter_insurance_only,
                )
                copart_lots = []
                for path, lot_url in saved_files:
                    lot = parse_copart_html(Path(path))
                    if lot is None:
                        continue
                    lot.url = lot_url
                    lot.lot_id = self._extract_lot_id_from_url(lot_url) or lot.lot_id
                    self._apply_listing_metadata(lot, scraper.last_listing_metadata.get(lot_url))
                    copart_lots.append(lot)
                all_lots.extend(copart_lots)
                print(f"[AutoScraper] Znaleziono {len(copart_lots)} lotów na Copart")
            except Exception as e:
                print(f"[AutoScraper] Błąd Copart: {e}")

        # 2. Scraping IAAI
        if "copart" in selected_sources:
            selected_sources.remove("copart")
        if "iaai" in criteria.sources:
            print(f"[AutoScraper] Scrapuję IAAI dla {criteria.make} {criteria.model or ''}...")
            try:
                scraper = IAAIScraper()
                saved_files = await scraper.scrape(
                    source_criteria(len(selected_sources)),
                    min_auction_window_hours=min_window_hours,
                    auction_window_hours=max_window_hours,
                    insurance_only=self.filter_insurance_only,
                )
                iaai_lots = []
                for path, lot_url in saved_files:
                    lot = parse_iaai_html(Path(path))
                    if lot is None:
                        continue
                    lot.url = lot_url
                    lot.lot_id = self._extract_lot_id_from_url(lot_url) or lot.lot_id
                    self._apply_listing_metadata(lot, scraper.last_listing_metadata.get(lot_url))
                    iaai_lots.append(lot)
                all_lots.extend(iaai_lots)
                print(f"[AutoScraper] Znaleziono {len(iaai_lots)} lotów na IAAI")
            except Exception as e:
                print(f"[AutoScraper] Błąd IAAI: {e}")

        # 3. Filtrowanie po kryteriach klienta
        before_criteria_filter = len(all_lots)
        all_lots = self._filter_by_client_criteria(all_lots, criteria)
        if before_criteria_filter != len(all_lots):
            print(
                f"[AutoScraper] Filtr make/model/rok/przebieg: "
                f"{before_criteria_filter} → {len(all_lots)} lotów"
            )

        # 4. Filtrowanie po dacie aukcji
        if max_window_hours is not None:
            before_filter = len(all_lots)
            time_filtered_lots = self._filter_by_auction_date(
                all_lots,
                min_hours=min_window_hours,
                max_hours=max_window_hours,
            )
            print(
                f"[AutoScraper] Filtr czasowy {min_window_hours}h–{max_window_hours}h: "
                f"{before_filter} → {len(time_filtered_lots)} lotów"
            )

            all_lots = time_filtered_lots

            all_lots.sort(key=self._auction_sort_key)
            if (
                criteria.max_results
                and len(all_lots) > criteria.max_results
                and not self.filter_insurance_only
            ):
                all_lots = all_lots[:criteria.max_results]
                print(f"[AutoScraper] Ograniczam do {len(all_lots)} lotów wg kryterium max_results")

        # 5. Wzbogacanie danymi z botów (jeśli włączone)
        if self.use_extensions and all_lots:
            print(f"[AutoScraper] Wzbogacam dane z AuctionGate i AutoHelperBot...")
            all_lots = await self._enrich_with_extensions(all_lots)

        # 6. Opcjonalne filtrowanie po seller_type (tylko ubezpieczyciele)
        if self.filter_insurance_only:
            before_seller_filter = len(all_lots)
            unknown_seller_count = sum(1 for lot in all_lots if lot.seller_type is None)
            confirmed_non_insurance = sum(1 for lot in all_lots if lot.seller_type == "dealer")
            all_lots = [lot for lot in all_lots if lot.seller_type in ("insurance", None)]
            print(
                f"[AutoScraper] Filtr seller_type: {before_seller_filter} → {len(all_lots)} lotów "
                f"(odrzucono {confirmed_non_insurance} dealer, zachowano {unknown_seller_count} unknown)"
            )

        all_lots.sort(key=self._damage_then_auction_sort_key)

        if (
            criteria.max_results
            and len(all_lots) > criteria.max_results
            and not self.collect_all_prefiltered_results
        ):
            all_lots = all_lots[:criteria.max_results]
            print(f"[AutoScraper] Ograniczam finalnie do {len(all_lots)} lotów wg kryterium max_results")

        print(f"[AutoScraper] Łącznie znaleziono {len(all_lots)} lotów")
        return all_lots

    def _filter_by_auction_date(self, lots: List[CarLot], min_hours: int, max_hours: int) -> List[CarLot]:
        """
        Filtruje loty, zostawiając tylko te, których aukcja kończy się pomiędzy min_hours a max_hours.

        Format auction_date: "YYYY-MM-DD HH:MM:SS" (UTC) lub "YYYY-MM-DD".
        Loty bez daty aukcji są odrzucane.
        """
        if min_hours > max_hours:
            min_hours, max_hours = max_hours, min_hours

        now = datetime.now(timezone.utc)
        earliest = now + timedelta(hours=min_hours)
        deadline = now + timedelta(hours=max_hours)
        filtered = []

        for lot in lots:
            if not lot.auction_date:
                # Brak daty - odrzuć, bo nie spełnia kryterium okna czasu
                continue

            try:
                # Parsuj datę aukcji
                date_str = lot.auction_date.strip()
                if len(date_str) == 10:
                    # Format "YYYY-MM-DD" - zakładamy koniec dnia UTC
                    auction_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                        hour=23, minute=59, tzinfo=timezone.utc
                    )
                else:
                    # Format "YYYY-MM-DD HH:MM:SS"
                    auction_dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=timezone.utc
                    )

                # Zachowaj loty, których aukcja jest w zadanym oknie czasowym
                if earliest <= auction_dt <= deadline:
                    filtered.append(lot)
            except (ValueError, AttributeError):
                # Nieznany format - odrzuć
                continue

        return filtered

    @staticmethod
    def _extract_lot_id_from_url(url: str) -> Optional[str]:
        if not url:
            return None
        explicit_match = re.search(r"/(?:lot|VehicleDetail)/(\d+)", url, flags=re.IGNORECASE)
        if explicit_match:
            return explicit_match.group(1)
        clean = url.split("?", 1)[0].rstrip("/")
        if not clean:
            return None
        tail = clean.split("/")[-1]
        m = re.search(r"(\d+)", tail)
        return m.group(1) if m else tail

    @staticmethod
    def _apply_listing_metadata(lot: CarLot, metadata: Optional[dict]) -> None:
        if not metadata:
            return
        if metadata.get("seller_type"):
            lot.seller_type = metadata["seller_type"]
        extension_data = metadata.get("extension_data") or {}
        if extension_data:
            if extension_data.get("seller_type"):
                lot.seller_type = extension_data["seller_type"]
            if extension_data.get("seller_reserve_usd"):
                lot.seller_reserve_usd = extension_data["seller_reserve_usd"]
            if extension_data.get("full_vin"):
                lot.full_vin = extension_data["full_vin"]
            if extension_data.get("delivery_cost_estimate_usd"):
                lot.delivery_cost_estimate_usd = extension_data["delivery_cost_estimate_usd"]
            lot.enriched_by_extension = bool(extension_data.get("enriched_by_extension"))
            lot.raw_data["extension_data"] = extension_data
        if metadata.get("auction_date"):
            lot.auction_date = metadata["auction_date"]
        if metadata.get("listing_damage_text"):
            lot.raw_data["listing_damage_text"] = metadata["listing_damage_text"]
        if metadata.get("listing_damage_score") is not None:
            lot.raw_data["listing_damage_score"] = metadata["listing_damage_score"]
        if metadata.get("listing_damage_label"):
            lot.raw_data["listing_damage_label"] = metadata["listing_damage_label"]
        listing_raw = metadata.get("listing_raw_data")
        if listing_raw:
            lot.raw_data["listing"] = listing_raw
            dynamic = listing_raw.get("dynamicLotDetails") or {}
            current_bid = dynamic.get("currentBid") or listing_raw.get("hb")
            buy_now = listing_raw.get("bnp")
            if lot.current_bid_usd is None and current_bid not in (None, "", 0, 0.0):
                try:
                    lot.current_bid_usd = float(current_bid)
                except (TypeError, ValueError):
                    pass
            if lot.buy_now_price_usd is None and buy_now not in (None, "", 0, 0.0):
                try:
                    lot.buy_now_price_usd = float(buy_now)
                except (TypeError, ValueError):
                    pass
            image_url = listing_raw.get("tims")
            if image_url and not lot.images:
                lot.images = [image_url]
        if metadata.get("listing_row_text"):
            lot.raw_data["listing_row_text"] = metadata["listing_row_text"]

    async def _enrich_with_extensions(self, lots: List[CarLot]) -> List[CarLot]:
        """Wzbogaca dane z rozszerzeń Chromium."""
        enricher = ExtensionEnricher()

        # Przygotuj listę (url, cache_path) dla każdego lota
        lots_to_enrich = [
            (lot.url, Path(lot.html_file))
            for lot in lots if lot.html_file and not lot.enriched_by_extension
        ]

        if not lots_to_enrich:
            print("[AutoScraper] Dane z botów zebrane już podczas pobierania detali")
            return lots

        # Wzbogacaj tylko loty, dla których nie udało się odczytać bota na detalu.
        try:
            enriched_map = await enricher.enrich_all(lots_to_enrich)
        except Exception as e:
            print(f"[AutoScraper] Błąd enrichera, pomijam wzbogacanie: {e}")
            return lots

        # Wzbogać loty danymi z rozszerzeń
        for lot in lots:
            ext = enriched_map.get(lot.url, {})
            if ext:
                lot.seller_reserve_usd = ext.get("seller_reserve_usd")
                if ext.get("seller_type"):
                    lot.seller_type = ext.get("seller_type")
                if ext.get("full_vin"):
                    lot.full_vin = ext.get("full_vin")
                lot.enriched_by_extension = ext.get("enriched_by_extension", False)

        enriched_count = sum(1 for lot in lots if lot.enriched_by_extension)
        print(f"[AutoScraper] Wzbogacono {enriched_count}/{len(lots)} lotów")

        return lots

    @staticmethod
    def _normalize_text(text: Optional[str]) -> str:
        return (text or "").strip().lower()

    def _filter_by_client_criteria(self, lots: List[CarLot], criteria: ClientCriteria) -> List[CarLot]:
        filtered: List[CarLot] = []
        make_query = self._normalize_text(criteria.make)
        model_query = self._normalize_text(criteria.model)

        for lot in lots:
            lot_make = self._normalize_text(lot.make)
            lot_model = self._normalize_text(lot.model)

            # IAAI bywa szerokie w wynikach; filtrujemy twardo po marce/modelu.
            if make_query and (not lot_make or make_query not in lot_make):
                continue
            if model_query and (not lot_model or model_query not in lot_model):
                continue

            if criteria.year_from and lot.year and lot.year < criteria.year_from:
                continue
            if criteria.year_to and lot.year and lot.year > criteria.year_to:
                continue
            if criteria.max_odometer_mi and lot.odometer_mi and lot.odometer_mi > criteria.max_odometer_mi:
                continue

            filtered.append(lot)

        return filtered

    @staticmethod
    def _auction_sort_key(lot: CarLot):
        date_str = (lot.auction_date or "").strip()
        if not date_str:
            return datetime.max.replace(tzinfo=timezone.utc)
        try:
            if len(date_str) == 10:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=23, minute=59, tzinfo=timezone.utc
                )
            else:
                dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            return dt
        except Exception:
            return datetime.max.replace(tzinfo=timezone.utc)

    @staticmethod
    def _damage_then_auction_sort_key(lot: CarLot):
        damage_text = BaseScraper.damage_text_from_values(
            lot.damage_primary,
            lot.damage_secondary,
            lot.raw_data.get("listing_damage_text") if lot.raw_data else None,
        )
        score, _label = BaseScraper.damage_severity_score(damage_text)
        return (
            score,
            AutomatedScraper._auction_sort_key(lot),
            lot.source or "",
            lot.lot_id or "",
        )
