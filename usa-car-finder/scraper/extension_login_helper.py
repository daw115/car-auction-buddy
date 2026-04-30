"""
Helper do logowania do rozszerzeń Chromium (AuctionGate i AutoHelperBot).
Uruchom raz, zaloguj się ręcznie, sesja zostanie zapisana w profilu
skonfigurowanym przez CHROME_PROFILE_DIR.

Użycie:
    python3 scraper/extension_login_helper.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.browser_context import CHROME_PROFILE_DIR, extension_paths, launch_extension_context

AUTOHELPERBOT_POPUP_URL = "chrome-extension://fojpkmgahmlajoheocnkebaoodepoekj/index.html"
AUCTIONGATE_POPUP_URL = "chrome-extension://ehpiejnmbdjkaplmbafaejdhodalfbie/template/popup/auth.html"


async def get_loaded_extension_names(page) -> list[str]:
    await page.goto("chrome://extensions", wait_until="domcontentloaded", timeout=10000)
    await page.wait_for_timeout(1000)
    return await page.evaluate(
        """
        () => {
            const manager = document.querySelector('extensions-manager');
            const managerRoot = manager && manager.shadowRoot;
            const list = managerRoot && managerRoot.querySelector('extensions-item-list');
            const listRoot = list && list.shadowRoot;
            const items = listRoot ? Array.from(listRoot.querySelectorAll('extensions-item')) : [];
            return items
                .map(item => item.shadowRoot?.querySelector('#name')?.textContent?.trim())
                .filter(Boolean);
        }
        """
    )


async def open_optional_page(context, url: str, label: str):
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=10000)
        print(f"Otwarto: {label}")
        return page
    except Exception as exc:
        print(f"Nie udało się otworzyć {label}: {exc}")
        try:
            await page.close()
        except Exception:
            pass
        return None


async def login_to_extensions():
    from playwright.async_api import async_playwright

    existing = extension_paths()
    if not existing:
        print("✗ Brak poprawnych rozszerzeń w ./extensions/")
        return

    print(f"Ładuję rozszerzenia: {len(existing)} szt.")

    async with async_playwright() as p:
        context = await launch_extension_context(p)

        extensions_page = await context.new_page()
        await asyncio.sleep(2)
        loaded_names = await get_loaded_extension_names(extensions_page)
        print(f"Rozszerzenia widoczne w chrome://extensions: {', '.join(loaded_names) or 'brak'}")

        page = await context.new_page()
        await page.goto("https://www.copart.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        await open_optional_page(context, AUTOHELPERBOT_POPUP_URL, "popup AutoHelperBot")
        await open_optional_page(context, AUCTIONGATE_POPUP_URL, "popup AuctionGate")

        print("\n" + "=" * 60)
        print("ZALOGUJ SIĘ DO ROZSZERZEŃ:")
        print("=" * 60)
        print("1. Karta chrome://extensions powinna pokazywać AutohelperBot i AuctionGate.")
        print("2. Użyj otwartej karty AutoHelperBot i zaloguj się, jeśli pokazuje formularz.")
        print("3. AuctionGate zwykle loguje się z panelu wstrzykniętego na Copart/IAAI;")
        print("   jeśli popup jest zablokowany, użyj otwartej karty Copart i panelu rozszerzenia.")
        print("4. Sprawdź że rozszerzenia działają otwierając jakiś lot na Copart.")
        print("5. Gdy gotowe - naciśnij ENTER aby zapisać sesję.")
        print("=" * 60)

        input()

        print(f"✓ Sesja zapisana w {CHROME_PROFILE_DIR}/")
        print("  Rozszerzenia będą działać przy następnym uruchomieniu enrichera.")
        await context.close()


if __name__ == "__main__":
    asyncio.run(login_to_extensions())
