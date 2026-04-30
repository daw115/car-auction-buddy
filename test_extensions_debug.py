"""
Test z logowaniem błędów konsoli Chrome.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


def get_extension_paths():
    base = Path(__file__).parent / "chrome_extensions"
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


async def test_with_console_logs():
    extensions = get_extension_paths()
    print(f"Ładowanie rozszerzeń: {extensions}\n")

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

        # Przechwytuj błędy konsoli
        console_messages = []
        page.on("console", lambda msg: console_messages.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: print(f"❌ Błąd strony: {err}"))

        print("Otwieranie Copart...")
        await page.goto("https://www.copart.com/", timeout=60000)
        await asyncio.sleep(5)

        # Wypisz błędy konsoli
        print("\n=== LOGI KONSOLI ===")
        for msg in console_messages:
            if "error" in msg.lower() or "failed" in msg.lower():
                print(f"❌ {msg}")
            else:
                print(f"ℹ️  {msg}")

        # Sprawdź czy rozszerzenia są załadowane
        print("\n=== SPRAWDZANIE ROZSZERZEŃ ===")
        extensions_loaded = await page.evaluate("""
            () => {
                // Sprawdź czy content scripts dodały coś do DOM
                const hasAutohelper = document.querySelector('[data-autohelperbot]') !== null;
                const hasAuctiongate = document.querySelector('[data-auctiongate]') !== null;

                return {
                    autohelperbot: hasAutohelper,
                    auctiongate: hasAuctiongate,
                    bodyClasses: document.body.className,
                    scripts: Array.from(document.scripts).map(s => s.src).filter(s => s.includes('chrome-extension'))
                };
            }
        """)

        print(f"AutohelperBot wykryty: {extensions_loaded['autohelperbot']}")
        print(f"AuctionGate wykryty: {extensions_loaded['auctiongate']}")
        print(f"Klasy body: {extensions_loaded['bodyClasses']}")
        print(f"Skrypty rozszerzeń: {extensions_loaded['scripts']}")

        await asyncio.sleep(5)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_with_console_logs())
