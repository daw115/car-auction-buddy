"""bidfax.info client — final sale price lookup for Copart/IAAI lots.

Port logiki z stasizb/AuctionScraper (nodriver → Playwright).

Krytyczne elementy zachowane:
  - reCAPTCHA v3 token harvesting (#token2 + #action2)
  - Cloudflare wait (cf_chl marker)
  - Homepage-bounce detection (soft-block → IN_PROGRESS, no retry)
  - Make-mismatch retry (do 3 prób gdy bidfax zwraca wrong vehicle)

Interfejs batch-oriented: `lookup_many(queries) -> {q: (price, vin, url)}`.
Wewnętrznie sekwencyjne (1 tab) — wystarczy dla naszego wolumenu, mniejsze
ryzyko Cloudflare burst-detection.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from playwright.async_api import Page, async_playwright

try:
    from playwright_stealth import Stealth
    _STEALTH_OK = True
except ImportError:
    _STEALTH_OK = False

from .bidfax_cache import (
    DEFAULT_CACHE_TTL_DAYS,
    _TIMESTAMPS_KEY,
    cache_results,
    load_cache,
)
from .bidfax_parsing import (
    IN_PROGRESS,
    extract_grid_result,
    url_make_matches,
)

BIDFAX_HOME = "https://bidfax.info"
SALE_ENDED_TEXT = "Sale ended"

_CF_WAIT_TIMEOUT = 90.0
_COPART_RENDER_WAIT = 4.0
_FORM_TOKEN_TIMEOUT = 15.0
_GRID_POLL_BUDGET = 10
_TOTAL_POLL_HARD_CAP = 30
_HOMEPAGE_MARKER = 'id="search"'
_BIDFAX_HOME_PATH = re.compile(r'^https?://bidfax\.info/?$')

# Cloudflare challenge markers — jeśli któryś jest w HTML, strona NIE jest
# zwykłą stroną bidfax. AuctionScraper miał tylko "cf_chl", ale Cloudflare
# rotuje implementację (Turnstile widget używa innych stringów).
_CF_MARKERS = (
    "cf_chl",
    "Verify you are human",
    "Performing security verification",
    "challenge-form",
    "cf-mitigated",
    "Just a moment",
)


def _is_cloudflare_page(html: str) -> bool:
    return any(marker in html for marker in _CF_MARKERS)

# Retry budgets — patrz komentarz w oryginale AuctionScrapera.
_BOUNCE_MAX_ATTEMPTS = 1
_BOUNCE_RETRY_WAIT = 5.0
_MISMATCH_MAX_ATTEMPTS = 3

DEBUG_SCREENSHOTS = os.getenv("BIDFAX_DEBUG_SCREENSHOTS", "false").lower() == "true"
LOG_DIR = Path(os.getenv("BIDFAX_LOG_DIR", "./logs"))


# Hidden form-field harvester. Token sources, w kolejności:
#   1. #token2 już ma wartość (bidfax dle_js.js wystrzelił grecaptcha.execute()) — użyj.
#   2. Odpalamy grecaptcha sami z site_key z <script src="recaptcha/api.js?render=...">.
#      Token wpada do #token2 asynchronicznie; Python pętla pollu czeka.
#
# UWAGA: token z <link rel="alternate" href="...token2=..."> jest dla SEO i
# bound do innej sesji — serwer ODRZUCA submission z tym tokenem. NIE używać.
_FORM_TOKEN_HARVEST_JS = """
(function() {
    var t = document.getElementById('token2');
    var a = document.getElementById('action2');
    if (t && t.value) {
        if (a && !a.value) a.value = 'search_action';
        return t.value;
    }
    if (!window._auctionsRecaptchaTriggered && typeof grecaptcha !== 'undefined') {
        var siteKey = null;
        var scripts = document.querySelectorAll('script[src*="recaptcha/api.js"]');
        for (var i = 0; i < scripts.length; i++) {
            var m = scripts[i].src.match(/[?&]render=([^&]+)/);
            if (m) { siteKey = m[1]; break; }
        }
        if (siteKey) {
            try {
                window._auctionsRecaptchaTriggered = true;
                grecaptcha.ready(function() {
                    grecaptcha
                        .execute(siteKey, {action: 'search_action'})
                        .then(function(token) {
                            if (t) t.value = token;
                            if (a) a.value = 'search_action';
                        });
                });
            } catch (e) { /* nothing to do */ }
        }
    }
    return t && t.value ? t.value : '';
})();
"""


@runtime_checkable
class BidfaxClient(Protocol):
    async def lookup_many(
        self,
        queries: list[str],
        makes: dict[str, str] | None = None,
        delay: float = 2.0,
    ) -> dict[str, tuple[str, str, str]]:
        ...


class _BidfaxBounce(Exception):
    """Server bounced back to homepage — soft-block / low reCAPTCHA score."""


def _dump_snippet(prefix: str, query: str, html: str) -> None:
    if not html:
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = LOG_DIR / f"bidfax_{prefix}_{query}_{ts}.html"
        path.write_text(html[:30_000], encoding="utf-8")
        print(f"    [bidfax] {prefix} snapshot for {query} → {path}", flush=True)
    except Exception as exc:
        print(f"    [bidfax] could not save {prefix} snippet: {exc}", flush=True)


async def _save_screenshot(page: Page, query: str) -> None:
    if not DEBUG_SCREENSHOTS:
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = LOG_DIR / f"bidfax_screenshot_{query}_{ts}.png"
        await page.screenshot(path=str(path), full_page=True)
    except Exception as exc:
        print(f"    [bidfax] [warn] screenshot failed: {exc}", flush=True)


def _log_lookup_result(idx: int, total: int, query: str, result: tuple[str, str, str]) -> None:
    price, vin, url = result
    if url and price != IN_PROGRESS:
        print(f"  [bidfax {idx}/{total}] {query} → {price}  VIN:{vin or '—'}  {url}", flush=True)
    elif url:
        print(f"  [bidfax {idx}/{total}] {query} → No Price  ({url})", flush=True)
    else:
        print(f"  [bidfax {idx}/{total}] {query} → No Price", flush=True)


async def _wait_cf_clear(page: Page, timeout: float = _CF_WAIT_TIMEOUT) -> None:
    """Poll until page is no longer a Cloudflare challenge.

    Drukuje hint przy pierwszym wykryciu CF, żeby user wiedział że
    może być potrzebne ręczne kliknięcie checkboxa (Turnstile).
    """
    first_seen = False

    async def _poll() -> None:
        nonlocal first_seen
        while True:
            try:
                content = await page.content()
            except Exception:
                content = ""
            if not _is_cloudflare_page(content):
                if first_seen:
                    print("    [bidfax] Cloudflare cleared, continuing", flush=True)
                return
            if not first_seen:
                first_seen = True
                print(
                    f"    [bidfax] Cloudflare challenge wykryty na {page.url} "
                    f"— kliknij ręcznie 'Verify you are human' jeśli widzisz checkbox "
                    f"(timeout {timeout:.0f}s)",
                    flush=True,
                )
            await asyncio.sleep(1)

    try:
        await asyncio.wait_for(_poll(), timeout=timeout)
    except asyncio.TimeoutError:
        print("    [bidfax] Cloudflare wait timeout — proceeding anyway", flush=True)


async def _ensure_search_tokens(page: Page, timeout: float = _FORM_TOKEN_TIMEOUT) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        try:
            val = await page.evaluate(_FORM_TOKEN_HARVEST_JS)
        except Exception:
            val = None
        if val:
            return True
        await asyncio.sleep(0.5)
        elapsed += 0.5
    return False


async def _fill_and_submit(page: Page, query: str) -> bool:
    search_input = page.locator("#search").first
    if await search_input.count() == 0:
        return False
    await asyncio.sleep(2)
    await search_input.click()
    await asyncio.sleep(0.5)
    await search_input.fill(query)
    await asyncio.sleep(0.5)

    if not await _ensure_search_tokens(page):
        try:
            html = await page.content()
        except Exception:
            html = ""
        _dump_snippet("token_missing", query, html)
        print(
            f"    [bidfax] CSRF tokens missing for {query!r} "
            f"— aborting submit (server would bounce back to home)",
            flush=True,
        )
        return False

    submit_btn = page.locator("#submit").first
    if await submit_btn.count() == 0:
        return False
    await submit_btn.click()
    return True


async def _wait_for_navigation(page: Page) -> bool:
    for _ in range(10):
        await asyncio.sleep(1)
        try:
            current_url = page.url
        except Exception:
            current_url = ""
        if current_url and not _BIDFAX_HOME_PATH.match(current_url):
            return True
    return False


async def _search_once(page: Page, query: str) -> tuple[str, str, str]:
    try:
        if not await _fill_and_submit(page, query):
            return IN_PROGRESS, "", ""
        navigated = await _wait_for_navigation(page)
        if not navigated:
            # URL nie zmienił się = bidfax odrzucił submit (token problem / soft-block)
            try:
                snap = await page.content()
            except Exception:
                snap = ""
            _dump_snippet("bounce", query, snap)
            raise _BidfaxBounce(query)

        polls_after_cf = 0
        last_html = ""
        for _ in range(_TOTAL_POLL_HARD_CAP):
            await asyncio.sleep(1)
            try:
                last_html = await page.content()
            except Exception:
                last_html = ""
            if _is_cloudflare_page(last_html):
                continue
            result = extract_grid_result(last_html)
            if result is not None:
                return result
            polls_after_cf += 1
            if polls_after_cf >= _GRID_POLL_BUDGET:
                break

        # Search OK (URL changed), brak #grid = genuine "no result" w bazie bidfaxa.
        # NIE traktujemy tego jako bounce — to po prostu nieindeksowany lot.
        _dump_snippet("empty", query, last_html)
        return IN_PROGRESS, "", ""
    finally:
        await _save_screenshot(page, query)


async def _query_with_retries(page: Page, query: str, expected_make: str) -> tuple[str, str, str]:
    bounce_attempts = 0
    mismatch_attempts = 0
    while True:
        try:
            await page.goto(BIDFAX_HOME, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            print(f"    [bidfax] navigation to home failed for {query!r}: {exc}", flush=True)
            return IN_PROGRESS, "", ""
        await asyncio.sleep(2)
        await _wait_cf_clear(page)

        try:
            price, vin, url = await _search_once(page, query)
        except _BidfaxBounce:
            bounce_attempts += 1
            if bounce_attempts >= _BOUNCE_MAX_ATTEMPTS:
                print(
                    f"    [bidfax] {query!r}: server bounced back to homepage "
                    f"(soft-block / not indexed) — surfacing IN_PROGRESS",
                    flush=True,
                )
                return IN_PROGRESS, "", ""
            await asyncio.sleep(_BOUNCE_RETRY_WAIT)
            continue

        if not url:
            return IN_PROGRESS, "", ""

        if not expected_make or url_make_matches(expected_make, url):
            return price, vin, url

        mismatch_attempts += 1
        if mismatch_attempts >= _MISMATCH_MAX_ATTEMPTS:
            return IN_PROGRESS, "", ""
        print(
            f"    [bidfax] make mismatch for {query!r}: "
            f"expected {expected_make!r}, got URL {url} "
            f"— retrying ({mismatch_attempts}/{_MISMATCH_MAX_ATTEMPTS - 1})",
            flush=True,
        )


class PlaywrightBidfaxClient:
    """Live bidfax.info client backed by Playwright.

    Domyślnie używa persistent context w `data/chrome_profile_bidfax/` żeby
    cookies (w tym CF clearance po jednorazowym ręcznym kliknięciu Turnstile)
    przetrwały między uruchomieniami. Jeśli `CHROME_EXECUTABLE_PATH` wskazuje
    na real Chrome, używa go zamiast bundled Chromium (znacznie mniej CF
    blokad).

    Headed (headless=False) jest domyślne — Cloudflare wykrywa headless
    Chromium bardzo agresywnie.
    """

    def __init__(self, headless: Optional[bool] = None) -> None:
        if headless is None:
            headless = os.getenv("BIDFAX_HEADLESS", "false").lower() == "true"
        self.headless = headless
        self.profile_dir = Path(
            os.getenv("BIDFAX_CHROME_PROFILE_DIR", "data/chrome_profile_bidfax")
        )
        self.chrome_executable = os.getenv("CHROME_EXECUTABLE_PATH", "").strip() or None
        # CDP attach mode: gdy ustawione, łączymy się do JUŻ DZIAŁAJĄCEJ Chrome
        # uruchomionej z --remote-debugging-port. Wtedy nie używamy persistent
        # profile (Chrome ma swój), nie stosujemy stealth (real Chrome user'a).
        self.cdp_url = os.getenv("BIDFAX_CHROME_CDP_URL", "").strip() or None

    def _launch_kwargs(self) -> dict:
        # KRYTYCZNE: ignore_default_args usuwa Playwrightowe flagi, które
        # real Chrome traktuje jako automation tells. Każdy baner u góry
        # ("Chrome is being controlled by automated test software",
        # "unsupported command-line flag: --no-sandbox") jest też w DOM
        # i CF go czyta. NIE dodawaj nic do `args` — w real Chrome każda
        # niestandardowa flaga pokazuje baner ostrzegawczy.
        # navigator.webdriver = undefined jest ustawiane przez stealth lib
        # przez init script (skuteczne równoważne).
        kwargs: dict = {
            "headless": self.headless,
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
        if self.chrome_executable and Path(self.chrome_executable).exists():
            kwargs["executable_path"] = self.chrome_executable
            print(f"    [bidfax] using real Chrome at {self.chrome_executable}", flush=True)
        return kwargs

    async def _apply_stealth(self, page: Page) -> None:
        if not _STEALTH_OK:
            return
        try:
            await Stealth().apply_stealth_async(page)
            print("    [bidfax] stealth applied", flush=True)
        except Exception as exc:
            print(f"    [bidfax] stealth setup nieudany ({exc}) - kontynuuję bez", flush=True)

    async def lookup_many(
        self,
        queries: list[str],
        makes: dict[str, str] | None = None,
        delay: float = 2.0,
    ) -> dict[str, tuple[str, str, str]]:
        if not queries:
            return {}
        makes = makes or {}
        results: dict[str, tuple[str, str, str]] = {}

        async with async_playwright() as p:
            if self.cdp_url:
                print(f"    [bidfax] CDP attach do {self.cdp_url}", flush=True)
                browser = await p.chromium.connect_over_cdp(self.cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = await context.new_page()
                owns_context = False
            else:
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                context = await p.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    **self._launch_kwargs(),
                )
                page = context.pages[0] if context.pages else await context.new_page()
                await self._apply_stealth(page)
                browser = None
                owns_context = True

            try:
                total = len(queries)
                for i, q in enumerate(queries, 1):
                    result = await _query_with_retries(page, q, makes.get(q, ""))
                    results[q] = result
                    _log_lookup_result(i, total, q, result)
                    if i < total:
                        await asyncio.sleep(delay)
            finally:
                if owns_context:
                    await context.close()
                else:
                    try:
                        await page.close()
                    except Exception:
                        pass
                    try:
                        await browser.close()
                    except Exception:
                        pass
        return results

    async def check_sale_ended_many(self, lot_urls: list[str]) -> dict[str, bool]:
        if not lot_urls:
            return {}
        results: dict[str, bool] = {}
        async with async_playwright() as p:
            if self.cdp_url:
                browser = await p.chromium.connect_over_cdp(self.cdp_url)
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                owns_context = False
            else:
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                context = await p.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    **self._launch_kwargs(),
                )
                browser = None
                owns_context = True
            try:
                for url in lot_urls:
                    page = await context.new_page()
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(_COPART_RENDER_WAIT)
                        content = await page.content()
                        results[url] = SALE_ENDED_TEXT in content
                    except Exception:
                        results[url] = False
                    finally:
                        await page.close()
            finally:
                if owns_context:
                    await context.close()
                else:
                    try:
                        await browser.close()
                    except Exception:
                        pass
        return results


class FakeBidfaxClient:
    """Test double — zwraca przygotowane odpowiedzi bez przeglądarki."""

    def __init__(
        self,
        responses: dict[str, tuple[str, str, str]] | None = None,
        sale_ended: dict[str, bool] | None = None,
        default_sale_ended: bool = True,
    ) -> None:
        self.responses = dict(responses or {})
        self._sale_ended = dict(sale_ended or {})
        self._default_sale_ended = default_sale_ended
        self.lookup_calls: list[str] = []
        self.sale_ended_calls: list[str] = []

    async def lookup_many(
        self,
        queries: list[str],
        makes: dict[str, str] | None = None,
        delay: float = 2.0,
    ) -> dict[str, tuple[str, str, str]]:
        del makes, delay
        self.lookup_calls.extend(queries)
        return {q: self.responses.get(q, (IN_PROGRESS, "", "")) for q in queries}

    async def check_sale_ended_many(self, lot_urls: list[str]) -> dict[str, bool]:
        self.sale_ended_calls.extend(lot_urls)
        return {u: self._sale_ended.get(u, self._default_sale_ended) for u in lot_urls}


async def lookup_with_cache(
    queries: list[str],
    cache_path: Path,
    *,
    makes: dict[str, str] | None = None,
    delay: float = 2.0,
    client: BidfaxClient | None = None,
) -> dict[str, tuple[str, str, str]]:
    """High-level wrapper: cache-aware batch lookup.

    Tylko finalne (non-IN_PROGRESS) wyniki idą do cache. Zwraca {query: (price, vin, url)}
    dla wszystkich zapytanych queries (z cache lub świeżo pobrane).
    """
    cache = load_cache(cache_path, ttl_days=DEFAULT_CACHE_TTL_DAYS)
    to_fetch = [q for q in queries if q not in cache or q == _TIMESTAMPS_KEY]

    if to_fetch:
        print(f"[*] bidfax lookup: {len(to_fetch)} new  (cached: {len(cache)})")
        real_client = client or PlaywrightBidfaxClient()
        fetched = await real_client.lookup_many(to_fetch, makes=makes, delay=delay)
        cache = cache_results(cache_path, fetched)

    return {
        q: cache.get(q, (IN_PROGRESS, "", ""))
        for q in queries
        if q != _TIMESTAMPS_KEY
    }
