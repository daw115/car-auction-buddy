"""Jednorazowy warmup sesji bidfax.info.

Uruchamiasz raz, ręcznie klikasz "Verify you are human", wciskasz ENTER.
Cookies z CF clearance zapisują się w persistent profile
(data/chrome_profile_bidfax/) — kolejne lookupy idą programatycznie bez
challenge.

Powtórz gdy bidfax znowu blokuje (zwykle co 1-7 dni).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

try:
    from playwright_stealth import Stealth
    _STEALTH_OK = True
except ImportError:
    _STEALTH_OK = False


PROFILE_DIR = Path(os.getenv("BIDFAX_CHROME_PROFILE_DIR", "data/chrome_profile_bidfax"))
CHROME_EXEC = os.getenv(
    "CHROME_EXECUTABLE_PATH",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


async def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    launch_kwargs: dict = {
        "headless": False,
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1365, "height": 900},
        "locale": "en-US",
        "ignore_default_args": [
            "--enable-automation",
            "--enable-blink-features=IdleDetection",
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    if Path(CHROME_EXEC).exists():
        launch_kwargs["executable_path"] = CHROME_EXEC
        print(f"[warmup] using real Chrome at {CHROME_EXEC}")
    else:
        print("[warmup] real Chrome nie znaleziona, używam bundled Chromium")

    print(f"[warmup] profile dir: {PROFILE_DIR}")
    print(f"[warmup] stealth: {'enabled' if _STEALTH_OK else 'DISABLED (pip install playwright-stealth)'}")
    print()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            **launch_kwargs,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        if _STEALTH_OK:
            await Stealth().apply_stealth_async(page)

        print("[warmup] otwieram https://bidfax.info ...")
        await page.goto("https://bidfax.info", wait_until="domcontentloaded", timeout=30000)

        print()
        print("=" * 60)
        print("INSTRUKCJA RĘCZNA:")
        print("=" * 60)
        print("1. Spójrz na otwarte okno Chrome.")
        print("2. Kliknij checkbox 'Verify you are human' (jeśli go widzisz).")
        print("3. Poczekaj aż strona przeładuje się do normalnej bidfax.info")
        print("   (z polem wyszukiwania '#search' na środku).")
        print("4. Wróć do TEGO terminala i wciśnij ENTER żeby zapisać profil.")
        print("=" * 60)
        print()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input, ">>> ENTER gdy CF przeszedł: ")

        try:
            content = await page.content()
        except Exception:
            content = ""
        cf_markers = [
            "Verify you are human",
            "Performing security verification",
            "challenge-form",
            "cf_chl",
        ]
        still_blocked = any(m in content for m in cf_markers)
        has_search = 'id="search"' in content

        print()
        print(f"[warmup] CF markers w HTML: {'TAK (niedobrze)' if still_blocked else 'BRAK (OK)'}")
        print(f"[warmup] '#search' input widoczny: {'TAK (OK)' if has_search else 'NIE'}")

        try:
            await context.storage_state(path=str(PROFILE_DIR / "storage_state.json"))
            print(f"[warmup] storage_state zapisany: {PROFILE_DIR / 'storage_state.json'}")
        except Exception as exc:
            print(f"[warmup] storage_state save error: {exc}")

        await context.close()

    print()
    if still_blocked or not has_search:
        print("[warmup] OSTRZEŻENIE: CF nie wygląda na przejście. Spróbuj raz jeszcze.")
        sys.exit(1)
    else:
        print("[warmup] OK — profil gotowy. Teraz odpal:")
        print("  BIDFAX_ENRICHMENT_ENABLED=true python3 test_bidfax_real.py")


if __name__ == "__main__":
    asyncio.run(main())
