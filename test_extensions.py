"""
Test rozszerzeń Chrome - robi screenshot i zapisuje do pliku.
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


async def test_copart():
    extensions = get_extension_paths()
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
        print("Otwieranie Copart...")
        await page.goto("https://www.copart.com/", timeout=60000)

        # Czekaj 5 sekund na załadowanie rozszerzeń
        await asyncio.sleep(5)

        # Zrób screenshot
        screenshot_path = "/tmp/copart_extensions_test.png"
        await page.screenshot(path=screenshot_path, full_page=False)
        print(f"\n✓ Screenshot zapisany: {screenshot_path}")

        # Czekaj jeszcze 5 sekund żeby zobaczyć
        await asyncio.sleep(5)

        await browser.close()
        print(f"\n✓ Test zakończony. Sprawdź screenshot: {screenshot_path}")


if __name__ == "__main__":
    asyncio.run(test_copart())
