"""
Wzbogaca dane lotów używając rozszerzeń Chromium: AuctionGate i AutoHelperBot.

Rozszerzenia wstrzykują dane na stronach Copart/IAAI:
  - Pełny VIN (aukcje ukrywają ostatnie 6 znaków)
  - Cenę rezerwową sprzedawcy (seller reserve)
  - Typ sprzedawcy: ubezpieczyciel vs dealer/reseller
  - Średnią cenę rynkową

Rozszerzenia muszą być skopiowane do katalogów:
  ./extensions/auctiongate/
  ./extensions/autohelperbot/
"""

import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from .browser_context import (
    extensions_arg,
    get_shared_extension_context,
    keep_browser_open,
    launch_extension_context,
)

load_dotenv(override=True)

EXTENSION_DIRS = [
    Path("./extensions/auctiongate"),
    Path("./extensions/autohelperbot"),
]
CHROME_PROFILE_DIR = Path(os.getenv("CHROME_PROFILE_DIR", "./data/chrome_profile"))

_AHB_JS = """
() => {
    const result = {};
    const bodyText = document.body.innerText;

    const vinMatch = bodyText.match(/VIN code[:\\s]*([A-HJ-NPR-Z0-9]{17})/i);
    if (vinMatch) result.full_vin = vinMatch[1];

    const whoSellsMatch = bodyText.match(/Who sells[:\\s]*(Insurance|Dealer)/i) ||
                         bodyText.match(/Seller[:\\s]*(Insurance|Dealer)/i) ||
                         bodyText.match(/(Insurance|Dealer)/i);
    if (whoSellsMatch) result.seller_type = whoSellsMatch[1].toLowerCase();

    const avgPriceMatch = bodyText.match(/Average price[:\\s]*\\$([\\d,\\s]+)USD/i);
    if (avgPriceMatch) {
        result.average_price_usd = parseFloat(avgPriceMatch[1].replace(/[,\\s]/g, ''));
    }

    const reserveMatch = bodyText.match(/Seller reserve[:\\s]*\\$([\\d,\\s]+)/i) ||
                        bodyText.match(/Reserve price[:\\s]*\\$([\\d,\\s]+)/i);
    if (reserveMatch) {
        result.seller_reserve_usd = parseFloat(reserveMatch[1].replace(/[,\\s]/g, ''));
    }

    return result;
}
"""


class ExtensionEnricher:

    def _get_extensions_arg(self) -> str:
        return extensions_arg()

    async def _wait_for_ahb_frame(self, page, max_wait_s: int = 20):
        """Polling na iframe AutoHelperBot zamiast sztywnego sleep(15)."""
        for _ in range(max_wait_s):
            for frame in page.frames:
                if "autohelperbot.com" in frame.url:
                    return frame
            await asyncio.sleep(1)
        return None

    async def _extract_from_page(self, page, url: str, html_cache_path: Path) -> dict:
        ahb_frame = await self._wait_for_ahb_frame(page)
        result = {}

        if ahb_frame:
            try:
                ahb_data = await ahb_frame.evaluate(_AHB_JS)
                if ahb_data and (ahb_data.get("full_vin") or ahb_data.get("seller_type")):
                    ahb_data["enriched_by_extension"] = True
                    result = ahb_data
                    lot_id = url.split("/")[-1]
                    print(
                        f"[Enricher] Lot {lot_id}: "
                        f"VIN={result.get('full_vin', 'N/A')} | "
                        f"seller={result.get('seller_type', 'N/A')} | "
                        f"avg=${result.get('average_price_usd', 'N/A')}"
                    )
                else:
                    print(f"[Enricher] {url}: iframe znaleziony ale bez danych")
            except Exception as e:
                print(f"[Enricher] Błąd JS dla {url}: {e}")
        else:
            print(f"[Enricher] {url}: brak iframe AutoHelperBot (timeout)")

        try:
            enriched_html = await page.content()
            html_cache_path.write_text(enriched_html, encoding="utf-8")
        except Exception:
            pass

        return result

    async def enrich_lots_batch(self, items: list[tuple[str, Path]]) -> list[dict]:
        """
        Wzbogaca listę lotów danymi z rozszerzeń — jeden kontekst Playwright na cały batch.

        Args:
            items: Lista krotek (url, html_cache_path)

        Returns:
            Lista słowników w tej samej kolejności co items.
        """
        extensions_arg = self._get_extensions_arg()
        if not extensions_arg:
            print("[Enricher] Brak rozszerzeń w ./extensions/ — pomijam wzbogacanie")
            return [{} for _ in items]

        CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        results: list[dict] = [{} for _ in items]

        async with async_playwright() as p:
            context = None
            owns_context = True
            try:
                if keep_browser_open():
                    context = await get_shared_extension_context()
                    owns_context = False
                    print("[Enricher] Używam stałego Chrome z rozszerzeniami")
                else:
                    context = await launch_extension_context(p)
            except Exception as e:
                print(f"[Enricher] Nie udało się uruchomić kontekstu rozszerzeń: {e}")
                return results

            print(f"[Enricher] Batch: wzbogacam {len(items)} lotów...")
            await asyncio.sleep(3)  # Jeden raz na start kontekstu

            try:
                for i, (url, cache_path) in enumerate(items):
                    page = None
                    try:
                        page = await context.new_page()
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        results[i] = await self._extract_from_page(page, url, cache_path)
                    except Exception as e:
                        print(f"[Enricher] Błąd dla {url}: {e}")
                    finally:
                        if page is not None:
                            try:
                                await page.close()
                            except Exception:
                                pass
            finally:
                if owns_context:
                    try:
                        await context.close()
                    except Exception:
                        pass

        return results

    async def enrich_lot(self, url: str, html_cache_path: Path) -> dict:
        """Wzbogaca pojedynczy lot (wrapper dla kompatybilności)."""
        results = await self.enrich_lots_batch([(url, html_cache_path)])
        return results[0]

    async def enrich_all(self, lots: list[tuple[str, Path]]) -> dict[str, dict]:
        """
        Wzbogaca listę lotów i zwraca słownik {url: dane}.

        Args:
            lots: Lista krotek (url, cache_path)

        Returns:
            Słownik {url: {seller_type, full_vin, average_price_usd}}
        """
        results_list = await self.enrich_lots_batch(lots)
        return {url: data for (url, _), data in zip(lots, results_list) if data}
