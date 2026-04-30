import asyncio
import hashlib
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from playwright.async_api import Page
from dotenv import load_dotenv

load_dotenv(override=True)

HTML_CACHE_DIR = Path(os.getenv("HTML_CACHE_DIR", "./data/html_cache"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO_MS = int(os.getenv("SLOW_MO_MS", "1500"))
FORCE_REFRESH = os.getenv("FORCE_REFRESH", "true").lower() == "true"
CACHE_MAX_AGE_HOURS = int(os.getenv("CACHE_MAX_AGE_HOURS", "24"))
BLOCK_MEDIA_ASSETS = os.getenv("BLOCK_MEDIA_ASSETS", "false").lower() == "true"
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome").strip() or None
BROWSER_EXECUTABLE_PATH = os.getenv("BROWSER_EXECUTABLE_PATH", "").strip()
CHROME_EXECUTABLE_PATH = os.getenv(
    "CHROME_EXECUTABLE_PATH",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
SECURITY_CHALLENGE_MARKERS = (
    "additional security check is required",
    "hcaptcha",
    "why am i seeing this page",
    "verify that an actual human",
    "verify you are human",
    "protected and accelerated by",
    "checking if the site connection is secure",
    "checking your browser",
    "enable javascript and cookies to continue",
    "request unsuccessful",
    "incident id",
)
SECURITY_CHALLENGE_SOFT_MARKERS = (
    "i am human",
    "imperva",
    "incapsula",
    "_incapsula_",
)

EXTENSION_DATA_JS = """
() => {
    const text = document.body ? document.body.innerText : "";
    const result = {};

    const vinMatch = text.match(/VIN(?: code)?[:\\s]*([A-HJ-NPR-Z0-9]{17})/i);
    if (vinMatch) result.full_vin = vinMatch[1];

    const sellerMatch = text.match(/Who\\s*sell[s:]?\\s*:?[\\s\\n]*(Insurance|Dealer|Seller|Owner)/i)
        || text.match(/Seller[:\\s]*(Insurance|Dealer|Seller|Owner)/i);
    if (sellerMatch) {
        const seller = sellerMatch[1].toLowerCase();
        result.seller_type = seller === "insurance" ? "insurance" : "dealer";
    }

    const reserveMatch = text.match(/Seller reserve[:\\s]*\\$?([\\d,\\s]+)/i)
        || text.match(/Reserve price[:\\s]*\\$?([\\d,\\s]+)/i);
    if (reserveMatch) {
        result.seller_reserve_usd = Number(reserveMatch[1].replace(/[,\\s]/g, ""));
    }

    const deliveryMatch = text.match(/(?:Delivery|Transport|Towing)[^$]{0,40}\\$([\\d,\\s]+)/i);
    if (deliveryMatch) {
        result.delivery_cost_estimate_usd = Number(deliveryMatch[1].replace(/[,\\s]/g, ""));
    }

    const avgPriceMatch = text.match(/Average price[:\\s]*\\$([\\d,\\s]+)/i);
    if (avgPriceMatch) {
        result.average_price_usd = Number(avgPriceMatch[1].replace(/[,\\s]/g, ""));
    }

    return result;
}
"""


def _clean_extension_payload(data: dict) -> dict:
    useful = {
        key: value
        for key, value in (data or {}).items()
        if value not in (None, "", 0, 0.0)
    }
    if useful:
        useful["enriched_by_extension"] = True
    return useful


@dataclass
class ListingCandidate:
    url: str
    lot_id: str
    seller_type: Optional[str] = None
    auction_date: Optional[str] = None
    damage_text: Optional[str] = None
    damage_score: Optional[int] = None
    damage_label: Optional[str] = None
    row_text: str = ""
    raw_data: dict = field(default_factory=dict)


class BaseScraper:
    def __init__(self, source_name: str):
        self.source_name = source_name
        self.cache_dir = HTML_CACHE_DIR / source_name
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_listing_metadata: dict[str, dict] = {}

    def get_cache_path(self, url: str) -> Path:
        url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
        return self.cache_dir / f"{url_hash}.html"

    @staticmethod
    def browser_launch_kwargs() -> dict:
        """Common browser launch options for non-extension scraping."""
        launch_kwargs = {
            "headless": HEADLESS,
            "slow_mo": SLOW_MO_MS,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if BROWSER_EXECUTABLE_PATH:
            launch_kwargs["executable_path"] = BROWSER_EXECUTABLE_PATH
        elif BROWSER_CHANNEL and BROWSER_CHANNEL.lower() != "chromium":
            launch_kwargs["channel"] = BROWSER_CHANNEL
        return launch_kwargs

    def is_cached(self, url: str) -> bool:
        force_refresh = os.getenv("FORCE_REFRESH", "false").lower() == "true"
        cache_max_age_hours = int(os.getenv("CACHE_MAX_AGE_HOURS", str(CACHE_MAX_AGE_HOURS)))

        if force_refresh:
            return False

        path = self.get_cache_path(url)
        if not path.exists():
            return False

        try:
            if self.text_has_security_challenge(path.read_text(encoding="utf-8", errors="ignore")):
                return False
        except Exception:
            return False

        if cache_max_age_hours <= 0:
            return True

        age_hours = (time.time() - path.stat().st_mtime) / 3600
        return age_hours <= cache_max_age_hours

    def save_html(self, url: str, html: str) -> Path:
        path = self.get_cache_path(url)
        path.write_text(html, encoding="utf-8")
        return path

    def load_html(self, url: str) -> str:
        return self.get_cache_path(url).read_text(encoding="utf-8")

    @staticmethod
    def format_utc(dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def datetime_from_auction_date(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None

        date_str = value.strip()
        try:
            if date_str.endswith("Z"):
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            elif "T" in date_str:
                dt = datetime.fromisoformat(date_str)
            elif len(date_str) == 10:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=23, minute=59, tzinfo=timezone.utc
                )
            else:
                dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
        except Exception:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @classmethod
    def auction_date_in_window(
        cls,
        auction_date: Optional[str],
        min_hours: Optional[int],
        max_hours: Optional[int],
    ) -> bool:
        if max_hours is None:
            return True

        min_hours = min_hours or 0
        if min_hours > max_hours:
            min_hours, max_hours = max_hours, min_hours

        auction_dt = cls.datetime_from_auction_date(auction_date)
        if auction_dt is None:
            return False

        now = datetime.now(timezone.utc)
        return now + timedelta(hours=min_hours) <= auction_dt <= now + timedelta(hours=max_hours)

    @classmethod
    def auction_sort_key(cls, auction_date: Optional[str]) -> datetime:
        return cls.datetime_from_auction_date(auction_date) or datetime.max.replace(tzinfo=timezone.utc)

    @staticmethod
    def damage_text_from_values(*values) -> str:
        parts = []
        for value in values:
            if value in (None, "", [], {}):
                continue
            text = re.sub(r"\s+", " ", str(value)).strip()
            if text:
                parts.append(text)
        return " | ".join(parts)

    @classmethod
    def damage_severity_score(cls, damage_text: Optional[str]) -> tuple[int, str]:
        """
        Zwraca priorytet uszkodzeń dla sortowania listy.

        Niższy wynik = łagodniejsze uszkodzenie i wyższy priorytet do otwarcia.
        """
        text = (damage_text or "").lower()
        if not text:
            return 60, "unknown"

        damage_buckets = [
            (100, "fire/flood", ("fire", "burn", "flood", "water")),
            (95, "rollover/all-over", ("rollover", "all over")),
            (88, "structural", ("frame", "structural")),
            (80, "undercarriage", ("undercarriage",)),
            (72, "mechanical", ("mechanical", "engine damage", "transmission")),
            (62, "front", ("front end", "front")),
            (50, "side/rear", ("rear end", "rear", "side")),
            (36, "vandalism/theft", ("vandalism", "theft")),
            (28, "hail", ("hail",)),
            (16, "minor", ("minor dent", "scratches", "scratch", "dent", "normal wear")),
        ]

        matches: list[tuple[int, str]] = []
        for score, label, markers in damage_buckets:
            if any(marker in text for marker in markers):
                matches.append((score, label))

        if not matches:
            return 55, "other"

        score, label = max(matches, key=lambda item: item[0])
        if len(matches) > 1 and score < 90:
            score += 5
            label = f"{label}+secondary"
        return min(score, 100), label

    @classmethod
    def candidate_sort_key(cls, candidate: ListingCandidate):
        damage_score = candidate.damage_score
        if damage_score is None:
            damage_score, _ = cls.damage_severity_score(candidate.damage_text)
        return (
            damage_score,
            cls.auction_sort_key(candidate.auction_date),
            candidate.lot_id or "",
        )

    @classmethod
    def damage_has_excluded_type(cls, damage_text: Optional[str], excluded_damage_types: list[str]) -> bool:
        text = (damage_text or "").lower()
        if not text:
            return False

        aliases = {
            "flood": ("flood", "water"),
            "water": ("flood", "water"),
            "fire": ("fire", "burn"),
            "frame": ("frame", "structural"),
            "structural": ("frame", "structural"),
        }

        for excluded in excluded_damage_types or []:
            key = excluded.strip().lower()
            markers = aliases.get(key, (key,))
            if any(marker and marker in text for marker in markers):
                return True
        return False

    def get_detail_scan_limit(self, requested_max_results: int) -> int:
        """Wylicza ile stron szczegółów pobrać z jednego źródła."""
        per_source_limit = max(1, int(os.getenv("MAX_RESULTS_PER_SOURCE", "100")))
        strict_threshold = max(0, int(os.getenv("STRICT_SCAN_MAX_RESULTS_THRESHOLD", "3")))
        requested = max(1, requested_max_results or per_source_limit)

        if strict_threshold and requested <= strict_threshold:
            return min(per_source_limit, requested)

        multiplier = max(1, int(os.getenv("SEARCH_DETAIL_MULTIPLIER", "4")))
        return min(per_source_limit, requested * multiplier)

    async def random_delay(self, min_s: float = 2.0, max_s: float = 5.0):
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def setup_page(self, page: Page):
        await page.set_extra_http_headers({
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        if BLOCK_MEDIA_ASSETS:
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,otf}",
                lambda route: route.abort()
            )

    @staticmethod
    def text_has_security_challenge(text: str) -> bool:
        html = (text or "").lower()
        if any(marker in html for marker in SECURITY_CHALLENGE_MARKERS):
            return True
        return any(marker in html for marker in SECURITY_CHALLENGE_SOFT_MARKERS) and any(
            context in html
            for context in (
                "captcha",
                "security check",
                "why am i seeing this page",
                "protected and accelerated by",
                "verify that an actual human",
                "verify you are human",
                "checking if the site connection is secure",
                "checking your browser",
                "enable javascript and cookies to continue",
            )
        )

    async def has_security_challenge(self, page: Page) -> bool:
        return self.text_has_security_challenge(await page.content())

    async def wait_for_security_challenge_clear(self, page: Page, timeout_s: int = 0) -> bool:
        """Czeka, aż użytkownik ręcznie przejdzie CAPTCHA/security check w widocznym oknie."""
        if not await self.has_security_challenge(page):
            return True

        if timeout_s <= 0:
            return False

        print(
            f"[{self.source_name.upper()}] Wykryto security check/CAPTCHA. "
            f"Masz {timeout_s}s na ręczne przejście w otwartym oknie."
        )
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            await asyncio.sleep(2)
            if not await self.has_security_challenge(page):
                print(f"[{self.source_name.upper()}] Security check zakończony - kontynuuję.")
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                await asyncio.sleep(3)
                return True

        print(f"[{self.source_name.upper()}] Security check nadal aktywny po {timeout_s}s.")
        return False

    async def wait_for_detail_data(self, page: Page):
        """Daje czas na doładowanie danych dynamicznych i lazy-load mediów."""
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass

        # Przewiń stronę, aby uruchomić lazy-load zdjęć/metadanych.
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.2)
            await page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass

        await asyncio.sleep(2.0)

    async def wait_for_extensions(self, page: Page, timeout_s: int = 15) -> bool:
        """Czeka, aż AutoHelperBot/AuctionGate wstrzykną iframe."""
        if os.getenv("USE_EXTENSIONS", "false").lower() != "true":
            return False

        print(f"[Scraper] Czekam na iframe z rozszerzeń (max {timeout_s}s)...")

        for i in range(timeout_s):
            frames = page.frames
            for frame in frames:
                frame_url = frame.url.lower()
                if "autohelperbot.com" in frame_url or "auctiongate" in frame_url:
                    print(f"[Scraper] ✅ Znaleziono iframe: {frame.url}")
                    return True

            await asyncio.sleep(1)

        print(f"[Scraper] ⏱ Timeout - brak iframe po {timeout_s}s")
        return False

    async def extract_extension_data(self, page: Page, timeout_s: int = 20) -> dict:
        """Czyta dane bezpośrednio z iframe rozszerzenia, bo page.content() ich nie zapisuje."""
        if os.getenv("USE_EXTENSIONS", "false").lower() != "true":
            return {}

        for _ in range(timeout_s):
            for frame in page.frames:
                frame_url = frame.url.lower()
                if "autohelperbot.com" not in frame_url and "auctiongate" not in frame_url:
                    continue

                try:
                    data = await frame.evaluate(EXTENSION_DATA_JS)
                except Exception:
                    continue

                if not data:
                    continue

                useful = _clean_extension_payload(data)
                if useful:
                    print(
                        "[Scraper] Dane z bota: "
                        f"seller={useful.get('seller_type', 'unknown')} "
                        f"vin={useful.get('full_vin', 'brak')}"
                    )
                    return useful

            await asyncio.sleep(1)

        print("[Scraper] Iframe bota jest, ale nie udało się odczytać danych")
        return {}

    def autohelperbot_detail_url(self, lot_id: str) -> Optional[str]:
        lot_id = re.sub(r"\D+", "", str(lot_id or ""))
        if not lot_id:
            return None
        if self.source_name == "iaai":
            return (
                f"https://autohelperbot.com/iaai_lot/{lot_id}/"
                "?type=ns&lang=en&autohelperbot_app=1.0&jsonp=false"
            )
        if self.source_name == "copart":
            return (
                f"https://autohelperbot.com/copart_lot/{lot_id}/"
                "?lang=en&v=2&autohelperbot_app=1.0&jsonp=false"
            )
        return None

    async def extract_autohelperbot_direct(self, page: Page, lot_id: str, timeout_s: int = 20) -> dict:
        """Fallback: otwiera stronę AutoHelperBot bezpośrednio w tym samym profilu przeglądarki."""
        if (
            os.getenv("USE_EXTENSIONS", "false").lower() != "true"
            and os.getenv("AUTOHELPERBOT_DIRECT_ENABLED", "false").lower() != "true"
        ):
            return {}

        url = self.autohelperbot_detail_url(lot_id)
        if not url:
            return {}

        bot_page = await page.context.new_page()
        try:
            print(f"[Scraper] Fallback AutoHelperBot direct: lot {lot_id}")

            await self._login_autohelperbot_if_configured(bot_page)

            try:
                await bot_page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                print(f"[Scraper] AutoHelperBot direct: domcontentloaded timeout, próbuję odczytać stronę ({exc})")
                try:
                    await bot_page.goto(url, wait_until="commit", timeout=15000)
                except Exception:
                    pass
            try:
                await bot_page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            for _ in range(timeout_s):
                try:
                    data = await bot_page.evaluate(EXTENSION_DATA_JS)
                except Exception:
                    data = {}

                useful = _clean_extension_payload(data)
                if useful:
                    useful["extension_source"] = "autohelperbot_direct"
                    print(
                        "[Scraper] Dane z AutoHelperBot direct: "
                        f"seller={useful.get('seller_type', 'unknown')} "
                        f"vin={useful.get('full_vin', 'brak')}"
                    )
                    return useful
                await asyncio.sleep(1)
        except Exception as exc:
            print(f"[Scraper] AutoHelperBot direct nie zwrócił danych: {exc}")
        finally:
            try:
                await bot_page.close()
            except Exception:
                pass

        return {}

    async def _login_autohelperbot_if_configured(self, page: Page) -> bool:
        email = os.getenv("AUTOHELPERBOT_EMAIL", "").strip()
        password = os.getenv("AUTOHELPERBOT_PASSWORD", "").strip()
        if not email or not password:
            return False

        try:
            await page.goto("https://autohelperbot.com/en/login", wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            print(f"[Scraper] AutoHelperBot login: nie udało się otworzyć logowania ({exc})")
            return False

        email_input = await self._first_visible_on_page(
            page,
            [
                "input[type='email']",
                "input[name*='email' i]",
                "input[id*='email' i]",
                "input[name*='login' i]",
                "input[id*='login' i]",
            ],
        )
        password_input = await self._first_visible_on_page(
            page,
            [
                "input[type='password']",
                "input[name*='password' i]",
                "input[id*='password' i]",
            ],
        )

        if email_input is None or password_input is None:
            print("[Scraper] AutoHelperBot login: formularz niewidoczny, zakładam aktywną sesję")
            return False

        await email_input.fill(email)
        await password_input.fill(password)
        submit = await self._first_visible_on_page(
            page,
            [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Log in')",
                "button:has-text('Login')",
                "button:has-text('Sign in')",
                "button:has-text('Sign In')",
            ],
        )
        if submit is None:
            await password_input.press("Enter")
        else:
            await submit.click()

        wait_seconds = int(os.getenv("AUTOHELPERBOT_POST_LOGIN_WAIT_SECONDS", "5"))
        print(f"[Scraper] AutoHelperBot login: czekam {wait_seconds}s po logowaniu")
        await asyncio.sleep(wait_seconds)
        return True

    @staticmethod
    async def _first_visible_on_page(page: Page, selectors: list[str]):
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

    async def extract_bot_data_for_lot(self, page: Page, lot_id: str) -> dict:
        iframe_wait = int(os.getenv("EXTENSION_IFRAME_WAIT_SECONDS", "15"))
        plugins_ready = await self.wait_for_extensions(page, timeout_s=iframe_wait)
        if plugins_ready:
            extension_data = await self.extract_extension_data(page)
            if extension_data:
                return extension_data
        else:
            print("[Scraper] Pluginy nie zwróciły danych w limicie")

        direct_wait = int(os.getenv("AUTOHELPERBOT_DIRECT_WAIT_SECONDS", "20"))
        return await self.extract_autohelperbot_direct(page, lot_id, timeout_s=direct_wait)

    async def collect_paginated_links(
        self,
        page: Page,
        *,
        link_selector: str,
        url_pattern: str,
        scan_limit: int,
    ) -> list[str]:
        """Zbiera linki z wyników wyszukiwania, przechodząc po kolejnych stronach."""
        max_pages = max(1, int(os.getenv("SEARCH_MAX_PAGES", "5")))
        seen: set[str] = set()
        links: list[str] = []
        pattern = re.compile(url_pattern)

        for page_index in range(max_pages):
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(2)

            current_links = await page.eval_on_selector_all(
                link_selector,
                """els => [...new Set(els.map(e => e.href).filter(Boolean))]"""
            )

            added = 0
            for url in current_links:
                if not pattern.search(url) or url in seen:
                    continue
                seen.add(url)
                links.append(url)
                added += 1
                if len(links) >= scan_limit:
                    break

            print(
                f"[{self.source_name.upper()}] Strona wyników {page_index + 1}: "
                f"+{added}, łącznie {len(links)}/{scan_limit}"
            )

            if len(links) >= scan_limit:
                break

            clicked_next = await self._click_next_results_page(page)
            if not clicked_next:
                break

        return links[:scan_limit]

    async def _click_next_results_page(self, page: Page) -> bool:
        next_selectors = [
            "a[aria-label*='Next' i]",
            "button[aria-label*='Next' i]",
            "a[title*='Next' i]",
            "button[title*='Next' i]",
            "li.next:not(.disabled) a",
            ".pagination-next:not(.disabled) a",
            ".pagination-next:not(.disabled) button",
            "a:has-text('Next')",
            "button:has-text('Next')",
            "a:has-text('>')",
            "button:has-text('>')",
        ]

        for selector in next_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    continue
                if not await locator.is_visible():
                    continue
                disabled = await locator.get_attribute("disabled")
                aria_disabled = await locator.get_attribute("aria-disabled")
                class_name = (await locator.get_attribute("class")) or ""
                if disabled is not None or aria_disabled == "true" or "disabled" in class_name.lower():
                    continue

                await locator.click(timeout=5000)
                await asyncio.sleep(3)
                return True
            except Exception:
                continue

        return False
