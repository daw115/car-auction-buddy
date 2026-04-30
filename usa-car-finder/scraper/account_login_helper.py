"""
Logowanie do Copart/IAAI/AutoHelperBot z danych z .env i zapis sesji.

Uwaga: uruchomienie tego pliku wysyła COPART_EMAIL/COPART_PASSWORD albo
IAAI_EMAIL/IAAI_PASSWORD do zewnętrznych serwisów. Nie wypisuje sekretów.
Sesja jest zapisywana w profilu `CHROME_PROFILE_DIR` używanym przez scraper
oraz w `playwright_profiles/*.json` dla trybu bez rozszerzeń.
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.storage_state import storage_state_path
from scraper.browser_context import launch_extension_context
from scraper.base import BaseScraper

load_dotenv()

CHROME_PROFILE_DIR = Path(os.getenv("CHROME_PROFILE_DIR", "./data/chrome_profile"))
EXTENSION_DIRS = [
    Path("./extensions/auctiongate"),
    Path("./extensions/autohelperbot"),
]

SITES = {
    "copart": {
        "login_url": "https://www.copart.com/login/",
        "email_env": "COPART_EMAIL",
        "password_env": "COPART_PASSWORD",
        "email_selectors": [
            "input[name='username']",
            "input[name='email']",
            "input[type='email']",
            "input[id*='user' i]",
            "input[id*='email' i]",
        ],
        "password_selectors": [
            "input[name='password']",
            "input[type='password']",
            "input[id*='password' i]",
        ],
        "submit_selectors": [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Log In')",
            "button:has-text('Login')",
            "button:has-text('Sign In')",
        ],
    },
    "iaai": {
        "login_url": "https://login.iaai.com/",
        "email_env": "IAAI_EMAIL",
        "password_env": "IAAI_PASSWORD",
        "email_selectors": [
            "input[name='Email']",
            "input[name='email']",
            "input[type='email']",
            "input[id*='email' i]",
            "input[id*='user' i]",
        ],
        "password_selectors": [
            "input[name='Password']",
            "input[name='password']",
            "input[type='password']",
            "input[id*='password' i]",
        ],
        "submit_selectors": [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Log In')",
            "button:has-text('Login')",
            "button:has-text('Sign In')",
        ],
    },
    "autohelperbot": {
        "login_url": "https://autohelperbot.com/en/login",
        "email_env": "AUTOHELPERBOT_EMAIL",
        "password_env": "AUTOHELPERBOT_PASSWORD",
        "fallback_env_pairs": [
            ("AUTOHELPER_EMAIL", "AUTOHELPER_PASSWORD"),
            ("HELPERBOT_EMAIL", "HELPERBOT_PASSWORD"),
            ("COPART_EMAIL", "COPART_PASSWORD"),
            ("IAAI_EMAIL", "IAAI_PASSWORD"),
        ],
        "email_selectors": [
            "input[name='email']",
            "input[type='email']",
            "input[id*='email' i]",
            "input[name='username']",
            "input[id*='login' i]",
        ],
        "password_selectors": [
            "input[name='password']",
            "input[type='password']",
            "input[id*='password' i]",
        ],
        "submit_selectors": [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Sign in')",
            "button:has-text('Log in')",
            "button:has-text('Login')",
        ],
    },
}


def site_credentials(cfg: dict) -> tuple[str, str, str]:
    pairs = [(cfg["email_env"], cfg["password_env"]), *cfg.get("fallback_env_pairs", [])]
    for email_key, password_key in pairs:
        email = os.getenv(email_key, "").strip()
        password = os.getenv(password_key, "").strip()
        if email and password:
            return email, password, f"{email_key}/{password_key}"
    return "", "", ""


def extension_args() -> list[str]:
    existing = [str(path.resolve()) for path in EXTENSION_DIRS if path.exists() and any(path.iterdir())]
    if not existing:
        return []
    extensions = ",".join(existing)
    return [
        f"--disable-extensions-except={extensions}",
        f"--load-extension={extensions}",
    ]


async def has_security_challenge(page: Page) -> bool:
    return BaseScraper.text_has_security_challenge(await page.content())


async def first_visible(page: Page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = await locator.count()
        except Exception:
            continue
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if await candidate.is_visible(timeout=1000):
                    return candidate
            except Exception:
                continue
    return None


async def login_site(context: BrowserContext, site: str) -> bool:
    cfg = SITES[site]
    email, password, credential_source = site_credentials(cfg)

    page = await context.new_page()
    await page.goto(cfg["login_url"], wait_until="domcontentloaded", timeout=45000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    if await has_security_challenge(page):
        wait_seconds = int(os.getenv(f"{site.upper()}_SECURITY_WAIT_SECONDS", "0"))
        if wait_seconds > 0:
            print(f"[{site}] Security check/CAPTCHA przed logowaniem - czekam {wait_seconds}s.")
            for _ in range(wait_seconds):
                await asyncio.sleep(1)
                if not await has_security_challenge(page):
                    break
        if await has_security_challenge(page):
            print(f"[{site}] Security check/CAPTCHA przed logowaniem - dokończ ręcznie w oknie.")
            input(f"[{site}] Po przejściu security check naciśnij Enter tutaj...")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            if await has_security_challenge(page):
                print(f"[{site}] Security check nadal aktywny - nie zapisuję sesji jako zalogowanej.")
                return False

    if not email or not password:
        print(f"[{site}] Brak danych w .env - zaloguj ręcznie w otwartym oknie.")
        input(f"[{site}] Po ręcznym zalogowaniu naciśnij Enter tutaj...")
        await context.storage_state(path=str(storage_state_path(site)))
        print(f"[{site}] Sesja zapisana")
        return True

    if credential_source != f"{cfg['email_env']}/{cfg['password_env']}":
        print(f"[{site}] Używam alternatywnego źródła danych: {credential_source}")

    if site == "autohelperbot":
        for selector in ["a:has-text('E-MAIL')", "text=E-MAIL", "span:has-text('E-MAIL')"]:
            try:
                email_tab = page.locator(selector).first
                if await email_tab.is_visible(timeout=1500):
                    await email_tab.click()
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue

    email_input = await first_visible(page, cfg["email_selectors"])
    password_input = await first_visible(page, cfg["password_selectors"])

    if email_input is None or password_input is None:
        print(f"[{site}] Nie znalazłem formularza logowania - dokończ ręcznie w oknie.")
        input(f"[{site}] Po ręcznym zalogowaniu naciśnij Enter tutaj...")
        await context.storage_state(path=str(storage_state_path(site)))
        return True

    await email_input.fill(email)
    await password_input.fill(password)

    submit_selectors = cfg["submit_selectors"]
    if site == "autohelperbot":
        submit_selectors = [
            ".mfp-wrap input[type='submit']",
            ".mfp-wrap button[type='submit']",
            ".mfp-wrap input[value*='Next' i]",
            *submit_selectors,
        ]

    submit = await first_visible(page, submit_selectors)
    if submit is None:
        await password_input.press("Enter")
    else:
        await submit.click()

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(8)

    if await has_security_challenge(page):
        print(f"[{site}] Security check/CAPTCHA po wysłaniu danych - dokończ ręcznie w oknie.")
        input(f"[{site}] Po ręcznym zalogowaniu naciśnij Enter tutaj...")

    try:
        body_text = (await page.locator("body").inner_text(timeout=3000)).lower()
    except Exception:
        body_text = ""
    if "these credentials do not match" in body_text or "credentials do not match" in body_text:
        print(f"[{site}] Serwis odrzucił login/hasło - nie zapisuję sesji jako zalogowanej")
        return False

    await context.storage_state(path=str(storage_state_path(site)))
    print(f"[{site}] Sesja zapisana")
    return True


async def launch_login_context(playwright: Playwright) -> BrowserContext:
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    if os.getenv("USE_EXTENSIONS", "false").lower() == "true":
        return await launch_extension_context(playwright)

    launch_kwargs = {
        "user_data_dir": str(CHROME_PROFILE_DIR),
        "headless": False,
        "slow_mo": int(os.getenv("SLOW_MO_MS", "1500")),
        "viewport": {"width": 1365, "height": 900},
        "locale": "en-US",
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "args": ["--no-sandbox"],
        "timeout": int(os.getenv("BROWSER_LAUNCH_TIMEOUT_MS", "90000")),
    }
    browser_channel = os.getenv("BROWSER_CHANNEL", "chromium").strip()
    browser_executable_path = os.getenv("BROWSER_EXECUTABLE_PATH", "").strip()
    if browser_executable_path:
        launch_kwargs["executable_path"] = browser_executable_path
    elif browser_channel and browser_channel.lower() != "chromium":
        launch_kwargs["channel"] = browser_channel

    return await playwright.chromium.launch_persistent_context(**launch_kwargs)


async def main() -> None:
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    requested_sites = [arg.lower() for arg in sys.argv[1:] if arg.lower() in SITES]
    sites = requested_sites or ["copart", "iaai"]

    async with async_playwright() as p:
        context = await launch_login_context(p)

        try:
            for site in sites:
                try:
                    await login_site(context, site)
                except Exception as exc:
                    print(f"[{site}] Logowanie nie powiodło się: {exc}")
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
