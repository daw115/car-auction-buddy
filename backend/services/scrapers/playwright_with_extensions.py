"""
Helper do uruchamiania Playwright z rozszerzeniami Chrome (AutohelperBot, AuctionGate).

UWAGA: Rozszerzenia Chrome NIE DZIAŁAJĄ w trybie headless!
- Wymaga headless=False (widoczna przeglądarka)
- Nie zadziała na Railway (brak GUI)
- Używaj tylko lokalnie do debugowania
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


def get_extension_paths():
    """Zwraca ścieżki do rozszerzeń Chrome."""
    base = Path(__file__).parent.parent.parent.parent / "chrome_extensions"

    autohelperbot = base / "autohelperbot"
    auctiongate = base / "auctiongate"

    # Znajdź katalogi z wersjami (np. 1.0.0_0)
    autohelperbot_version = next(autohelperbot.iterdir()) if autohelperbot.exists() else None
    auctiongate_version = next(auctiongate.iterdir()) if auctiongate.exists() else None

    extensions = []
    if autohelperbot_version and autohelperbot_version.is_dir():
        extensions.append(str(autohelperbot_version))
    if auctiongate_version and auctiongate_version.is_dir():
        extensions.append(str(auctiongate_version))

    return extensions


async def launch_browser_with_extensions(playwright_instance):
    """
    Uruchamia Chromium z załadowanymi rozszerzeniami.

    UWAGA: persistent_context nie wspiera storage_state.
    Musisz zalogować się ręcznie - sesja zostanie zapisana w user_data_dir.

    Args:
        playwright_instance: Instancja playwright (z async_playwright())

    Returns:
        browser_context: Kontekst przeglądarki z rozszerzeniami
    """
    extensions = get_extension_paths()

    if not extensions:
        raise RuntimeError("Nie znaleziono rozszerzeń Chrome w chrome_extensions/")

    print(f"Ładowanie rozszerzeń: {extensions}")

    # Rozszerzenia wymagają persistent context
    # Sesje logowania będą zapisane w user_data_dir automatycznie
    context = await playwright_instance.chromium.launch_persistent_context(
        user_data_dir="/tmp/playwright_chrome_profile",
        headless=False,  # MUSI być False dla rozszerzeń
        args=[
            f"--disable-extensions-except={','.join(extensions)}",
            f"--load-extension={','.join(extensions)}",
            "--disable-blink-features=AutomationControlled",
        ],
        viewport={"width": 1365, "height": 900},
        locale="en-US",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    )

    return context


async def example_copart_with_extensions():
    """Przykład: Copart z rozszerzeniami."""
    async with async_playwright() as p:
        context = await launch_browser_with_extensions(p)

        # Czekaj aż rozszerzenia się załadują
        await asyncio.sleep(3)

        # persistent_context już ma domyślną stronę
        pages = context.pages
        if pages:
            page = pages[0]
        else:
            page = await context.new_page()
            await asyncio.sleep(1)

        try:
            await page.goto("https://www.copart.com/", timeout=60000)
        except Exception as e:
            print(f"Błąd podczas ładowania strony: {e}")
            print("Przeglądarka jest otwarta - możesz ręcznie wejść na stronę.")

        print("\nPrzeglądarka otwarta z rozszerzeniami AutohelperBot i AuctionGate.")
        print("Sprawdź ikony rozszerzeń w prawym górnym rogu Chrome.")
        print("Zaloguj się ręcznie - sesja zostanie zapisana automatycznie.")
        print("\nNaciśnij Enter aby zamknąć...")
        input()

        await context.close()


async def example_iaai_with_extensions():
    """Przykład: IAAI z rozszerzeniami."""
    async with async_playwright() as p:
        context = await launch_browser_with_extensions(p)

        # persistent_context już ma domyślną stronę
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.iaai.com/")

        print("Przeglądarka otwarta z rozszerzeniami.")
        print("Zaloguj się ręcznie - sesja zostanie zapisana automatycznie.")
        print("Naciśnij Enter aby zamknąć...")
        input()

        await context.close()


if __name__ == "__main__":
    print("Wybierz test:")
    print("1. Copart z rozszerzeniami")
    print("2. IAAI z rozszerzeniami")
    choice = input("Wybór (1/2): ").strip()

    if choice == "1":
        asyncio.run(example_copart_with_extensions())
    elif choice == "2":
        asyncio.run(example_iaai_with_extensions())
    else:
        print("Nieprawidłowy wybór")
