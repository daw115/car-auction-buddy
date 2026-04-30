import asyncio
import random
import os
import re
from pathlib import Path
from typing import Optional
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright
from .base import BaseScraper, ListingCandidate
from .browser_context import (
    extensions_enabled,
    get_shared_extension_context,
    keep_browser_open,
    launch_extension_context,
)
from .storage_state import combined_storage_state, storage_state_path, has_storage_state
from parser.models import ClientCriteria

EXTENSION_DIRS = [
    Path("./extensions/auctiongate"),
    Path("./extensions/autohelperbot"),
]
CHROME_PROFILE_DIR = Path(os.getenv("CHROME_PROFILE_DIR", "./data/chrome_profile"))


class IAAIScraper(BaseScraper):
    BASE_URL = "https://www.iaai.com"

    def __init__(self):
        super().__init__("iaai")

    def build_search_url(self, criteria: ClientCriteria) -> str:
        from urllib.parse import quote

        parts = [criteria.make]
        if criteria.model:
            parts.append(criteria.model)
        query = quote(" ".join(parts).strip().lower())
        return f"{self.BASE_URL}/Search?searchkeyword={query}"

    async def jitter(self):
        """Random delay dla anti-rate-limiting."""
        await asyncio.sleep(random.uniform(1.5, 4.0))

    async def _first_visible(self, page, selectors: list[str]):
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

    async def _login_if_configured(self, page) -> bool:
        email = os.getenv("IAAI_EMAIL", "").strip()
        password = os.getenv("IAAI_PASSWORD", "").strip()
        if not email or not password:
            print("[IAAI] Brak IAAI_EMAIL/IAAI_PASSWORD - pomijam aktywne logowanie")
            return False

        print("[IAAI] Loguję konto IAAI z .env...")
        login_timeout_ms = int(os.getenv("LOGIN_NAV_TIMEOUT_MS", "15000"))
        await page.goto("https://login.iaai.com/", wait_until="domcontentloaded", timeout=login_timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        email_input = await self._first_visible(
            page,
            [
                "input[name='Email']",
                "input[name='email']",
                "input[type='email']",
                "input[id*='email' i]",
                "input[id*='user' i]",
            ],
        )
        password_input = await self._first_visible(
            page,
            [
                "input[name='Password']",
                "input[name='password']",
                "input[type='password']",
                "input[id*='password' i]",
            ],
        )

        if email_input is None or password_input is None:
            print("[IAAI] Nie znalazłem formularza logowania - możliwe, że sesja już jest zalogowana")
            return False

        await email_input.fill(email)
        await password_input.fill(password)

        submit = await self._first_visible(
            page,
            [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Log In')",
                "button:has-text('Login')",
                "button:has-text('Sign In')",
            ],
        )
        if submit is None:
            await password_input.press("Enter")
        else:
            await submit.click()

        wait_seconds = int(os.getenv("IAAI_POST_LOGIN_WAIT_SECONDS", "10"))
        print(f"[IAAI] Czekam {wait_seconds}s po logowaniu...")
        await asyncio.sleep(wait_seconds)
        return True

    async def _wait_for_listing_seller_data(self, page, timeout_s: int = 15) -> bool:
        if os.getenv("USE_EXTENSIONS", "false").lower() != "true":
            return False

        for _ in range(timeout_s):
            try:
                html = await page.content()
                if "Who sell:" in html:
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)
        return False

    @staticmethod
    def _parse_price_from_text(text: str) -> Optional[float]:
        prices = re.findall(r"\$([\d,]+(?:\.\d+)?)\s*USD", text or "", flags=re.IGNORECASE)
        if not prices:
            return None
        try:
            return float(prices[-1].replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _seller_type_from_html(html: str, text: str) -> Optional[str]:
        combined = f"{html} {text}"
        match = re.search(
            r"Who\s*sell[s:]?\s*:?\s*(Insurance|Seller|Dealer|Owner)",
            combined,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None
        value = match.group(1).lower()
        return "insurance" if value == "insurance" else "dealer"

    def _row_to_candidate(self, row: dict) -> Optional[ListingCandidate]:
        url = (row.get("href") or "").strip()
        lot_id = (row.get("lot_id") or "").strip()
        if not url or not lot_id:
            return None

        html = row.get("html") or ""
        text = row.get("text") or ""
        seller_type = self._seller_type_from_html(html, text)
        auction_date = row.get("auction_date") or None
        if auction_date:
            auction_dt = self.datetime_from_auction_date(auction_date)
            auction_date = self.format_utc(auction_dt) if auction_dt else None

        damage_text = self.damage_text_from_values(text)
        damage_score, damage_label = self.damage_severity_score(damage_text)

        return ListingCandidate(
            url=url,
            lot_id=lot_id,
            seller_type=seller_type,
            auction_date=auction_date,
            damage_text=damage_text,
            damage_score=damage_score,
            damage_label=damage_label,
            row_text=text,
            raw_data=row,
        )

    def _listing_matches(
        self,
        candidate: ListingCandidate,
        criteria: ClientCriteria,
        *,
        min_auction_window_hours: Optional[int],
        auction_window_hours: Optional[int],
        insurance_only: bool,
    ) -> bool:
        if not self.auction_date_in_window(
            candidate.auction_date,
            min_auction_window_hours,
            auction_window_hours,
        ):
            return False

        if insurance_only and candidate.seller_type is not None and candidate.seller_type != "insurance":
            return False

        if self.damage_has_excluded_type(candidate.damage_text, criteria.excluded_damage_types):
            return False

        text = candidate.row_text.lower()
        if criteria.make and criteria.make.lower() not in text:
            return False
        if criteria.model and criteria.model.lower() not in text:
            return False

        year_match = re.search(r"\b(19|20)\d{2}\b", candidate.row_text)
        if year_match:
            year = int(year_match.group(0))
            if criteria.year_from and year < criteria.year_from:
                return False
            if criteria.year_to and year > criteria.year_to:
                return False

        price = self._parse_price_from_text(candidate.row_text)
        if criteria.budget_usd and price is not None and price > criteria.budget_usd:
            return False

        return True

    async def _extract_current_listing_candidates(self, page) -> list[ListingCandidate]:
        rows = await page.locator("a[href*='/VehicleDetail']").evaluate_all(
            """els => {
                const detailsValue = document.querySelector('#VehicleDetails')?.value || '[]';
                let details = [];
                try { details = JSON.parse(detailsValue); } catch (e) { details = []; }
                const detailMap = Object.fromEntries(details.map(item => [String(item.Id || '').replace('~US', ''), item]));
                const seen = new Set();
                return els.map(a => {
                    const href = a.href;
                    if (!href || seen.has(href)) return null;
                    seen.add(href);
                    const idMatch = href.match(/VehicleDetail\\/(\\d+)/);
                    const lotId = idMatch ? idMatch[1] : (a.getAttribute('name') || '').replace(/\\D+/g, '');
                    let row = a.closest('.table-cell--data') || a;
                    let node = a;
                    for (let i = 0; i < 10 && node.parentElement; i++) {
                        const text = node.innerText || node.textContent || '';
                        if (text.length > 300 && /View Sale List|Join Auction|Timed Auction|Who sell/i.test(text)) {
                            row = node;
                            break;
                        }
                        node = node.parentElement;
                    }
                    const detail = detailMap[lotId] || {};
                    return {
                        href,
                        lot_id: lotId,
                        auction_date: detail.AuctionDate || detail.AuctionDateTime || detail.ActnDtTm || null,
                        html: (row.outerHTML || '').slice(0, 30000),
                        text: (row.innerText || row.textContent || '').replace(/\\s+/g, ' ').trim(),
                    };
                }).filter(Boolean);
            }"""
        )

        candidates: list[ListingCandidate] = []
        for row in rows:
            candidate = self._row_to_candidate(row)
            if candidate:
                candidates.append(candidate)
        return candidates

    async def _collect_prefiltered_candidates(
        self,
        page,
        criteria: ClientCriteria,
        *,
        scan_limit: int,
        min_auction_window_hours: Optional[int],
        auction_window_hours: Optional[int],
        insurance_only: bool,
    ) -> list[ListingCandidate]:
        max_pages = max(1, int(os.getenv("SEARCH_MAX_PAGES", "5")))
        candidates: list[ListingCandidate] = []
        seen: set[str] = set()

        print(
            "[IAAI] Lista: filtruję auction window → insurance → damage, "
            "potem sortuję po najmniejszych uszkodzeniach"
        )
        for page_index in range(max_pages):
            await self._wait_for_listing_seller_data(page, timeout_s=15)
            page_candidates = await self._extract_current_listing_candidates(page)
            page_matches = 0
            for candidate in page_candidates:
                if candidate.url in seen:
                    continue
                seen.add(candidate.url)
                if not self._listing_matches(
                    candidate,
                    criteria,
                    min_auction_window_hours=min_auction_window_hours,
                    auction_window_hours=auction_window_hours,
                    insurance_only=insurance_only,
                ):
                    continue

                candidates.append(candidate)
                page_matches += 1
                if len(candidates) >= scan_limit:
                    break

            print(
                f"[IAAI] Strona listy {page_index + 1}: "
                f"{page_matches} pasuje, łącznie {len(candidates)}/{scan_limit}"
            )

            if len(candidates) >= scan_limit:
                break

            clicked_next = await self._click_next_results_page(page)
            if not clicked_next:
                break

        candidates.sort(key=self.candidate_sort_key)
        return candidates[:scan_limit]

    async def scrape(
        self,
        criteria: ClientCriteria,
        *,
        min_auction_window_hours: Optional[int] = None,
        auction_window_hours: Optional[int] = None,
        insurance_only: Optional[bool] = None,
    ) -> list[tuple[str, str]]:
        """Zwraca listę krotek (ścieżka HTML, oryginalny URL lota)."""
        saved_files: list[tuple[str, str]] = []
        self.last_listing_metadata = {}

        async with async_playwright() as p:
            browser = None
            page = None
            owns_context = True
            if extensions_enabled():
                if keep_browser_open():
                    context = await get_shared_extension_context()
                    owns_context = False
                    print("[IAAI] Tryb stałej przeglądarki + pluginy aktywny")
                else:
                    context = await launch_extension_context(p)
                    print("[IAAI] Tryb przeglądarki + pluginy aktywny")
                    await asyncio.sleep(3)
            else:
                # IAAI używa podobnej ochrony jak Copart - headless=False z sesją
                browser = await p.chromium.launch(**self.browser_launch_kwargs())

                # Storage state (opcjonalne - dla zalogowanych sesji)
                context_options = {
                    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                                 "Chrome/124.0.0.0 Safari/537.36",
                    "viewport": {"width": 1365, "height": 900},
                    "locale": "en-US",
                }

                if has_storage_state("iaai"):
                    context_options["storage_state"] = combined_storage_state("iaai", "autohelperbot")

                context = await browser.new_context(**context_options)
            try:
                page = await context.new_page()
                await self.setup_page(page)
                if os.getenv("IAAI_ACTIVE_LOGIN", "true").lower() == "true":
                    try:
                        await self._login_if_configured(page)
                        if not await self.has_security_challenge(page):
                            await context.storage_state(path=str(storage_state_path("iaai")))
                            print(f"[IAAI] Zapisano sesję logowania: {storage_state_path('iaai')}")
                    except Exception as exc:
                        print(f"[IAAI] Aktywne logowanie nieudane ({exc}) - kontynuuję z zapisaną sesją profilu")

                search_url = self.build_search_url(criteria)
                print(f"[IAAI] Szukam: {search_url}")
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

                # Akceptuj ciasteczka jeśli banner się pojawi
                try:
                    accept_button = page.locator('button:has-text("Accept"), button:has-text("I Accept")')
                    if await accept_button.count() > 0:
                        await accept_button.first.click()
                        print("[IAAI] Zaakceptowano ciasteczka")
                        await asyncio.sleep(2)
                except:
                    pass

                # Czekaj na załadowanie JavaScript (IAAI ładuje wyniki asynchronicznie)
                print("[IAAI] Czekam na załadowanie wyników...")
                await asyncio.sleep(5)

                # Sprawdź czy są wyniki
                vehicle_count = await page.locator("a[href*='/VehicleDetail']").count()
                if vehicle_count == 0:
                    print("[IAAI] Brak wyników wyszukiwania")
                    return []

                print(f"[IAAI] Znaleziono {vehicle_count} wyników")

                scan_limit = self.get_detail_scan_limit(criteria.max_results)
                effective_insurance_only = (
                    insurance_only
                    if insurance_only is not None
                    else os.getenv("FILTER_SELLER_INSURANCE_ONLY", "false").lower() == "true"
                )
                use_listing_prefilter = (
                    effective_insurance_only
                    or auction_window_hours is not None
                    or criteria.year_from is not None
                    or criteria.year_to is not None
                    or criteria.budget_usd is not None
                )

                detail_target = None
                if use_listing_prefilter:
                    candidates = await self._collect_prefiltered_candidates(
                        page,
                        criteria,
                        scan_limit=scan_limit,
                        min_auction_window_hours=min_auction_window_hours,
                        auction_window_hours=auction_window_hours,
                        insurance_only=effective_insurance_only,
                    )
                    lot_links = [candidate.url for candidate in candidates]
                    if os.getenv("OPEN_ALL_PREFILTERED_DETAILS", "true").lower() == "true":
                        detail_target = len(lot_links)
                    else:
                        detail_target = min(scan_limit, max(1, criteria.max_results or scan_limit))
                    self.last_listing_metadata = {
                        candidate.url: {
                            "lot_id": candidate.lot_id,
                            "seller_type": candidate.seller_type,
                            "auction_date": candidate.auction_date,
                            "listing_damage_text": candidate.damage_text,
                            "listing_damage_score": candidate.damage_score,
                            "listing_damage_label": candidate.damage_label,
                            "listing_row_text": candidate.row_text,
                            "listing_raw_data": candidate.raw_data,
                        }
                        for candidate in candidates
                    }
                else:
                    lot_links = await self.collect_paginated_links(
                        page,
                        link_selector="a[href*='/VehicleDetail']",
                        url_pattern=r"/VehicleDetail/\d+",
                        scan_limit=scan_limit,
                    )
                if detail_target is not None:
                    print(
                        f"[IAAI] Kandydatów z listy: {len(lot_links)}; "
                        f"pobieram detale do {detail_target} poprawnych lotów"
                    )
                else:
                    print(f"[IAAI] Do pobrania szczegółów: {len(lot_links)} lotów")

                for i, url in enumerate(lot_links):
                    if detail_target is not None and len(saved_files) >= detail_target:
                        break
                    if self.is_cached(url):
                        cache_path = self.get_cache_path(url)
                        saved_files.append((str(cache_path), url))
                        print(f"[IAAI] {i+1}/{len(lot_links)} z cache: {cache_path.name}")
                        continue
                    try:
                        detail_timeout_ms = int(os.getenv("DETAIL_NAV_TIMEOUT_MS", "60000"))
                        try:
                            await page.goto(url, wait_until="domcontentloaded", timeout=detail_timeout_ms)
                        except PlaywrightTimeoutError:
                            print(
                                f"[IAAI] {i+1}/{len(lot_links)} timeout detalu po {detail_timeout_ms}ms - "
                                "kontynuuję z aktualnym DOM"
                            )
                        await self.wait_for_detail_data(page)
                        print(f"[IAAI] {i+1}/{len(lot_links)} pobieram dane botów...")
                        metadata = self.last_listing_metadata.setdefault(url, {})
                        lot_id = metadata.get("lot_id")
                        if not lot_id:
                            match = re.search(r"/VehicleDetail/(\d+)", url, flags=re.IGNORECASE)
                            lot_id = match.group(1) if match else ""
                        extension_data = await self.extract_bot_data_for_lot(page, lot_id)
                        if extension_data:
                            metadata["extension_data"] = extension_data
                            for key in (
                                "seller_type",
                                "seller_reserve_usd",
                                "full_vin",
                                "delivery_cost_estimate_usd",
                            ):
                                if extension_data.get(key):
                                    metadata[key] = extension_data[key]
                        await self.jitter()
                        html = await page.content()
                        path = self.save_html(url, html)
                        saved_files.append((str(path), url))
                        print(f"[IAAI] {i+1}/{len(lot_links)} zapisano: {path.name}")
                    except Exception as e:
                        print(f"[IAAI] Błąd {url}: {e}")
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if owns_context:
                    await context.close()
                if browser is not None:
                    await browser.close()

        return saved_files
