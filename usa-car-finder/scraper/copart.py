import asyncio
import json
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


class CopartScraper(BaseScraper):
    BASE_URL = "https://www.copart.com"

    def __init__(self):
        super().__init__("copart")

    def build_search_url(self, criteria: ClientCriteria) -> str:
        from urllib.parse import quote
        parts = [criteria.make]
        if criteria.model:
            parts.append(criteria.model)
        query = quote(" ".join(parts).lower())
        url = f"{self.BASE_URL}/lotSearchResults?free=true&query={query}"
        return url

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
        email = os.getenv("COPART_EMAIL", "").strip()
        password = os.getenv("COPART_PASSWORD", "").strip()
        if not email or not password:
            print("[Copart] Brak COPART_EMAIL/COPART_PASSWORD - pomijam aktywne logowanie")
            return False

        print("[Copart] Loguję konto Copart z .env...")
        login_timeout_ms = int(os.getenv("LOGIN_NAV_TIMEOUT_MS", "15000"))
        await page.goto(f"{self.BASE_URL}/login/", wait_until="domcontentloaded", timeout=login_timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        if await self.has_security_challenge(page):
            wait_seconds = int(os.getenv("COPART_SECURITY_WAIT_SECONDS", "0"))
            print("[Copart] Security check przed formularzem logowania")
            if not await self.wait_for_security_challenge_clear(page, wait_seconds):
                return False
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(2)

        email_input = await self._first_visible(
            page,
            [
                "input[name='username']",
                "input[name='email']",
                "input[type='email']",
                "input[id*='user' i]",
                "input[id*='email' i]",
            ],
        )
        password_input = await self._first_visible(
            page,
            [
                "input[name='password']",
                "input[type='password']",
                "input[id*='password' i]",
            ],
        )

        if email_input is None or password_input is None:
            print("[Copart] Nie znalazłem formularza logowania - możliwe, że sesja już jest zalogowana")
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

        wait_seconds = int(os.getenv("COPART_POST_LOGIN_WAIT_SECONDS", "10"))
        print(f"[Copart] Czekam {wait_seconds}s po logowaniu...")
        await asyncio.sleep(wait_seconds)
        return True

    def _build_search_payload(self, criteria: ClientCriteria, page_number: int, page_size: int) -> dict:
        parts = [criteria.make]
        if criteria.model:
            parts.append(criteria.model)
        query = " ".join(parts).strip().lower()
        return {
            "query": [query],
            "filter": {},
            "sort": ["auction_date_utc asc"],
            "page": page_number,
            "size": page_size,
            "start": page_number * page_size,
            "watchListOnly": False,
            "freeFormSearch": True,
            "hideImages": False,
            "defaultSort": False,
            "specificRowProvided": False,
            "displayName": "",
            "searchName": "",
            "backUrl": "",
            "includeTagByField": {},
            "rawParams": {},
        }

    async def _fetch_listing_api_page(
        self,
        page,
        criteria: ClientCriteria,
        page_number: int,
        page_size: int = 100,
    ) -> tuple[list[dict], dict]:
        payload = self._build_search_payload(criteria, page_number, page_size)
        response = await page.evaluate(
            """async (payload) => {
                const response = await fetch('/public/lots/search-results', {
                    method: 'POST',
                    headers: {'content-type': 'application/json'},
                    body: JSON.stringify(payload),
                });
                const text = await response.text();
                return {status: response.status, text};
            }""",
            payload,
        )
        if response["status"] != 200:
            raise RuntimeError(f"Copart search API HTTP {response['status']}")

        data = json.loads(response["text"])
        results = data.get("data", {}).get("results", {})
        return results.get("content") or [], results

    def _listing_candidate_from_api_lot(self, lot: dict) -> Optional[ListingCandidate]:
        lot_id = str(lot.get("lotNumberStr") or lot.get("ln") or "").strip()
        if not lot_id:
            return None

        slug = (lot.get("ldu") or "").strip()
        url = f"{self.BASE_URL}/lot/{lot_id}/{slug}" if slug else f"{self.BASE_URL}/lot/{lot_id}"

        auction_date = None
        if lot.get("ad"):
            try:
                from datetime import datetime, timezone

                auction_date = self.format_utc(
                    datetime.fromtimestamp(int(lot["ad"]) / 1000, tz=timezone.utc)
                )
            except Exception:
                auction_date = None

        seller_type = None
        if lot.get("ifs") is True:
            seller_type = "insurance"
        elif lot.get("ifs") is False:
            seller_type = "dealer"

        damage_text = self.damage_text_from_values(
            lot.get("dd"),
            lot.get("sdd"),
            lot.get("pd"),
            lot.get("primaryDamage"),
            lot.get("secondaryDamage"),
            lot.get("ld"),
        )
        damage_score, damage_label = self.damage_severity_score(damage_text)

        row_text = " ".join(
            str(value)
            for value in [
                lot.get("ld"),
                f"Lot # {lot_id}",
                f"seller={seller_type or 'unknown'}",
                f"auction={auction_date or '-'}",
                f"damage={damage_text or '-'}",
                lot.get("yn"),
            ]
            if value
        )

        return ListingCandidate(
            url=url,
            lot_id=lot_id,
            seller_type=seller_type,
            auction_date=auction_date,
            damage_text=damage_text,
            damage_score=damage_score,
            damage_label=damage_label,
            row_text=row_text,
            raw_data=lot,
        )

    @staticmethod
    def _positive_price(value) -> Optional[float]:
        try:
            price = float(value)
        except (TypeError, ValueError):
            return None
        return price if price > 0 else None

    def _listing_matches(
        self,
        candidate: ListingCandidate,
        criteria: ClientCriteria,
        *,
        min_auction_window_hours: Optional[int],
        auction_window_hours: Optional[int],
        insurance_only: bool,
    ) -> bool:
        lot = candidate.raw_data
        if not self.auction_date_in_window(
            candidate.auction_date,
            min_auction_window_hours,
            auction_window_hours,
        ):
            return False

        if insurance_only and candidate.seller_type != "insurance":
            return False

        if self.damage_has_excluded_type(candidate.damage_text, criteria.excluded_damage_types):
            return False

        year = lot.get("lcy")
        if criteria.year_from and year and int(year) < criteria.year_from:
            return False
        if criteria.year_to and year and int(year) > criteria.year_to:
            return False

        make_query = criteria.make.lower().strip()
        model_query = (criteria.model or "").lower().strip()
        make_text = str(lot.get("mkn") or lot.get("lmc") or "").lower()
        model_text = " ".join(str(lot.get(key) or "") for key in ("lm", "lmg", "mmod", "ld")).lower()
        if make_query and make_query not in make_text:
            return False
        if model_query and model_query not in model_text:
            return False

        current_bid = self._positive_price(
            lot.get("dynamicLotDetails", {}).get("currentBid") or lot.get("hb")
        )
        buy_now = self._positive_price(lot.get("bnp"))
        if criteria.budget_usd:
            price_to_check = buy_now or current_bid
            if price_to_check is not None and price_to_check > criteria.budget_usd:
                return False

        return True

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
            "[Copart] Lista: filtruję auction window → insurance → damage, "
            "potem sortuję po najmniejszych uszkodzeniach"
        )
        for page_number in range(max_pages):
            lots, result_meta = await self._fetch_listing_api_page(page, criteria, page_number)
            page_matches = 0
            for api_lot in lots:
                candidate = self._listing_candidate_from_api_lot(api_lot)
                if candidate is None or candidate.url in seen:
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

            total = result_meta.get("totalElements") or result_meta.get("totalLotCount") or "?"
            print(
                f"[Copart] Strona listy {page_number + 1}: "
                f"{page_matches} pasuje, łącznie {len(candidates)}/{scan_limit}, total={total}"
            )

            if len(candidates) >= scan_limit or len(lots) == 0:
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
                    print("[Copart] Tryb stałej przeglądarki + pluginy aktywny")
                else:
                    context = await launch_extension_context(p)
                    print("[Copart] Tryb przeglądarki + pluginy aktywny")
                    await asyncio.sleep(3)
            else:
                # Copart używa Incapsula - z sesją headless=False omija wykrywanie bota
                browser = await p.chromium.launch(**self.browser_launch_kwargs())

                # Storage state (opcjonalne - dla zalogowanych sesji)
                context_options = {
                    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                                 "Chrome/124.0.0.0 Safari/537.36",
                    "viewport": {"width": 1365, "height": 900},
                    "locale": "en-US",
                }

                if has_storage_state("copart"):
                    context_options["storage_state"] = combined_storage_state("copart", "autohelperbot")

                context = await browser.new_context(**context_options)
            try:
                page = await context.new_page()
                await self.setup_page(page)
                if os.getenv("COPART_ACTIVE_LOGIN", "true").lower() == "true":
                    try:
                        await self._login_if_configured(page)
                        if not await self.has_security_challenge(page):
                            await context.storage_state(path=str(storage_state_path("copart")))
                            print(f"[Copart] Zapisano sesję logowania: {storage_state_path('copart')}")
                        else:
                            print("[Copart] Nie zapisuję sesji: aktywny security check")
                    except Exception as exc:
                        print(f"[Copart] Aktywne logowanie nieudane ({exc}) - kontynuuję z zapisaną sesją profilu")

                search_url = self.build_search_url(criteria)
                print(f"[Copart] Szukam: {search_url}")
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

                # Akceptuj ciasteczka jeśli banner się pojawi
                try:
                    accept_button = page.locator('button:has-text("Accept"), button:has-text("I Accept")')
                    if await accept_button.count() > 0:
                        await accept_button.first.click()
                        print("[Copart] Zaakceptowano ciasteczka")
                        await asyncio.sleep(2)
                except:
                    pass

                # Czekaj na załadowanie JavaScript (Copart ładuje wyniki asynchronicznie)
                print("[Copart] Czekam na załadowanie wyników...")
                await asyncio.sleep(5)

                if await self.has_security_challenge(page):
                    wait_seconds = int(os.getenv("COPART_SECURITY_WAIT_SECONDS", "0"))
                    if not await self.wait_for_security_challenge_clear(page, wait_seconds):
                        print(
                            "[Copart] Blokada Imperva/hCaptcha - wymagana ręczna weryfikacja "
                            "albo zalogowana sesja Copart."
                        )
                        return []

                # Sprawdź czy są wyniki
                lot_count = await page.locator("a[href*='/lot/']").count()
                if lot_count == 0:
                    print("[Copart] Brak wyników wyszukiwania")
                    return []

                print(f"[Copart] Znaleziono {lot_count} wyników")

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
                        link_selector="a[href*='/lot/']",
                        url_pattern=r"/lot/\d+",
                        scan_limit=scan_limit,
                    )
                if detail_target is not None:
                    print(
                        f"[Copart] Kandydatów z listy: {len(lot_links)}; "
                        f"pobieram detale do {detail_target} poprawnych lotów"
                    )
                else:
                    print(f"[Copart] Do pobrania szczegółów: {len(lot_links)} lotów")

                for i, url in enumerate(lot_links):
                    if detail_target is not None and len(saved_files) >= detail_target:
                        break
                    if self.is_cached(url):
                        cache_path = self.get_cache_path(url)
                        saved_files.append((str(cache_path), url))
                        print(f"[Copart] {i+1}/{len(lot_links)} z cache: {cache_path.name}")
                        continue
                    try:
                        detail_timeout_ms = int(os.getenv("DETAIL_NAV_TIMEOUT_MS", "60000"))
                        try:
                            await page.goto(url, wait_until="domcontentloaded", timeout=detail_timeout_ms)
                        except PlaywrightTimeoutError:
                            print(
                                f"[Copart] {i+1}/{len(lot_links)} timeout detalu po {detail_timeout_ms}ms - "
                                "kontynuuję z aktualnym DOM"
                            )
                        if await self.has_security_challenge(page):
                            wait_seconds = int(os.getenv("COPART_SECURITY_WAIT_SECONDS", "0"))
                            if not await self.wait_for_security_challenge_clear(page, wait_seconds):
                                print(
                                    f"[Copart] {i+1}/{len(lot_links)} blokada Imperva/hCaptcha "
                                    "- pomijam lot."
                                )
                                continue
                        await self.wait_for_detail_data(page)
                        print(f"[Copart] {i+1}/{len(lot_links)} pobieram dane botów...")
                        metadata = self.last_listing_metadata.setdefault(url, {})
                        lot_id = metadata.get("lot_id")
                        if not lot_id:
                            match = re.search(r"/lot/(\d+)", url, flags=re.IGNORECASE)
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
                        print(f"[Copart] {i+1}/{len(lot_links)} zapisano: {path.name}")
                    except Exception as e:
                        print(f"[Copart] Błąd {url}: {e}")
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
