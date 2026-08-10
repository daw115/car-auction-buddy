"""
Manheim (search.manheim.com) — scraper działający na sesji z wtyczki BidWise.

Manheim nie ma otwartego wyszukiwania: search.manheim.com wymaga zalogowanego
konta dealerskiego, a logowanie idzie przez OTP — nie da się go zautomatyzować
loginem/hasłem tak jak w Copart/IAAI. Sesję dostarcza wtyczka BidWise (Eridan).
Sprawdzone empirycznie: po wyłączeniu wtyczki search.manheim.com przekierowuje na
publiczne site.manheim.com — czyli to wtyczka trzyma sesję, nie same ciasteczka
profilu.

Konsekwencje projektowe:
  * własny headed kontekst przeglądarki tylko z BidWise i własnym profilem
    (browser_context.launch_manheim_context) — NIE wspólny z AuctionGate/
    AutoHelperBotem, bo te potrafią zawiesić start bundled Chromium na swoim
    service workerze i zabrałyby ze sobą Manheima. Dzięki temu Manheim nie
    zależy też od globalnych USE_EXTENSIONS/HEADLESS,
  * bez sesji zwraca 0 lotów i mówi to wprost — nie ma mocków ani obchodzenia
    logowania Manheima,
  * dane bierzemy z odpowiedzi XHR samego SPA (self-discovering), a nie z
    zakodowanych na sztywno selektorów DOM — Manheim przebudowuje front bez
    zapowiedzi, a kształt JSON-a jest znacznie stabilniejszy.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from playwright.async_api import Page, async_playwright

from parser.manheim_records import (
    as_float,
    as_int,
    extract_vehicles,
    merge_records,
    pick,
)
from parser.models import ClientCriteria
from scraper.base import BaseScraper, ListingCandidate
from scraper.browser_context import (
    MANHEIM_PROFILE_DIR,
    connect_manheim_cdp,
    launch_manheim_context,
    manheim_cdp_url,
)
from scraper.manheim_session import (
    config_ready,
    extension_dir,
    result_limit as manheim_result_limit,
    session_ready,
)

load_dotenv(override=True)

logger = logging.getLogger("scraper.manheim")

SEARCH_URL = os.getenv("MANHEIM_SEARCH_URL", "https://search.manheim.com/results").strip()

# Manheim wylogowaną sesję odsyła na publiczny serwis marketingowy albo na SSO.
_LOGGED_OUT_MARKERS = ("site.manheim.com", "auth.manheim.com", "home.manheim.com/login")

# Blok wstrzykiwany do zapisanego HTML-a — parser czyta go zamiast zgadywać DOM.
EMBEDDED_DATA_ID = "usacar-manheim-listing"

# Fallback gdy manifest nie ma pola "key" (wtedy Chromium losuje ID per profil).
_BIDWISE_FALLBACK_ID = "mapbnmkenejciggnkildgcohibbnhnmm"


def bidwise_extension_id() -> str:
    """ID wtyczki wyliczone z pola `key` w manifeście.

    Chromium liczy je jako pierwsze 16 bajtów SHA-256 klucza publicznego,
    zamapowane na alfabet a-p. Dzięki `key` w manifeście ID rozpakowanej kopii
    jest identyczne jak w Web Store, więc adres popupu jest przewidywalny —
    a tylko tak da się pokazać okno logowania BidWise w przeglądarce odpalonej
    przez Playwrighta, gdzie pasek rozszerzeń jest niedostępny.
    """
    try:
        manifest = json.loads((extension_dir() / "manifest.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(base64.b64decode(manifest["key"])).digest()[:16]
        return "".join(
            chr(ord("a") + (byte >> 4)) + chr(ord("a") + (byte & 0xF)) for byte in digest
        )
    except Exception:
        logger.debug("[Manheim] Nie wyliczyłem ID wtyczki z manifestu", exc_info=True)
        return _BIDWISE_FALLBACK_ID


def bidwise_popup_url() -> str:
    return f"chrome-extension://{bidwise_extension_id()}/popup/index.html"


class ManheimScraper(BaseScraper):
    """Scraper Manheima na własnym kontekście przeglądarki z wtyczką BidWise."""

    def __init__(self):
        super().__init__("manheim")
        self._captured: list[dict] = []

    # ------------------------------------------------------------------ query

    def build_search_query(self, criteria: ClientCriteria) -> str:
        """Manheim ma jedno pole full-text — składamy z niego rocznik+marka+model."""
        parts: list[str] = []
        if criteria.year_from and criteria.year_to and criteria.year_from == criteria.year_to:
            parts.append(str(criteria.year_from))
        parts.append(criteria.make.strip())
        model = self.normalize_model_for_query(criteria.model)
        if model:
            parts.append(model.strip())
        return " ".join(part for part in parts if part)

    # ---------------------------------------------------------------- capture

    async def _on_response(self, response) -> None:
        """Zbiera JSON-y z XHR-ów SPA. Endpoint celowo nie jest zaszyty —
        Manheim zmienia ścieżki, a my i tak filtrujemy po kształcie rekordu."""
        try:
            url = response.url
            if "manheim.com" not in url:
                return
            content_type = (response.headers or {}).get("content-type", "")
            if "json" not in content_type.lower():
                return
            payload = await response.json()
        except Exception:
            return

        records = extract_vehicles(payload)
        if not records:
            return
        # Bez locka celowo: handlery odpowiedzi lecą na tej samej pętli zdarzeń,
        # a między odczytem a zapisem listy nie ma awaita.
        self._captured.extend(records)
        logger.debug("[Manheim] %d rekordów pojazdów z %s", len(records), url)

    def _reset_capture(self) -> None:
        self._captured = []

    def _dedup_captured(self) -> list[dict]:
        return merge_records(self._captured)

    # -------------------------------------------------------------- candidate

    def _detail_url(self, record: dict, lot_id: str) -> str:
        raw = pick(record, "url")
        if isinstance(raw, str) and raw.strip():
            href = raw.strip()
            if href.startswith("http"):
                return href
            return f"https://search.manheim.com/{href.lstrip('/')}"
        return f"{SEARCH_URL}#/vdp/{lot_id}"

    def _candidate_from_record(self, record: dict) -> Optional[ListingCandidate]:
        # VIN przed identyfikatorem aukcji: pick() schodzi w zagnieżdżenia i
        # potrafi trafić na wspólne pole `id` (np. sprzedaży), przez co różne
        # pojazdy dostawały ten sam URL, nadpisywały ten sam plik i wracały
        # jako kilka kopii jednego auta. VIN jest unikalny z definicji.
        lot_id = str(pick(record, "vin") or pick(record, "lot_id") or "").strip()
        if not lot_id:
            return None

        damage_text = self.damage_text_from_values(
            pick(record, "damage"),
            pick(record, "title_type"),
            pick(record, "condition_grade"),
        )
        damage_score, damage_label = self.damage_severity_score(damage_text)
        auction_date = pick(record, "auction_date")
        return ListingCandidate(
            url=self._detail_url(record, lot_id),
            lot_id=lot_id,
            seller_type=None,
            auction_date=str(auction_date) if auction_date else None,
            damage_text=damage_text or None,
            damage_score=damage_score,
            damage_label=damage_label,
            row_text=" ".join(
                str(value)
                for value in (
                    pick(record, "year"),
                    pick(record, "make"),
                    pick(record, "model"),
                    pick(record, "trim"),
                )
                if value
            ),
            raw_data=record,
        )

    @staticmethod
    def _unique_by_url(candidates: list[ListingCandidate]) -> list[ListingCandidate]:
        """Siatka bezpieczeństwa: dwa kandydaty pod jednym URL-em to jeden plik.

        Zapisany dokument nazywamy hashem URL-a, więc kolizja cicho nadpisuje
        poprzedni lot i lista wynikowa robi się kopiami jednego auta.
        """
        seen: set[str] = set()
        unique: list[ListingCandidate] = []
        for candidate in candidates:
            if candidate.url in seen:
                logger.warning(
                    "[Manheim] Pomijam lot %s — ten sam URL co wcześniejszy (%s)",
                    candidate.lot_id,
                    candidate.url,
                )
                continue
            seen.add(candidate.url)
            unique.append(candidate)
        return unique

    def _matches_criteria(self, record: dict, criteria: ClientCriteria) -> bool:
        """Prefiltr po stronie listy — Manheim oddaje TOP 3, więc odrzucamy
        oczywiste niedopasowania zanim wydamy czas na stronę detalu."""
        year = as_int(pick(record, "year"))
        if year:
            if criteria.year_from and year < criteria.year_from:
                return False
            if criteria.year_to and year > criteria.year_to:
                return False

        make = str(pick(record, "make") or "").strip().lower()
        if make and criteria.make and criteria.make.strip().lower() not in make:
            return False

        model = str(pick(record, "model") or "").strip().lower()
        if model and criteria.model:
            wanted = criteria.model.strip().lower().replace("-", "").replace(" ", "")
            if wanted and wanted not in model.replace("-", "").replace(" ", ""):
                return False

        odometer = as_int(pick(record, "odometer"))
        if odometer and criteria.max_odometer_mi and odometer > criteria.max_odometer_mi:
            return False

        price = as_float(pick(record, "buy_now")) or as_float(pick(record, "current_bid"))
        if price and criteria.budget_usd and price > criteria.budget_usd:
            return False

        if self.damage_has_excluded_type(
            self.damage_text_from_values(pick(record, "damage"), pick(record, "title_type")),
            criteria.excluded_damage_types,
        ):
            return False

        return True

    # ------------------------------------------------------------------ pages

    async def _is_logged_in(self, page: Page) -> bool:
        """Rozstrzyga URL, nie treść strony.

        Zmierzone: wylogowana sesja jest ODSYŁANA z search.manheim.com na
        publiczne site.manheim.com. Dopóki zostajemy na search.manheim.com,
        sesja żyje. Heurystyki po tekście strony okazały się zawodne — SPA
        dorenderowuje treść z opóźnieniem i potrafiły odrzucić dobrą kartę.
        """
        url = (page.url or "").lower()
        if any(marker in url for marker in _LOGGED_OUT_MARKERS):
            return False
        if "search.manheim.com" in url:
            return True
        try:
            body = (await page.inner_text("body"))[:4000].lower()
        except Exception:
            return False
        return "manheim" in body and "sign in" not in body

    @staticmethod
    def _find_manheim_page(context) -> Optional[Page]:
        for page in context.pages:
            url = (page.url or "").lower()
            if "search.manheim.com" in url and not any(
                marker in url for marker in _LOGGED_OUT_MARKERS
            ):
                return page
        return None

    async def _await_interactive_login(self, context, page: Page, timeout_s: int) -> bool:
        """Otwiera popup BidWise i czeka aż operator się zaloguje.

        Playwright startuje Chromium bez paska rozszerzeń, więc do okna logowania
        nie ma jak kliknąć — wchodzimy w nie wprost po adresie chrome-extension://.
        Używane tylko przy jawnym MANHEIM_LOGIN_WAIT_SECONDS (albo z probe);
        zwykły scrape nigdy nie czeka na człowieka.
        """
        popup = None
        try:
            popup = await context.new_page()
            await popup.goto(bidwise_popup_url(), wait_until="domcontentloaded", timeout=20000)
        except Exception as exc:
            logger.warning("[Manheim] Nie otworzyłem popupu BidWise (%s): %s", bidwise_popup_url(), exc)

        print(
            f"\n>>> Zaloguj się do BidWise w otwartej zakładce ({bidwise_popup_url()}).\n"
            f">>> Czekam do {timeout_s}s na aktywną sesję Manheima...\n"
        )

        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(5)
            try:
                await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                if await self._is_logged_in(page):
                    print(">>> Sesja Manheima aktywna, jadę dalej.\n")
                    if popup is not None:
                        await popup.close()
                    return True
            except Exception:
                logger.debug("[Manheim] Sprawdzenie sesji nieudane, ponawiam", exc_info=True)

        logger.warning("[Manheim] Nie doczekałem się zalogowanej sesji (%ds)", timeout_s)
        return False

    async def _run_search(self, page: Page, query: str) -> bool:
        """Wpisuje zapytanie w wyszukiwarkę SPA. Zwraca False gdy nie znaleziono pola."""
        selectors = (
            "input[type='search']",
            "input[name*='search' i]",
            "input[placeholder*='search' i]",
            "input[aria-label*='search' i]",
        )
        for selector in selectors:
            locator = page.locator(selector)
            try:
                if await locator.count() == 0:
                    continue
                field = locator.first
                await field.click(timeout=5000)
                await field.fill(query, timeout=5000)
                await field.press("Enter")
                return True
            except Exception:
                continue
        logger.warning("[Manheim] Nie znalazłem pola wyszukiwania (%s)", ", ".join(selectors))
        return False

    def _save_detail(self, url: str, html: str, record: dict) -> Path:
        """Zapisuje HTML detalu z doklejonym rekordem JSON z listy.

        Parser czyta wstrzyknięty blok zamiast polegać na klasach CSS Manheima —
        dzięki temu zmiana frontu nie wywraca parsowania, a zapisany plik jest
        samowystarczalny (da się z niego odtworzyć lota bez przeglądarki).
        """
        blob = json.dumps(record, ensure_ascii=False, default=str)
        marker = (
            f'<script id="{EMBEDDED_DATA_ID}" type="application/json">{blob}</script>'
        )
        if "</body>" in html:
            html = html.replace("</body>", f"{marker}</body>", 1)
        else:
            html = f"{html}{marker}"
        return self.save_html(url, html)

    def _save_listing_only(self, candidate: ListingCandidate) -> Optional[tuple[str, str]]:
        """Zapisuje dokument zbudowany wyłącznie z rekordu z listy, bez wizyty
        na stronie lota. Parser czyta wstrzyknięty JSON, więc wynik jest pełny
        poza zdjęciami."""
        try:
            html = (
                "<html><head><title>Manheim listing</title></head><body>"
                f"<p>Rekord z listy Manheim (bez wizyty na stronie lota): {candidate.lot_id}</p>"
                "</body></html>"
            )
            path = self._save_detail(candidate.url, html, candidate.raw_data)
            return str(path), candidate.url
        except Exception as exc:
            logger.warning("[Manheim] Zapis rekordu %s nieudany: %s", candidate.lot_id, exc)
            return None

    async def _fetch_detail(self, context, candidate: ListingCandidate) -> Optional[tuple[str, str]]:
        page = None
        try:
            page = await context.new_page()
            await self.setup_page(page)
            await page.goto(
                candidate.url,
                wait_until="domcontentloaded",
                timeout=int(os.getenv("MANHEIM_NAV_TIMEOUT_MS", "45000")),
            )
            await asyncio.sleep(float(os.getenv("MANHEIM_DETAIL_WAIT_SECONDS", "6")))
            html = await page.content()
            if self.text_has_security_challenge(html):
                logger.warning("[Manheim] Security challenge na detalu %s", candidate.url)
                return None
            path = self._save_detail(candidate.url, html, candidate.raw_data)
            return str(path), candidate.url
        except Exception as exc:
            logger.warning("[Manheim] Detal %s nieudany: %s", candidate.url, exc)
            return None
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

    # ----------------------------------------------------------------- scrape

    # ------------------------------------------------------------- kolektor

    @staticmethod
    def _collector_records() -> list[dict]:
        """Rekordy zebrane przez rozszerzenie manheim-collector.

        Import leniwy: scraper bywa używany bez uruchomionego API, a magazyn
        żyje w procesie backendu.
        """
        try:
            from api.manheim_ingest import vehicles
        except Exception:
            logger.debug("[Manheim] Magazyn kolektora niedostępny", exc_info=True)
            return []
        return vehicles()

    @staticmethod
    def _request_job(keyword: str) -> Optional[str]:
        try:
            from api.manheim_jobs import create
        except Exception:
            logger.debug("[Manheim] Kolejka zadań niedostępna", exc_info=True)
            return None
        return create(keyword)

    @staticmethod
    async def _await_job(job_id: str, timeout_s: float) -> tuple[list[dict], Optional[str]]:
        """Czeka aż rozszerzenie wykona zlecone wyszukiwanie."""
        try:
            from api.manheim_jobs import get
        except Exception:
            return [], "kolejka zadań niedostępna"

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_s
        while loop.time() < deadline:
            job = get(job_id)
            if job and job["status"] in ("done", "error"):
                return job["records"], job["error"]
            await asyncio.sleep(1.0)
        return [], f"brak odpowiedzi rozszerzenia w {int(timeout_s)}s"

    async def _from_collector(self, criteria: ClientCriteria, limit: int) -> list[tuple[str, str]]:
        # Najpierw zlecamy rozszerzeniu wyszukiwanie na żywo. Backend nie może
        # odpytać Manheima sam — patrz api/manheim_jobs.py.
        timeout_s = float(os.getenv("MANHEIM_JOB_TIMEOUT_SECONDS", "60"))
        records: list[dict] = []
        if timeout_s > 0:
            keyword = self.build_search_query(criteria)
            job_id = self._request_job(keyword)
            if job_id:
                logger.info("[Manheim] Zlecam wyszukiwanie %r (czekam do %.0fs)", keyword, timeout_s)
                records, error = await self._await_job(job_id, timeout_s)
                if error:
                    logger.warning("[Manheim] Zlecenie nieudane: %s", error)

        # Fallback: to, co kolektor zebrał przy okazji ręcznych wyszukiwań.
        if not records:
            records = self._collector_records()
        if not records:
            logger.warning(
                "[Manheim] Magazyn kolektora pusty. Zainstaluj extensions/manheim-collector "
                "w Chrome z BidWise i wyszukaj na Manheimie — dane trafiają do "
                "/api/manheim/ingest."
            )
            return []

        matching = [record for record in records if self._matches_criteria(record, criteria)]
        logger.info(
            "[Manheim] Kolektor: %d rekordów, po kryteriach %d", len(records), len(matching)
        )

        candidates = [
            candidate
            for candidate in (self._candidate_from_record(record) for record in matching)
            if candidate is not None
        ]
        candidates.sort(key=self.candidate_sort_key)
        candidates = self._unique_by_url(candidates)[:limit]

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

        saved: list[tuple[str, str]] = []
        for candidate in candidates:
            result = self._save_listing_only(candidate)
            if result:
                saved.append(result)
        logger.info("[Manheim] Kolektor oddał %d lotów", len(saved))
        return saved

    async def scrape(
        self,
        criteria: ClientCriteria,
        *,
        min_auction_window_hours: Optional[int] = None,
        auction_window_hours: Optional[int] = None,
        insurance_only: Optional[bool] = None,
        login_wait_s: Optional[int] = None,
    ) -> list[tuple[str, str]]:
        """Zwraca listę krotek (ścieżka HTML, URL lota) — kontrakt jak Copart/IAAI.

        login_wait_s > 0 włącza jednorazowe, interaktywne logowanie do BidWise
        (używa tego scripts/manheim_probe.py). Domyślnie 0 — zwykły scrape nigdy
        nie blokuje się w oczekiwaniu na człowieka.
        """
        saved_files: list[tuple[str, str]] = []
        self.last_listing_metadata = {}
        self._reset_capture()

        # Świadomie config_ready(), nie session_ready(): istnienie profilu to
        # tylko proxy dla /api/capabilities. Tu autorytatywny jest _is_logged_in()
        # niżej — dzięki temu pierwszy przebieg (probe) może profil dopiero założyć.
        if not config_ready():
            logger.warning(
                "[Manheim] Pomijam źródło: wymagane USE_EXTENSIONS=true, HEADLESS=false "
                "oraz rozpakowana wtyczka BidWise w %s",
                extension_dir(),
            )
            return []

        limit = manheim_result_limit(criteria.max_results)

        # Domyślnie bierzemy dane z kolektora w przeglądarce. Ścieżka
        # Playwright/CDP jest nieużywalna: BidWise trzyma slot chrome.debugger
        # i podpięcie się zamyka kartę w ~5 sekund (zmierzone).
        if os.getenv("MANHEIM_SOURCE_MODE", "collector").strip().lower() == "collector":
            return await self._from_collector(criteria, limit)

        query = self.build_search_query(criteria)
        logger.info("[Manheim] Szukam: %r (limit %d)", query, limit)

        async with async_playwright() as p:
            cdp_url = manheim_cdp_url()
            if cdp_url:
                context = await connect_manheim_cdp(p, cdp_url)
            else:
                context = await launch_manheim_context(p)
                await asyncio.sleep(3)

            page = None
            owns_page = False
            try:
                if cdp_url:
                    # Nie otwieramy własnej karty. BidWise autoryzuje sesję Manheima
                    # PER KARTA (w jej kodzie: tabs_manheim.com, previousTabStates.manheim,
                    # extra_tabs_closed_before_manheim_reauth) — obca karta dostaje
                    # wylogowane site.manheim.com, a jej pojawienie się potrafi
                    # sprowokować wtyczkę do zamknięcia tych prawidłowych.
                    page = self._find_manheim_page(context)
                    if page is None:
                        logger.warning(
                            "[Manheim] Brak otwartej karty %s w Chrome pod %s. "
                            "Otwórz Manheima przez BidWise (przycisk przy 'Manheim' "
                            "albo 'Restore Tabs') i zostaw kartę otwartą.",
                            SEARCH_URL,
                            cdp_url,
                        )
                        return []
                    logger.info("[Manheim] Używam istniejącej karty: %s", page.url)
                else:
                    page = await context.new_page()
                    owns_page = True
                    await self.setup_page(page)
                    await page.goto(
                        SEARCH_URL,
                        wait_until="domcontentloaded",
                        timeout=int(os.getenv("MANHEIM_NAV_TIMEOUT_MS", "45000")),
                    )
                    await asyncio.sleep(float(os.getenv("MANHEIM_BOOT_WAIT_SECONDS", "8")))
                page.on("response", lambda response: asyncio.create_task(self._on_response(response)))

                if not await self._is_logged_in(page):
                    wait_s = (
                        login_wait_s
                        if login_wait_s is not None
                        else int(os.getenv("MANHEIM_LOGIN_WAIT_SECONDS", "0"))
                    )
                    logger.warning(
                        "[Manheim] Brak zalogowanej sesji (URL: %s). %s",
                        page.url,
                        f"Chrome po CDP: {cdp_url}" if cdp_url else f"Profil: {MANHEIM_PROFILE_DIR}",
                    )
                    if wait_s <= 0 or not await self._await_interactive_login(
                        context, page, wait_s
                    ):
                        return []

                if not await self._run_search(page, query):
                    return []
                await asyncio.sleep(float(os.getenv("MANHEIM_RESULTS_WAIT_SECONDS", "12")))

                records = self._dedup_captured()
                logger.info("[Manheim] Rekordów z wyszukiwarki: %d", len(records))
                if not records:
                    logger.warning(
                        "[Manheim] Wyszukiwarka nie zwróciła rozpoznanych rekordów pojazdów "
                        "— sprawdź czy zapytanie %r daje wyniki w UI.",
                        query,
                    )
                    return []

                matching = [record for record in records if self._matches_criteria(record, criteria)]
                logger.info("[Manheim] Po prefiltrze kryteriów: %d", len(matching))

                candidates = [
                    candidate
                    for candidate in (self._candidate_from_record(record) for record in matching)
                    if candidate is not None
                ]
                candidates.sort(key=self.candidate_sort_key)
                candidates = candidates[:limit]

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

                # W trybie CDP domyślnie NIE otwieramy stron detali. Każda nowa karta
                # manheim.com prowokuje BidWise do sprzątania kart i ponownej
                # autoryzacji, a ta ma limit prób z 10-minutową karencją. Rekord
                # z listy i tak trafia do zapisanego dokumentu, więc parser ma
                # komplet — strona detalu dokłada wyłącznie zdjęcia.
                fetch_details = os.getenv(
                    "MANHEIM_FETCH_DETAILS", "false" if cdp_url else "true"
                ).strip().lower() == "true"

                for candidate in candidates:
                    if fetch_details:
                        result = await self._fetch_detail(context, candidate)
                        await self.random_delay(1.0, 2.5)
                    else:
                        result = self._save_listing_only(candidate)
                    if result:
                        saved_files.append(result)

                logger.info("[Manheim] Zapisano %d detali", len(saved_files))
                return saved_files
            finally:
                # Karty operatora nie zamykamy — jest nośnikiem sesji BidWise.
                if page is not None and owns_page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                try:
                    # NIE zamykamy niczego po CDP. Browser.close() na połączeniu
                    # connect_over_cdp zamyka kontekst, do którego się podpięliśmy —
                    # czyli WSZYSTKIE karty operatora, razem z uwierzytelnioną kartą
                    # Manheima. Zerwanie samego połączenia załatwia wyjście z
                    # async_playwright().
                    if not cdp_url:
                        await context.close()
                except Exception:
                    pass
