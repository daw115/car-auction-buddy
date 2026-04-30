"""
Helper do logowania na Copart/IAAI i zapisania sesji.
Uruchom interaktywnie - otwiera się przeglądarka, logujesz się ręcznie,
potem Enter w terminalu zapisuje sesję.

Użycie:
    python3 scraper/login_helper.py copart
    python3 scraper/login_helper.py iaai
"""
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

URLS = {
    "copart": "https://www.copart.com/login/",
    "iaai": "https://login.iaai.com/",
}

STORAGE_DIR = Path("./playwright_profiles")


async def main(site: str):
    if site not in URLS:
        print(f"Nieznana strona {site!r}. Opcje: {list(URLS)}")
        sys.exit(1)

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    out = STORAGE_DIR / f"{site}.json"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        )
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(URLS[site])

        print(f"\nZaloguj się ręcznie w oknie przeglądarki na {site}.")
        input("Gdy jesteś już zalogowany, naciśnij Enter tutaj — zapiszę sesję... ")

        await context.storage_state(path=str(out))
        print(f"Zapisano: {out}")
        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Użycie: python3 scraper/login_helper.py <copart|iaai>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
