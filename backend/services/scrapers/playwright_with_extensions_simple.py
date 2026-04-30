"""
Uproszczona wersja - uruchamia Chrome z rozszerzeniami bez persistent_context.
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


def get_extension_paths():
    """Zwraca ścieżki do rozszerzeń Chrome."""
    base = Path(__file__).parent.parent.parent.parent / "chrome_extensions"

    autohelperbot = base / "autohelperbot"
    auctiongate = base / "auctiongate"

    autohelperbot_version = next(autohelperbot.iterdir()) if autohelperbot.exists() else None
    auctiongate_version = next(auctiongate.iterdir()) if auctiongate.exists() else None

    extensions = []
    if autohelperbot_version and autohelperbot_version.is_dir():
        extensions.append(str(autohelperbot_version))
    if auctiongate_version and auctiongate_version.is_dir():
        extensions.append(str(auctiongate_version))

    return extensions


async def test_copart():
    """Test Copart z rozszerzeniami."""
    extensions = get_extension_paths()

    if not extensions:
        print("Błąd: Nie znaleziono rozszerzeń w chrome_extensions/")
        return

    print(f"Ładowanie rozszerzeń: {extensions}")

    async with async_playwright() as p:
        # Standardowy launch z argumentami dla rozszerzeń
        browser = await p.chromium.launch(
            headless=False,
            args=[
                f"--disable-extensions-except={','.join(extensions)}",
                f"--load-extension={','.join(extensions)}",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1365, "height": 900},
            locale="en-US",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        )

        page = await context.new_page()

        print("\nOtwieranie Copart...")
        await page.goto("https://www.copart.com/", timeout=60000)

        print("\n✓ Przeglądarka otwarta z rozszerzeniami AutohelperBot i AuctionGate")
        print("✓ Sprawdź ikony rozszerzeń w prawym górnym rogu Chrome")
        print("✓ Zaloguj się ręcznie jeśli potrzebujesz")
        print("\nNaciśnij Enter aby zamknąć...")
        input()

        await browser.close()


async def test_iaai():
    """Test IAAI z rozszerzeniami."""
    extensions = get_extension_paths()

    if not extensions:
        print("Błąd: Nie znaleziono rozszerzeń w chrome_extensions/")
        return

    print(f"Ładowanie rozszerzeń: {extensions}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                f"--disable-extensions-except={','.join(extensions)}",
                f"--load-extension={','.join(extensions)}",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1365, "height": 900},
            locale="en-US",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        )

        page = await context.new_page()

        print("\nOtwieranie IAAI...")
        await page.goto("https://www.iaai.com/", timeout=60000)

        print("\n✓ Przeglądarka otwarta z rozszerzeniami AutohelperBot i AuctionGate")
        print("✓ Sprawdź ikony rozszerzeń w prawym górnym rogu Chrome")
        print("✓ Zaloguj się ręcznie jeśli potrzebujesz")
        print("\nNaciśnij Enter aby zamknąć...")
        input()

        await browser.close()


if __name__ == "__main__":
    print("Wybierz test:")
    print("1. Copart z rozszerzeniami")
    print("2. IAAI z rozszerzeniami")
    choice = input("Wybór (1/2): ").strip()

    if choice == "1":
        asyncio.run(test_copart())
    elif choice == "2":
        asyncio.run(test_iaai())
    else:
        print("Nieprawidłowy wybór")
