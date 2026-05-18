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
            # Normalizuj 'CRV' → 'cr-v' itp. — IAAI też wyszukuje dosłownie
            parts.append(self.normalize_model_for_query(criteria.model))
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

    async def _is_session_active(self, page) -> bool:
        """Sprawdza czy IAAI session jest aktywna (URL-based redirect check).

        Strategia: otwórz /Dashboard. Zalogowany → URL pozostaje /Dashboard.
        Niezalogowany → IAAI redirectuje na login.iaai.com. URL-based jest
        deterministyczne i nie zależy od JS-rendered DOM selektorów.
        """
        try:
            await page.goto(f"{self.BASE_URL}/Dashboard", wait_until="domcontentloaded", timeout=15000)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            current_url = (page.url or "").lower()
            # Logged-in = URL nie zredirectowany na login subdomain ani /login path
            return not any(p in current_url for p in ["login.iaai.com", "/login", "/signin"])
        except Exception as exc:
            print(f"[IAAI] Health check sesji failed: {exc}")
            return False

    async def _login_if_configured(self, page) -> bool:
        email = os.getenv("IAAI_EMAIL", "").strip()
        password = os.getenv("IAAI_PASSWORD", "").strip()
        if not email or not password:
            print("[IAAI] Brak IAAI_EMAIL/IAAI_PASSWORD - pomijam aktywne logowanie")
            return False

        # Health check: jeśli sesja aktywna, pomiń login flow (~10-15s oszczędności)
        if await self._is_session_active(page):
            print("[IAAI] ✅ Sesja aktywna — pomijam logowanie")
            return True

        print("[IAAI] ⚠️ Sesja wygasła lub brak — loguję z .env...")
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

    async def _fetch_one_detail_parallel(self, context, url: str, idx: int, total: int):
        """Fetch single IAAI detail page w osobnym tab (nowa page w context).

        Każda task ma własną page (osobny tab Chrome) — pozwala asyncio.gather
        ważyć N równoległych detail fetches bez race condition na shared page.

        AHB direct (przez extract_bot_data_for_lot) otwiera dodatkowy tab dla
        bot.autohelperbot.com — to OK bo context.new_page() jest tani.

        Zwraca (saved_path, url) gdy sukces, None gdy error/timeout.
        """
        page = None
        try:
            page = await context.new_page()
            detail_timeout_ms = int(os.getenv("DETAIL_NAV_TIMEOUT_MS", "60000"))
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=detail_timeout_ms)
            except PlaywrightTimeoutError:
                print(f"[IAAI] {idx+1}/{total} timeout detalu po {detail_timeout_ms}ms - kontynuuję z DOM")
            await self.wait_for_detail_data(page)
            print(f"[IAAI] {idx+1}/{total} pobieram dane botów...")
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
            print(f"[IAAI] {idx+1}/{total} zapisano: {path.name}")
            return (str(path), url)
        except Exception as e:
            print(f"[IAAI] Błąd {url}: {type(e).__name__}: {e}")
            return None
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

    async def _apply_dom_filter_input(self, page, input_selector: str, value: str) -> bool:
        """Wypełnia DOM input (np. #YearFilterFrom) wartością i wciska Enter.
        Opt-in via IAAI_USE_DOM_FILTERS=true. Zwraca True jeśli zaaplikowano."""
        try:
            locator = page.locator(input_selector).first
            if await locator.count() == 0:
                return False
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            await locator.fill("")
            await locator.fill(value)
            await locator.press("Enter")
            return True
        except Exception as exc:
            print(f"[IAAI] Filtr {input_selector} nieudany: {exc}")
            return False

    async def _apply_year_filter(self, page, year_from: Optional[int], year_to: Optional[int]) -> None:
        applied_any = False
        if year_from:
            if await self._apply_dom_filter_input(page, "#YearFilterFrom", str(year_from)):
                applied_any = True
                await asyncio.sleep(0.8)
        if year_to:
            if await self._apply_dom_filter_input(page, "#YearFilterTo", str(year_to)):
                applied_any = True
                await asyncio.sleep(0.8)
        if applied_any:
            print(f"[IAAI] Filtr DOM: rok {year_from or '*'}-{year_to or '*'}")

    async def _apply_odometer_filter(self, page, max_miles: Optional[int]) -> None:
        if not max_miles:
            return
        if await self._apply_dom_filter_input(page, "#ODOValueFilterTo", str(max_miles)):
            await asyncio.sleep(0.8)
            print(f"[IAAI] Filtr DOM: odometer ≤ {max_miles} mi")

    async def _apply_auction_today_filter(self, page) -> None:
        try:
            for selector in [
                "button:has-text('Auction Today')",
                "a:has-text('Auction Today')",
                "[data-filter='AuctionToday']",
                "label:has-text('Auction Today')",
            ]:
                locator = page.locator(selector).first
                if await locator.count() > 0:
                    try:
                        await locator.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    await locator.click()
                    await asyncio.sleep(1.2)
                    print("[IAAI] Filtr DOM: 'Auction Today'")
                    return
        except Exception as exc:
            print(f"[IAAI] Filtr 'Auction Today' nieudany: {exc}")

    async def _apply_seller_insurance_filter(self, page) -> bool:
        """Klika sidebar 'Seller Type → Insurance Companies' w IAAI search.

        Struktura IAAI sidebar (2-step UX, zdiagnozowano w iaai_sidebar_debug):
          <li class="checkbox">
            <input type="checkbox" id="customizedSellerType">
            <label for="customizedSellerType">Seller Type</label>
          </li>
        Po kliku na #customizedSellerType lub jego label, IAAI otwiera
        dropdown / sub-panel z opcjami (Insurance Companies / Dealer / Owner).
        Wtedy klikamy konkretną opcję 'Insurance Companies'.

        Opt-in via FILTER_SELLER_INSURANCE_ONLY=true. Drastycznie redukuje
        liczbę kandydatów (typowo 5-15x mniej z całej listy)."""

        async def _debug_dump(suffix: str) -> None:
            """Debug HTML dump gdy IAAI_DEBUG_SIDEBAR=true."""
            if os.getenv("IAAI_DEBUG_SIDEBAR", "false").lower() != "true":
                return
            try:
                import time
                from pathlib import Path
                html = await page.content()
                ts = time.strftime("%Y%m%d_%H%M%S")
                cache_dir = Path(os.getenv("HTML_CACHE_DIR", "./data/html_cache"))
                cache_dir.mkdir(parents=True, exist_ok=True)
                fp = cache_dir / f"iaai_sidebar_{suffix}_{ts}.html"
                fp.write_text(html, encoding="utf-8")
                print(f"[IAAI] DEBUG {suffix}: HTML zapisany do {fp} ({len(html)//1024} KB)")
            except Exception as exc:
                print(f"[IAAI] DEBUG {suffix} dump failed: {exc}")

        # Czekaj na pełen JS render sidebar
        await asyncio.sleep(2)
        await _debug_dump("before_click")

        # Krok 1: kliknij na element 'Seller Type' (id=customizedSellerType)
        # — to otwiera dropdown/sub-list z opcjami sprzedawcy.
        toggle_selectors = [
            "#customizedSellerType",
            "label[for='customizedSellerType']",
            "input#customizedSellerType",
            "li.checkbox label:has-text('Seller Type')",
        ]
        clicked_toggle = False
        for sel in toggle_selectors:
            try:
                locator = page.locator(sel).first
                if await locator.count() > 0:
                    try:
                        await locator.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    await locator.click()
                    await asyncio.sleep(2)  # czekaj na lazy load sub-options
                    clicked_toggle = True
                    print(f"[IAAI] Klik na '{sel}' (Seller Type toggle)")
                    break
            except Exception as exc:
                continue

        if not clicked_toggle:
            print("[IAAI] Filtr sidebar 'Seller Type' nie znaleziony — fallback do client-side")
            return False

        await _debug_dump("after_toggle")

        # Krok 2: kliknij konkretną opcję 'Insurance Companies' (lub równoważną)
        # IAAI używa skrótów:
        #   - 'Insurance Companies' / 'Insurance Company'
        #   - 'ICO' = Insurance Company Owned (kod wewnętrzny)
        #   - 'Insurance' (czasem skrócone)
        insurance_selectors = [
            "label:has-text('Insurance Compan')",  # 'Insurance Companies' lub 'Insurance Company'
            "input[type=checkbox][value*='Insurance']",
            "input[type=checkbox][value*='ICO']",
            "input[type=checkbox][id*='Insurance']",
            "input[type=checkbox][name*='Insurance']",
            "a:has-text('Insurance Compan')",
            "li:has-text('Insurance Compan') input[type=checkbox]",
            "li.checkbox:has-text('Insurance') label",
        ]
        for sel in insurance_selectors:
            try:
                locator = page.locator(sel).first
                if await locator.count() > 0:
                    try:
                        await locator.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    await locator.click()
                    await asyncio.sleep(2)
                    print(f"[IAAI] Filtr DOM zaaplikowany: Seller Type → Insurance Companies (selector: '{sel}')")
                    await _debug_dump("after_insurance")
                    return True
            except Exception:
                continue

        print("[IAAI] Sub-option 'Insurance Companies' nie znaleziona po toggle — fallback do client-side")
        await _debug_dump("not_found")
        return False

    async def _apply_listing_filters(
        self,
        page,
        criteria: ClientCriteria,
        *,
        auction_window_hours: Optional[int],
        insurance_only: bool = False,
    ) -> None:
        """Orchestrator filtrów DOM. Klika filtry IAAI w DOM (rok / odometer /
        Auction Today / Seller) przed scrapingiem listy.

        - IAAI_USE_DOM_FILTERS=true → opt-in dla year/odometer/auction-today
        - FILTER_SELLER_INSURANCE_ONLY=true (lub `insurance_only` arg) → zawsze
          próbuj kliknąć Seller filter (główny win: 5-15× mniej kandydatów).
        """
        use_dom_filters = os.getenv("IAAI_USE_DOM_FILTERS", "false").lower() == "true"
        env_insurance_only = os.getenv("FILTER_SELLER_INSURANCE_ONLY", "false").lower() == "true"
        apply_seller = insurance_only or env_insurance_only

        if not use_dom_filters and not apply_seller:
            return

        if use_dom_filters:
            print("[IAAI] Aplikuję filtry DOM (IAAI_USE_DOM_FILTERS=true)...")
        try:
            if use_dom_filters:
                await self._apply_year_filter(page, criteria.year_from, criteria.year_to)
                await self._apply_odometer_filter(page, criteria.max_odometer_mi)
                if auction_window_hours is not None and auction_window_hours <= 30:
                    await self._apply_auction_today_filter(page)
            if apply_seller:
                await self._apply_seller_insurance_filter(page)
            await asyncio.sleep(2)
        except Exception as exc:
            print(f"[IAAI] Aplikacja filtrów DOM przerwana ({exc}) - lecę bez nich")

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
        """Wykrywa typ sprzedawcy z karty listing IAAI.

        Trzy strategie (od najpewniejszej do fallbackowej):
        1. **Native IAAI badge** w prawym górnym rogu karty (`<span>INSURANCE</span>` /
           `<span>DEALER</span>`). Działa BEZ AutoHelperBot.
        2. **AHB "Who sell:" chip** wstawiony przez AutoHelperBot extension
           (wymaga `USE_EXTENSIONS=true` + zalogowany AHB w przeglądarce).
        3. None gdy żadne nie pasuje (przepuszczamy do detail page).
        """
        combined = f"{html} {text}"

        # Strategia 1: Native IAAI listing badge. IAAI sam pokazuje "INSURANCE" /
        # "DEALER" jako kolorowy tag w karcie wyniku — niezależny od AHB.
        # Patrzymy na izolowane słowo (granice słowa) żeby nie złapać częściowych
        # matchów typu "INSURANCEFOO".
        badge = re.search(r"\b(INSURANCE|DEALER)\b", combined)
        if badge:
            return "insurance" if badge.group(1).upper() == "INSURANCE" else "dealer"

        # Strategia 2: AHB "Who sell:" chip (fallback).
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

        if insurance_only and candidate.seller_type != "insurance":
            # Permissive mode (default IAAI_REQUIRE_LISTING_SELLER=false) — IAAI
            # listing HTML często nie ma native badge widocznego dla regex
            # (React/lazy render); UNKNOWN przepuszczamy do detail page.
            # Strict mode (=true) — wymaga że badge ALBO AHB chip są wykrywalne;
            # odrzuca UNKNOWN. Włącz dopiero po weryfikacji że `seller insurance`
            # > 0 w logach.
            require_known = os.getenv("IAAI_REQUIRE_LISTING_SELLER", "false").lower() == "true"
            if require_known:
                return False
            if candidate.seller_type is not None:
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
        # Early exit: gdy N stron z rzędu daje 0 pasujących lotów → break.
        # Default 2 (jeśli pierwsze 2 strony dały 0 → modele rzadkie/poza oknem,
        # nie warto iterować pozostałe 3 strony × ~30s = 90s).
        empty_streak_threshold = max(1, int(os.getenv("SEARCH_EMPTY_STREAK_THRESHOLD", "2")))
        candidates: list[ListingCandidate] = []
        seen: set[str] = set()
        empty_streak = 0

        print(
            "[IAAI] Lista: filtruję auction window → insurance → damage, "
            "potem sortuję po najmniejszych uszkodzeniach"
        )
        for page_index in range(max_pages):
            await self._wait_for_listing_seller_data(page, timeout_s=15)
            page_candidates = await self._extract_current_listing_candidates(page)
            page_matches = 0
            seller_breakdown = {"insurance": 0, "dealer": 0, "unknown": 0}
            for candidate in page_candidates:
                if candidate.url in seen:
                    continue
                seen.add(candidate.url)
                seller_key = candidate.seller_type if candidate.seller_type in ("insurance", "dealer") else "unknown"
                seller_breakdown[seller_key] += 1
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
                f"seller insurance={seller_breakdown['insurance']} "
                f"dealer={seller_breakdown['dealer']} unknown={seller_breakdown['unknown']} → "
                f"{page_matches} pasuje, łącznie {len(candidates)}/{scan_limit}"
            )

            # DIAGNOSTYKA: gdy 0 dopasowań mimo wczytanych lotów — dlaczego?
            # (buyer-login mask vs model-string mismatch vs zły wynik search).
            if (
                page_matches == 0
                and page_candidates
                and os.getenv("IAAI_DEBUG_NOMATCH", "true").lower() == "true"
            ):
                try:
                    html_l = (await page.content()).lower()
                    buyer_masked = "log in as a buyer" in html_l
                except Exception:
                    buyer_masked = None
                mk = (criteria.make or "").lower()
                md = (criteria.model or "").lower()
                for c in page_candidates[:3]:
                    t = (c.row_text or "")[:160].replace("\n", " ")
                    print(
                        f"[IAAI][DBG] seller={c.seller_type} "
                        f"make_in={(mk in c.row_text.lower()) if mk else None} "
                        f"model('{md}')_in={(md in c.row_text.lower()) if md else None} "
                        f"auction={c.auction_date} buyer_masked={buyer_masked} "
                        f"row[:160]={t!r}"
                    )

            if len(candidates) >= scan_limit:
                break

            # Early exit: track empty streak. Gdy N kolejnych stron daje 0
            # pasujących lotów → przerwij paginację (oszczędność ~30s/strona).
            if page_matches == 0:
                empty_streak += 1
                if empty_streak >= empty_streak_threshold:
                    print(
                        f"[IAAI] Early exit: {empty_streak} kolejnych stron bez wyników — "
                        f"przerwij paginację (zostało {max_pages - page_index - 1} stron)"
                    )
                    break
            else:
                empty_streak = 0

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
                await asyncio.sleep(int(os.getenv("IAAI_LISTING_INITIAL_WAIT_S", "3")))

                # Sprawdź czy są wyniki
                vehicle_count = await page.locator("a[href*='/VehicleDetail']").count()
                if vehicle_count == 0:
                    print("[IAAI] Brak wyników wyszukiwania")
                    return []

                print(f"[IAAI] Znaleziono {vehicle_count} wyników")

                # Oblicz effective_insurance_only ZANIM odpalimy DOM filters —
                # filtr Seller=Insurance ma być aplikowany od razu (drastycznie
                # redukuje liczbę kandydatów do detail enrichment, nie tylko
                # gdy IAAI_USE_DOM_FILTERS=true).
                effective_insurance_only = (
                    insurance_only
                    if insurance_only is not None
                    else os.getenv("FILTER_SELLER_INSURANCE_ONLY", "false").lower() == "true"
                )

                # DOM filters (year/odometer/auction-today via IAAI_USE_DOM_FILTERS) +
                # Seller=Insurance Companies (gdy effective_insurance_only=True).
                await self._apply_listing_filters(
                    page,
                    criteria,
                    auction_window_hours=auction_window_hours,
                    insurance_only=effective_insurance_only,
                )
                if (
                    os.getenv("IAAI_USE_DOM_FILTERS", "false").lower() == "true"
                    or effective_insurance_only
                ):
                    vehicle_count_after = await page.locator("a[href*='/VehicleDetail']").count()
                    if vehicle_count_after != vehicle_count:
                        print(f"[IAAI] Po filtrach DOM: {vehicle_count_after} wyników (było {vehicle_count})")

                scan_limit = self.get_detail_scan_limit(criteria.max_results)
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

                # PARALLEL detail fetch — refactor: zamiast sekwencyjnego for,
                # użyć asyncio.gather z batch processing (concurrency limit).
                # Default 3 — bezpieczne dla Imperva (jitter zachowany per task).
                # Per scrape z 26 lotami:
                #   Sekwencyjnie:  26 × 20s = 520s (~9 min)
                #   Parallel sem=3: ceil(26/3) × 20s = 180s (~3 min)
                concurrency = max(1, int(os.getenv("IAAI_PARALLEL_DETAIL", "3")))
                total_links = len(lot_links)
                i = 0
                while i < total_links and (detail_target is None or len(saved_files) < detail_target):
                    # Batch size: ile zdąży się jeszcze "zmieścić" w detail_target
                    remaining_slots = (detail_target - len(saved_files)) if detail_target else (total_links - i)
                    batch_size = min(concurrency, total_links - i, remaining_slots)
                    batch_urls = lot_links[i:i + batch_size]

                    # Cache check synchronicznie (oszczędza task creation)
                    detail_tasks = []
                    for j, url in enumerate(batch_urls):
                        global_idx = i + j
                        if self.is_cached(url):
                            cache_path = self.get_cache_path(url)
                            saved_files.append((str(cache_path), url))
                            print(f"[IAAI] {global_idx+1}/{total_links} z cache: {cache_path.name}")
                            continue
                        detail_tasks.append(self._fetch_one_detail_parallel(context, url, global_idx, total_links))

                    if detail_tasks:
                        results = await asyncio.gather(*detail_tasks, return_exceptions=True)
                        for r in results:
                            if isinstance(r, Exception):
                                print(f"[IAAI] Detail task exception: {type(r).__name__}: {r}")
                            elif r is not None:
                                saved_files.append(r)

                    i += batch_size
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if owns_context:
                    try:
                        await context.close()
                    except Exception:
                        # TargetClosedError gdy context już zamknięty (np. crash Chrome
                        # lub close cascade). Nieblokujący — scrape zwrócił dane przed.
                        pass
                if browser is not None:
                    try:
                        await browser.close()
                    except Exception:
                        pass

        return saved_files
