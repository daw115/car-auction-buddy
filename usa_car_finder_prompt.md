# USA Car Finder — pełny prompt dla Claude Code

Zbuduj kompletną aplikację `usa-car-finder` do wyszukiwania, analizy i raportowania aut z amerykańskich aukcji Copart i IAAI. Aplikacja działa lokalnie na komputerze i wystawia interfejs webowy pod `http://localhost:8000`.

---

## Architektura systemu

```
Klient podaje kryteria (marka, model, rocznik, budżet, przebieg, uszkodzenia)
  → Scraper Playwright pobiera strony wyników z Copart + IAAI
  → Każdy lot zapisywany jako plik .html na dysku (cache)
  → Opcjonalnie: Playwright z rozszerzeniami AuctionGate + AutoHelperBot
    wzbogaca loty o: pełny VIN, cenę rezerwową, typ sprzedawcy, kalkulator dostawy
  → Parser HTML wyciąga dane do modeli Pydantic (JSON)
  → Claude API analizuje loty: opłacalność, czerwone flagi, ranking, opis PL
  → Raport PDF generowany przez Jinja2 + WeasyPrint
  → FastAPI serwuje frontend i API pod localhost:8000
```

---

## Struktura katalogów do utworzenia

```
usa-car-finder/
├── scraper/
│   ├── __init__.py
│   ├── base.py
│   ├── copart.py
│   ├── iaai.py
│   └── extension_enricher.py
├── parser/
│   ├── __init__.py
│   ├── models.py
│   ├── copart_parser.py
│   └── iaai_parser.py
├── ai/
│   ├── __init__.py
│   └── analyzer.py
├── report/
│   ├── __init__.py
│   ├── generator.py
│   └── templates/
│       └── report.html.j2
├── api/
│   ├── __init__.py
│   ├── main.py
│   └── static/
│       └── index.html
├── extensions/
│   ├── auctiongate/         ← użytkownik wkleja rozpakowane rozszerzenie
│   └── autohelperbot/       ← użytkownik wkleja rozpakowane rozszerzenie
├── data/
│   ├── html_cache/
│   │   ├── copart/
│   │   └── iaai/
│   ├── chrome_profile/
│   └── reports/
├── requirements.txt
├── .env.example
├── .env                     ← NIE commitować
└── README.md
```

---

## Plik: requirements.txt

```
playwright==1.44.0
beautifulsoup4==4.12.3
lxml==5.2.2
pydantic==2.7.1
fastapi==0.111.0
uvicorn==0.29.0
anthropic==0.28.0
jinja2==3.1.4
weasyprint==62.3
python-dotenv==1.0.1
httpx==0.27.0
```

---

## Plik: .env.example

```
ANTHROPIC_API_KEY=sk-ant-...
MAX_RESULTS_PER_SOURCE=30
HEADLESS=true
SLOW_MO_MS=1500
HTML_CACHE_DIR=./data/html_cache
REPORTS_DIR=./data/reports
CHROME_PROFILE_DIR=./data/chrome_profile
USE_EXTENSIONS=false
```

---

## Plik: parser/models.py

```python
from pydantic import BaseModel, Field
from typing import Optional


class CarLot(BaseModel):
    source: str                              # "copart" | "iaai"
    lot_id: str
    url: str
    html_file: Optional[str] = None

    # Dane podstawowe
    vin: Optional[str] = None
    full_vin: Optional[str] = None           # pełny VIN z rozszerzenia (Copart ukrywa ostatnie 6 znaków)
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    odometer_mi: Optional[int] = None
    odometer_km: Optional[int] = None

    # Uszkodzenia i tytuł
    damage_primary: Optional[str] = None
    damage_secondary: Optional[str] = None
    title_type: Optional[str] = None        # Clean / Salvage / Rebuilt / Parts Only / Flood

    # Ceny
    current_bid_usd: Optional[float] = None
    buy_now_price_usd: Optional[float] = None
    seller_reserve_usd: Optional[float] = None   # cena rezerwowa z rozszerzenia

    # Sprzedawca (z rozszerzenia AuctionGate/AutoHelperBot)
    seller_type: Optional[str] = None       # "insurance" | "dealer" | "unknown"

    # Lokalizacja
    location_state: Optional[str] = None
    location_city: Optional[str] = None

    # Aukcja
    auction_date: Optional[str] = None
    keys: Optional[bool] = None
    airbags_deployed: Optional[bool] = None

    # Media
    images: list[str] = Field(default_factory=list)

    # Metadane
    enriched_by_extension: bool = False
    delivery_cost_estimate_usd: Optional[float] = None
    raw_data: dict = Field(default_factory=dict)


class ClientCriteria(BaseModel):
    make: str
    model: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    budget_usd: float
    max_odometer_mi: Optional[int] = None
    allowed_damage_types: list[str] = Field(default_factory=list)
    excluded_damage_types: list[str] = Field(
        default_factory=lambda: ["Flood", "Fire"]
    )
    max_results: int = 30
    sources: list[str] = Field(default_factory=lambda: ["copart", "iaai"])


class AIAnalysis(BaseModel):
    lot_id: str
    score: float = Field(ge=0, le=10)
    recommendation: str              # "POLECAM" | "RYZYKO" | "ODRZUĆ"
    red_flags: list[str] = Field(default_factory=list)
    estimated_repair_usd: Optional[int] = None
    estimated_total_cost_usd: Optional[int] = None
    client_description_pl: str
    ai_notes: Optional[str] = None


class AnalyzedLot(BaseModel):
    lot: CarLot
    analysis: AIAnalysis
```

---

## Plik: scraper/base.py

```python
import asyncio
import hashlib
import os
import random
from pathlib import Path
from playwright.async_api import Page
from dotenv import load_dotenv

load_dotenv()

HTML_CACHE_DIR = Path(os.getenv("HTML_CACHE_DIR", "./data/html_cache"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO_MS = int(os.getenv("SLOW_MO_MS", "1500"))


class BaseScraper:
    def __init__(self, source_name: str):
        self.source_name = source_name
        self.cache_dir = HTML_CACHE_DIR / source_name
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_path(self, url: str) -> Path:
        url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
        return self.cache_dir / f"{url_hash}.html"

    def is_cached(self, url: str) -> bool:
        return self.get_cache_path(url).exists()

    def save_html(self, url: str, html: str) -> Path:
        path = self.get_cache_path(url)
        path.write_text(html, encoding="utf-8")
        return path

    def load_html(self, url: str) -> str:
        return self.get_cache_path(url).read_text(encoding="utf-8")

    async def random_delay(self, min_s: float = 2.0, max_s: float = 5.0):
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def setup_page(self, page: Page):
        await page.set_extra_http_headers({
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        # Blokuj obrazy i fonty żeby przyspieszyć scraping
        await page.route(
            "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,otf}",
            lambda route: route.abort()
        )
```

---

## Plik: scraper/copart.py

```python
import asyncio
from playwright.async_api import async_playwright
from .base import BaseScraper, HEADLESS, SLOW_MO_MS
from parser.models import ClientCriteria


class CopartScraper(BaseScraper):
    BASE_URL = "https://www.copart.com"

    def __init__(self):
        super().__init__("copart")

    def build_search_url(self, criteria: ClientCriteria) -> str:
        parts = [criteria.make]
        if criteria.model:
            parts.append(criteria.model)
        query = "%20".join(parts)
        url = f"{self.BASE_URL}/lot-list?query={query}"
        if criteria.year_from:
            url += f"&filters[YEAR][0]={criteria.year_from}"
        if criteria.year_to:
            url += f"&filters[YEAR][1]={criteria.year_to}"
        if criteria.max_odometer_mi:
            url += f"&filters[OD][0]=0&filters[OD][1]={criteria.max_odometer_mi}"
        return url

    async def scrape(self, criteria: ClientCriteria) -> list[str]:
        """Zwraca listę ścieżek do zapisanych plików HTML."""
        saved_files = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO_MS)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            await self.setup_page(page)

            search_url = self.build_search_url(criteria)
            print(f"[Copart] Szukam: {search_url}")
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
            await self.random_delay(3, 6)

            # Zbierz linki do lotów
            lot_links = await page.eval_on_selector_all(
                "a[href*='/lot/']",
                "els => [...new Set(els.map(e => e.href))].filter(h => /\/lot\/\d+/.test(h))"
            )
            lot_links = lot_links[:criteria.max_results]
            print(f"[Copart] Znaleziono {len(lot_links)} lotów")

            for i, url in enumerate(lot_links):
                if self.is_cached(url):
                    cache_path = self.get_cache_path(url)
                    saved_files.append(str(cache_path))
                    print(f"[Copart] {i+1}/{len(lot_links)} z cache: {cache_path.name}")
                    continue
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    await self.random_delay(2, 4)
                    html = await page.content()
                    path = self.save_html(url, html)
                    saved_files.append(str(path))
                    print(f"[Copart] {i+1}/{len(lot_links)} zapisano: {path.name}")
                except Exception as e:
                    print(f"[Copart] Błąd {url}: {e}")

            await browser.close()

        return saved_files
```

---

## Plik: scraper/iaai.py

```python
import asyncio
from playwright.async_api import async_playwright
from .base import BaseScraper, HEADLESS, SLOW_MO_MS
from parser.models import ClientCriteria


class IAAIScraper(BaseScraper):
    BASE_URL = "https://www.iaai.com"

    def __init__(self):
        super().__init__("iaai")

    def build_search_url(self, criteria: ClientCriteria) -> str:
        url = f"{self.BASE_URL}/Search?makes={criteria.make}"
        if criteria.model:
            url += f"&models={criteria.model}"
        if criteria.year_from:
            url += f"&yearFrom={criteria.year_from}"
        if criteria.year_to:
            url += f"&yearTo={criteria.year_to}"
        if criteria.max_odometer_mi:
            url += f"&odometerMax={criteria.max_odometer_mi}"
        return url

    async def scrape(self, criteria: ClientCriteria) -> list[str]:
        """Zwraca listę ścieżek do zapisanych plików HTML."""
        saved_files = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO_MS)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            await self.setup_page(page)

            search_url = self.build_search_url(criteria)
            print(f"[IAAI] Szukam: {search_url}")
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
            await self.random_delay(3, 6)

            # Zbierz linki do lotów IAAI
            lot_links = await page.eval_on_selector_all(
                "a[href*='/vehicle/']",
                "els => [...new Set(els.map(e => e.href))].filter(h => /\/vehicle\/\d+/.test(h))"
            )
            lot_links = lot_links[:criteria.max_results]
            print(f"[IAAI] Znaleziono {len(lot_links)} lotów")

            for i, url in enumerate(lot_links):
                if self.is_cached(url):
                    cache_path = self.get_cache_path(url)
                    saved_files.append(str(cache_path))
                    print(f"[IAAI] {i+1}/{len(lot_links)} z cache: {cache_path.name}")
                    continue
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    await self.random_delay(2, 4)
                    html = await page.content()
                    path = self.save_html(url, html)
                    saved_files.append(str(path))
                    print(f"[IAAI] {i+1}/{len(lot_links)} zapisano: {path.name}")
                except Exception as e:
                    print(f"[IAAI] Błąd {url}: {e}")

            await browser.close()

        return saved_files
```

---

## Plik: scraper/extension_enricher.py

```python
"""
Wzbogaca dane lotów używając rozszerzeń Chrome: AuctionGate i AutoHelperBot.

Rozszerzenia wstrzykują do DOM stron Copart/IAAI:
  - Pełny VIN (aukcje ukrywają ostatnie 6 znaków)
  - Cenę rezerwową sprzedawcy (seller reserve)
  - Typ sprzedawcy: ubezpieczyciel vs dealer/reseller
  - Kalkulator kosztów dostawy do kraju docelowego

WYMAGANIE: Rozpakuj pliki CRX rozszerzeń do katalogów:
  ./extensions/auctiongate/
  ./extensions/autohelperbot/

Pobierz CRX z:
  AuctionGate:    https://chrome-stats.com/d/ehpiejnmbdjkaplmbafaejdhodalfbie/download
  AutoHelperBot:  https://chrome-stats.com/d/fojpkmgahmlajoheocnkebaoodepoekj/download

Zmień .crx na .zip i rozpakuj do odpowiednich katalogów.
"""

import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

EXTENSION_DIRS = [
    Path("./extensions/auctiongate"),
    Path("./extensions/autohelperbot"),
]
CHROME_PROFILE_DIR = Path(os.getenv("CHROME_PROFILE_DIR", "./data/chrome_profile"))


class ExtensionEnricher:

    def _get_extensions_arg(self) -> str:
        existing = [str(p.resolve()) for p in EXTENSION_DIRS if p.exists()]
        return ",".join(existing)

    async def enrich_lot(self, url: str, html_cache_path: Path) -> dict:
        """
        Otwiera stronę lota z załadowanymi rozszerzeniami.
        Wyciąga dane wstrzyknięte przez AuctionGate/AutoHelperBot.
        Nadpisuje plik HTML w cache wzbogaconym contentem.
        Zwraca słownik z dodatkowymi danymi.
        """
        extensions_arg = self._get_extensions_arg()
        if not extensions_arg:
            print("[Enricher] Brak rozszerzeń w ./extensions/ — pomijam wzbogacanie")
            return {}

        CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            # Rozszerzenia wymagają trybu headed (nie headless)
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(CHROME_PROFILE_DIR),
                headless=False,
                args=[
                    f"--disable-extensions-except={extensions_arg}",
                    f"--load-extension={extensions_arg}",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
                slow_mo=2000,
            )
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                # Daj rozszerzeniom czas na wstrzyknięcie danych
                await asyncio.sleep(5)

                # Wyciągnij dane wstrzyknięte przez rozszerzenia
                # Selektory mogą wymagać dostosowania po inspekcji DOM w przeglądarce
                enriched = await page.evaluate("""
                    () => {
                        const get = (sel) => {
                            const el = document.querySelector(sel);
                            return el ? el.innerText.trim() : null;
                        };
                        const getAttr = (sel, attr) => {
                            const el = document.querySelector(sel);
                            return el ? el.getAttribute(attr) : null;
                        };

                        return {
                            // AuctionGate — cena rezerwowa
                            seller_reserve: get('[data-auctiongate-reserve]')
                                || get('.ag-reserve-price')
                                || get('[class*="auctiongate"][class*="reserve"]'),

                            // AuctionGate — typ sprzedawcy
                            seller_type: get('[data-auctiongate-seller-type]')
                                || get('.ag-seller-type'),

                            // AuctionGate — pełny VIN
                            full_vin: get('[data-auctiongate-vin]')
                                || get('.ag-full-vin')
                                || getAttr('[data-full-vin]', 'data-full-vin'),

                            // AuctionGate — szacunek dostawy
                            delivery_cost: get('[data-auctiongate-delivery]')
                                || get('.ag-delivery-cost'),

                            // AutoHelperBot — cena rezerwowa
                            ahb_reserve: get('[class*="autohelper"][class*="reserve"]')
                                || get('.ahb-reserve-price'),

                            // AutoHelperBot — typ sprzedawcy
                            ahb_seller_type: get('[class*="autohelper"][class*="seller"]'),

                            enriched_by_extension: true,
                        };
                    }
                """)

                # Zapisz wzbogacony HTML (nadpisuje poprzedni cache)
                enriched_html = await page.content()
                html_cache_path.write_text(enriched_html, encoding="utf-8")

                reserve = enriched.get("seller_reserve") or enriched.get("ahb_reserve")
                seller = enriched.get("seller_type") or enriched.get("ahb_seller_type")
                vin = enriched.get("full_vin")
                print(f"[Enricher] OK: reserve={reserve} | seller={seller} | vin={vin}")
                return enriched

            except Exception as e:
                print(f"[Enricher] Błąd dla {url}: {e}")
                return {}
            finally:
                await context.close()

    async def enrich_all(self, lots: list[tuple[str, Path]]) -> dict[str, dict]:
        """Wzbogaca listę (url, cache_path). Przetwarza sekwencyjnie."""
        results = {}
        for url, cache_path in lots:
            results[url] = await self.enrich_lot(url, cache_path)
            await asyncio.sleep(3)
        return results
```

---

## Plik: parser/copart_parser.py

```python
import re
from bs4 import BeautifulSoup
from pathlib import Path
from .models import CarLot


def parse_price(text: str) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def parse_odometer(text: str) -> tuple[int | None, int | None]:
    if not text:
        return None, None
    nums = re.findall(r"\d+", text.replace(",", ""))
    if not nums:
        return None, None
    mi = int(nums[0])
    return mi, round(mi * 1.60934)


def parse_copart_html(html_file: Path) -> CarLot | None:
    try:
        soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "lxml")

        def txt(selector: str) -> str:
            el = soup.select_one(selector)
            return el.get_text(strip=True) if el else ""

        # Lot ID z nazwy pliku
        lot_id = html_file.stem

        # VIN — Copart ukrywa ostatnie 6 znaków, rozszerzenie odkrywa pełny
        vin_raw = (
            txt("[data-uname='lotdetailVin'] span")
            or txt(".vin-number")
            or txt("[class*='vin']")
        )

        # Rok, marka, model z tytułu
        title_text = txt("h1.lot-title") or txt(".lot-description h1") or txt("title")
        year_match = re.search(r"\b(19|20)\d{2}\b", title_text)
        year = int(year_match.group()) if year_match else None

        # Odometer
        odo_text = (
            txt("[data-uname='lotdetailOdometer']")
            or txt(".lot-odometer")
            or txt("[class*='odometer']")
        )
        mi, km = parse_odometer(odo_text)

        # Uszkodzenia
        damage_primary = (
            txt("[data-uname='lotdetailDamagetype']")
            or txt(".damage-primary")
            or txt("[class*='damage-type']")
        )
        damage_secondary = txt("[data-uname='lotdetailSecondarydamage']")

        # Tytuł
        title_type = (
            txt("[data-uname='lotdetailTitletypes']")
            or txt(".title-type")
            or txt("[class*='title-type']")
        )

        # Cena
        bid_text = (
            txt("[data-uname='lotdetailCurrentbid']")
            or txt(".bid-value")
            or txt("[class*='current-bid']")
        )
        current_bid = parse_price(bid_text)

        # Lokalizacja
        location = (
            txt("[data-uname='lotdetailLocation']")
            or txt(".lot-location")
        )
        city = location.split(",")[0].strip() if "," in location else location
        state = location.split(",")[-1].strip() if "," in location else None

        # Zdjęcia (tylko pierwsze 5)
        images = [
            img.get("src", "")
            for img in soup.select(".image-block img, .lot-image img, [class*='lot-img'] img")
            if img.get("src", "").startswith("http")
        ][:5]

        # Flagi bezpieczeństwa
        page_text = soup.get_text().lower()
        airbags_deployed = "deployed" in page_text and "airbag" in page_text
        keys = "yes" in txt(".lot-keys").lower() if txt(".lot-keys") else None

        return CarLot(
            source="copart",
            lot_id=lot_id,
            url=f"https://www.copart.com/lot/{lot_id}",
            html_file=str(html_file),
            vin=vin_raw or None,
            year=year,
            odometer_mi=mi,
            odometer_km=km,
            damage_primary=damage_primary or None,
            damage_secondary=damage_secondary or None,
            title_type=title_type or None,
            current_bid_usd=current_bid,
            location_city=city or None,
            location_state=state,
            images=images,
            airbags_deployed=airbags_deployed,
            keys=keys,
        )

    except Exception as e:
        print(f"[Parser/Copart] Błąd {html_file.name}: {e}")
        return None


def parse_all_copart(cache_dir: Path) -> list[CarLot]:
    results = []
    files = list(cache_dir.glob("*.html"))
    for f in files:
        lot = parse_copart_html(f)
        if lot:
            results.append(lot)
    print(f"[Parser/Copart] Sparsowano {len(results)}/{len(files)} plików")
    return results
```

---

## Plik: parser/iaai_parser.py

```python
import re
from bs4 import BeautifulSoup
from pathlib import Path
from .models import CarLot
from .copart_parser import parse_price, parse_odometer


def parse_iaai_html(html_file: Path) -> CarLot | None:
    try:
        soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "lxml")

        def txt(selector: str) -> str:
            el = soup.select_one(selector)
            return el.get_text(strip=True) if el else ""

        lot_id = html_file.stem

        # VIN
        vin_raw = (
            txt("[class*='vin']")
            or txt("[data-vin]")
            or txt(".vehicle-vin")
        )

        # Rok z tytułu
        title_text = txt("h1") or txt("title")
        year_match = re.search(r"\b(19|20)\d{2}\b", title_text)
        year = int(year_match.group()) if year_match else None

        # Marka i model
        make = txt("[class*='vehicle-make']") or txt("[class*='make']")
        model = txt("[class*='vehicle-model']") or txt("[class*='model']")

        # Odometer
        odo_text = txt("[class*='odometer']") or txt("[class*='mileage']")
        mi, km = parse_odometer(odo_text)

        # Uszkodzenia
        damage_primary = (
            txt("[class*='damage-type']")
            or txt("[class*='primary-damage']")
        )

        # Tytuł
        title_type = (
            txt("[class*='title-type']")
            or txt("[class*='document-type']")
        )

        # Cena
        bid_text = (
            txt("[class*='current-bid']")
            or txt("[class*='buy-now']")
        )
        current_bid = parse_price(bid_text)

        # Lokalizacja
        location = txt("[class*='location']") or txt("[class*='yard']")
        city = location.split(",")[0].strip() if "," in location else location
        state = location.split(",")[-1].strip() if "," in location else None

        # Zdjęcia
        images = [
            img.get("src", "")
            for img in soup.select("[class*='vehicle-img'] img, [class*='photo'] img")
            if img.get("src", "").startswith("http")
        ][:5]

        page_text = soup.get_text().lower()
        airbags_deployed = "deployed" in page_text and "airbag" in page_text

        return CarLot(
            source="iaai",
            lot_id=lot_id,
            url=f"https://www.iaai.com/vehicle/{lot_id}",
            html_file=str(html_file),
            vin=vin_raw or None,
            year=year,
            make=make or None,
            model=model or None,
            odometer_mi=mi,
            odometer_km=km,
            damage_primary=damage_primary or None,
            title_type=title_type or None,
            current_bid_usd=current_bid,
            location_city=city or None,
            location_state=state,
            images=images,
            airbags_deployed=airbags_deployed,
        )

    except Exception as e:
        print(f"[Parser/IAAI] Błąd {html_file.name}: {e}")
        return None


def parse_all_iaai(cache_dir: Path) -> list[CarLot]:
    results = []
    files = list(cache_dir.glob("*.html"))
    for f in files:
        lot = parse_iaai_html(f)
        if lot:
            results.append(lot)
    print(f"[Parser/IAAI] Sparsowano {len(results)}/{len(files)} plików")
    return results
```

---

## Plik: ai/analyzer.py

```python
import anthropic
import json
import os
from parser.models import CarLot, ClientCriteria, AIAnalysis, AnalyzedLot
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """Jesteś ekspertem od importu aut z USA do Polski.
Analizujesz dane z aukcji Copart i IAAI dla klienta-brokera importowego.

KOSZTY STAŁE DO UWZGLĘDNIENIA:
- Transport USA → Polska: ok. 1400–1800 USD (zależnie od stanu)
- Cło + akcyza: ok. 800 USD ekwiwalent (szacunek uproszczony)
- Homologacja + rejestracja: ok. 500 USD

ZASADY OCENY USZKODZEŃ:
- FLOOD / WATER DAMAGE → automatycznie ODRZUĆ (ukryta korozja, elektronika)
- FIRE → automatycznie ODRZUĆ
- DEPLOYED AIRBAGS → duże ryzyko, nalicz 1500–3000 USD do naprawy
- FRAME/STRUCTURAL DAMAGE → duże ryzyko, może nie przejść homologacji PL
- REBUILT TITLE → ryzyko, trudniej sprzedać w Polsce
- FRONT END / REAR END → standardowe szkody, szacuj 1000–4000 USD

ZASADY UŻYCIA CENY REZERWOWEJ (seller_reserve_usd):
- Jeśli aktualna oferta < rezerwa: auto prawdopodobnie nie zostanie sprzedane lub cena wzrośnie znacznie
- Jeśli oferta >= rezerwa: sprzedaż prawie pewna po tej cenie
- Uwzględnij to w szacunkach total cost

ZASADY UŻYCIA TYPU SPRZEDAWCY (seller_type):
- "insurance": ubezpieczyciel chce szybko pozbyć auta, ceny bardziej negocjowalne
- "dealer": reseller, cena zazwyczaj bliższa rynkowej, mniejszy margines

Zwróć WYŁĄCZNIE poprawny JSON array. Bez żadnego tekstu przed ani po.
"""


def parse_price_from_str(text: str | None) -> float | None:
    if not text:
        return None
    import re
    cleaned = re.sub(r"[^\d.]", "", str(text).replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def analyze_lots(lots: list[CarLot], criteria: ClientCriteria) -> list[AnalyzedLot]:
    if not lots:
        return []

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    lots_data = []
    for lot in lots:
        lots_data.append({
            "lot_id": lot.lot_id,
            "source": lot.source,
            "year": lot.year,
            "make": lot.make,
            "model": lot.model,
            "odometer_mi": lot.odometer_mi,
            "odometer_km": lot.odometer_km,
            "damage_primary": lot.damage_primary,
            "damage_secondary": lot.damage_secondary,
            "title_type": lot.title_type,
            "current_bid_usd": lot.current_bid_usd,
            "seller_reserve_usd": lot.seller_reserve_usd,
            "seller_type": lot.seller_type,
            "location_state": lot.location_state,
            "airbags_deployed": lot.airbags_deployed,
            "keys": lot.keys,
            "enriched_by_extension": lot.enriched_by_extension,
        })

    user_prompt = f"""
Kryteria klienta:
- Marka/model: {criteria.make} {criteria.model or '(dowolny)'}
- Rocznik: {criteria.year_from or 'dowolny'}–{criteria.year_to or 'dowolny'}
- Budżet maksymalny: {criteria.budget_usd} USD (łącznie z transportem i naprawą)
- Maksymalny przebieg: {criteria.max_odometer_mi or 'bez limitu'} mil
- Wykluczone typy uszkodzeń: {', '.join(criteria.excluded_damage_types)}

Oceń poniższe {len(lots_data)} lotów:

{json.dumps(lots_data, ensure_ascii=False, indent=2)}

Dla każdego lota zwróć obiekt JSON z polami:
- lot_id (string, dokładnie jak w danych wejściowych)
- score (liczba 0.0–10.0, im wyższa tym lepszy lot dla klienta)
- recommendation (string: dokładnie "POLECAM", "RYZYKO" lub "ODRZUĆ")
- red_flags (array of strings — lista problemów, może być pusta [])
- estimated_repair_usd (int lub null — szacowany koszt naprawy)
- estimated_total_cost_usd (int — suma: current_bid + estimated_repair + 1600 transport + 500 inne)
- client_description_pl (string — 2–3 zdania po polsku dla klienta, rzeczowo i konkretnie)
- ai_notes (string lub null — uwagi techniczne dla brokera po polsku)
"""

    print(f"[AI] Analizuję {len(lots)} lotów przez Claude API...")

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw = message.content[0].text.strip()

    # Bezpieczne parsowanie — usuń markdown code fences jeśli są
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()

    analyses_data = json.loads(raw)

    # Połącz loty z analizami
    lots_by_id = {lot.lot_id: lot for lot in lots}
    results = []

    for ad in analyses_data:
        lot_id = ad.get("lot_id")
        if not lot_id or lot_id not in lots_by_id:
            continue

        analysis = AIAnalysis(
            lot_id=lot_id,
            score=float(ad.get("score", 0)),
            recommendation=ad.get("recommendation", "RYZYKO"),
            red_flags=ad.get("red_flags", []),
            estimated_repair_usd=ad.get("estimated_repair_usd"),
            estimated_total_cost_usd=ad.get("estimated_total_cost_usd"),
            client_description_pl=ad.get("client_description_pl", ""),
            ai_notes=ad.get("ai_notes"),
        )
        results.append(AnalyzedLot(lot=lots_by_id[lot_id], analysis=analysis))

    # Sortuj: POLECAM > RYZYKO > ODRZUĆ, potem wg score malejąco
    order = {"POLECAM": 0, "RYZYKO": 1, "ODRZUĆ": 2}
    results.sort(key=lambda x: (order.get(x.analysis.recommendation, 99), -x.analysis.score))

    polecam = sum(1 for r in results if r.analysis.recommendation == "POLECAM")
    ryzyko = sum(1 for r in results if r.analysis.recommendation == "RYZYKO")
    odrzuc = sum(1 for r in results if r.analysis.recommendation == "ODRZUĆ")
    print(f"[AI] Wyniki: POLECAM={polecam} | RYZYKO={ryzyko} | ODRZUĆ={odrzuc}")

    return results
```

---

## Plik: report/templates/report.html.j2

```html
<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: Arial, sans-serif; font-size: 11pt; color: #222; margin: 20mm; }
  h1 { font-size: 18pt; color: #1a3a5c; border-bottom: 2px solid #1a3a5c; padding-bottom: 6px; }
  h2 { font-size: 13pt; color: #1a3a5c; margin-top: 24px; }
  .lot { border: 1px solid #ccc; border-radius: 6px; margin-bottom: 24px;
         padding: 14px 18px; page-break-inside: avoid; }
  .lot-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
  .badge { padding: 4px 12px; border-radius: 4px; font-weight: bold; font-size: 10pt; }
  .POLECAM { background: #d4edda; color: #155724; }
  .RYZYKO  { background: #fff3cd; color: #856404; }
  .ODRZUĆ  { background: #f8d7da; color: #721c24; }
  .score   { font-size: 20pt; font-weight: bold; color: #1a3a5c; }
  .info-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin: 10px 0; }
  .info-item { font-size: 9pt; }
  .info-item strong { display: block; color: #555; font-size: 8pt; text-transform: uppercase; }
  .description { font-style: italic; color: #333; margin: 10px 0; padding: 8px 12px;
                 background: #f7f9fc; border-left: 3px solid #1a3a5c; }
  .flags { margin: 8px 0; }
  .flag { display: inline-block; background: #ffeeba; color: #856404; border-radius: 3px;
          padding: 2px 8px; font-size: 8pt; margin: 2px; }
  .costs { background: #f0f4f8; padding: 8px 12px; border-radius: 4px; font-size: 10pt; }
  .costs span { font-weight: bold; color: #1a3a5c; }
  .lot-image { width: 180px; height: 120px; object-fit: cover; border-radius: 4px; margin-right: 14px; }
  .summary { background: #1a3a5c; color: white; padding: 12px 18px; border-radius: 6px; margin-bottom: 24px; }
  .summary-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
  .summary-item { text-align: center; }
  .summary-item .num { font-size: 24pt; font-weight: bold; }
  .summary-item .lbl { font-size: 9pt; opacity: 0.8; }
  @media print { .lot { border-color: #999; } }
</style>
</head>
<body>

<h1>Raport wyszukiwania aut z USA</h1>
<p>Wygenerowano: {{ generated_at }} | Łączna liczba przeanalizowanych lotów: {{ total_lots }}</p>

<div class="summary">
  <div class="summary-grid">
    <div class="summary-item">
      <div class="num" style="color:#7dffb3">{{ polecam_count }}</div>
      <div class="lbl">POLECAM</div>
    </div>
    <div class="summary-item">
      <div class="num" style="color:#ffe08a">{{ ryzyko_count }}</div>
      <div class="lbl">RYZYKO</div>
    </div>
    <div class="summary-item">
      <div class="num" style="color:#ff8a8a">{{ odrzuc_count }}</div>
      <div class="lbl">ODRZUĆ</div>
    </div>
  </div>
</div>

{% for item in lots %}
<div class="lot">
  <div class="lot-header">
    <div>
      <strong style="font-size:13pt">
        {{ item.lot.year or '?' }} {{ item.lot.make or '' }} {{ item.lot.model or '' }}
      </strong>
      <span style="color:#666; font-size:9pt; margin-left:8px">
        {{ item.lot.source | upper }} | Lot: {{ item.lot.lot_id }}
      </span>
    </div>
    <div style="display:flex; align-items:center; gap:14px">
      <span class="score">{{ "%.1f"|format(item.analysis.score) }}/10</span>
      <span class="badge {{ item.analysis.recommendation }}">{{ item.analysis.recommendation }}</span>
    </div>
  </div>

  {% if item.lot.images %}
  <img src="{{ item.lot.images[0] }}" class="lot-image" alt="Zdjęcie pojazdu">
  {% endif %}

  <div class="info-grid">
    <div class="info-item"><strong>Przebieg</strong>
      {{ item.lot.odometer_mi | default('—') }} mi / {{ item.lot.odometer_km | default('—') }} km
    </div>
    <div class="info-item"><strong>Uszkodzenie główne</strong>
      {{ item.lot.damage_primary | default('—') }}
    </div>
    <div class="info-item"><strong>Tytuł</strong>
      {{ item.lot.title_type | default('—') }}
    </div>
    <div class="info-item"><strong>Aktualna oferta</strong>
      ${{ item.lot.current_bid_usd | default('—') }}
    </div>
    <div class="info-item"><strong>Cena rezerwowa</strong>
      {% if item.lot.seller_reserve_usd %}${{ item.lot.seller_reserve_usd }}{% else %}nieznana{% endif %}
    </div>
    <div class="info-item"><strong>Sprzedawca</strong>
      {{ item.lot.seller_type | default('nieznany') }}
    </div>
    <div class="info-item"><strong>Lokalizacja</strong>
      {{ item.lot.location_city | default('') }}{{ ', ' if item.lot.location_state else '' }}{{ item.lot.location_state | default('') }}
    </div>
    <div class="info-item"><strong>Klucze</strong>
      {{ 'Tak' if item.lot.keys else ('Nie' if item.lot.keys == False else '—') }}
    </div>
    <div class="info-item"><strong>Poduszki</strong>
      {{ 'ODPALONE' if item.lot.airbags_deployed else 'OK' }}
    </div>
  </div>

  {% if item.analysis.red_flags %}
  <div class="flags">
    {% for flag in item.analysis.red_flags %}
    <span class="flag">⚠ {{ flag }}</span>
    {% endfor %}
  </div>
  {% endif %}

  <div class="description">{{ item.analysis.client_description_pl }}</div>

  <div class="costs">
    Szacowany koszt naprawy: <span>${{ item.analysis.estimated_repair_usd | default('—') }}</span>
    &nbsp;|&nbsp;
    Łączny koszt (bid + naprawa + transport): <span>${{ item.analysis.estimated_total_cost_usd | default('—') }}</span>
  </div>

  {% if item.analysis.ai_notes %}
  <p style="font-size:9pt; color:#555; margin-top:8px"><em>Uwagi: {{ item.analysis.ai_notes }}</em></p>
  {% endif %}

  <p style="font-size:8pt; color:#888; margin-top:6px">
    <a href="{{ item.lot.url }}">{{ item.lot.url }}</a>
    {% if item.lot.enriched_by_extension %} | ✓ Wzbogacono przez rozszerzenie{% endif %}
  </p>
</div>
{% endfor %}

</body>
</html>
```

---

## Plik: report/generator.py

```python
import os
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from parser.models import AnalyzedLot
from dotenv import load_dotenv

load_dotenv()

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "./data/reports"))
TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_pdf_report(
    analyzed_lots: list[AnalyzedLot],
    output_filename: str | None = None,
) -> Path:
    """Generuje raport PDF. Zwraca ścieżkę do pliku."""
    try:
        import weasyprint
    except ImportError:
        raise ImportError("Zainstaluj weasyprint: pip install weasyprint")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if not output_filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"raport_{ts}.pdf"

    output_path = REPORTS_DIR / output_filename

    # Statystyki
    polecam = [x for x in analyzed_lots if x.analysis.recommendation == "POLECAM"]
    ryzyko  = [x for x in analyzed_lots if x.analysis.recommendation == "RYZYKO"]
    odrzuc  = [x for x in analyzed_lots if x.analysis.recommendation == "ODRZUĆ"]

    # Renderuj szablon
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("report.html.j2")
    html = template.render(
        lots=analyzed_lots,
        total_lots=len(analyzed_lots),
        polecam_count=len(polecam),
        ryzyko_count=len(ryzyko),
        odrzuc_count=len(odrzuc),
        generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
    )

    # Generuj PDF
    weasyprint.HTML(string=html).write_pdf(str(output_path))
    print(f"[Report] Raport zapisany: {output_path}")
    return output_path
```

---

## Plik: api/static/index.html

```html
<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>USA Car Finder</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; background: #f0f2f5; color: #222; }
  header { background: #1a3a5c; color: white; padding: 16px 32px; }
  header h1 { font-size: 20pt; }
  header p  { font-size: 10pt; opacity: 0.8; margin-top: 4px; }
  .container { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
  .card { background: white; border-radius: 8px; padding: 20px 24px;
          box-shadow: 0 1px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }
  h2 { font-size: 13pt; color: #1a3a5c; margin-bottom: 14px; }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
  label { font-size: 9pt; color: #555; display: block; margin-bottom: 4px; }
  input, select { width: 100%; padding: 8px 10px; border: 1px solid #ccc;
                  border-radius: 4px; font-size: 11pt; }
  .btn { background: #1a3a5c; color: white; border: none; padding: 10px 24px;
         border-radius: 4px; font-size: 11pt; cursor: pointer; margin-top: 14px; }
  .btn:hover { background: #245080; }
  .btn-secondary { background: #6c757d; margin-left: 8px; }
  #status { margin-top: 12px; font-size: 10pt; color: #555; font-style: italic; }
  .lot-card { border: 1px solid #ddd; border-radius: 6px; padding: 14px 16px; margin-bottom: 14px; }
  .lot-header { display: flex; justify-content: space-between; align-items: center; }
  .badge { padding: 3px 10px; border-radius: 3px; font-weight: bold; font-size: 9pt; }
  .POLECAM { background: #d4edda; color: #155724; }
  .RYZYKO  { background: #fff3cd; color: #856404; }
  .ODRZUĆ  { background: #f8d7da; color: #721c24; }
  .score-big { font-size: 20pt; font-weight: bold; color: #1a3a5c; }
  .lot-meta { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 10px 0; }
  .meta-item { font-size: 9pt; }
  .meta-item strong { display: block; color: #888; font-size: 8pt; }
  .description { font-style: italic; background: #f7f9fc; border-left: 3px solid #1a3a5c;
                 padding: 8px 12px; margin: 8px 0; font-size: 10pt; }
  .flags span { background: #ffeeba; color: #856404; border-radius: 3px;
                padding: 2px 7px; font-size: 8pt; margin: 2px; display: inline-block; }
  .costs { background: #f0f4f8; padding: 8px 12px; border-radius: 4px; font-size: 10pt; margin-top: 8px; }
  .lot-img { width: 160px; height: 110px; object-fit: cover; border-radius: 4px; float: right; margin-left: 14px; }
  #summary { display: none; }
</style>
</head>
<body>
<header>
  <h1>🚗 USA Car Finder</h1>
  <p>Wyszukiwarka aut z aukcji Copart i IAAI z analizą AI</p>
</header>
<div class="container">

  <!-- Formularz kryteriów -->
  <div class="card">
    <h2>Kryteria wyszukiwania</h2>
    <div class="form-grid">
      <div>
        <label>Marka *</label>
        <input id="make" type="text" placeholder="np. BMW" value="BMW">
      </div>
      <div>
        <label>Model</label>
        <input id="model" type="text" placeholder="np. 3 Series">
      </div>
      <div>
        <label>Budżet max (USD) *</label>
        <input id="budget" type="number" placeholder="15000" value="15000">
      </div>
      <div>
        <label>Rocznik od</label>
        <input id="year_from" type="number" placeholder="2018" value="2018">
      </div>
      <div>
        <label>Rocznik do</label>
        <input id="year_to" type="number" placeholder="2023">
      </div>
      <div>
        <label>Max przebieg (mil)</label>
        <input id="max_odometer" type="number" placeholder="80000" value="80000">
      </div>
      <div>
        <label>Max wyników</label>
        <input id="max_results" type="number" value="20">
      </div>
      <div>
        <label>Źródła aukcji</label>
        <select id="sources">
          <option value="both" selected>Copart + IAAI</option>
          <option value="copart">Tylko Copart</option>
          <option value="iaai">Tylko IAAI</option>
        </select>
      </div>
    </div>
    <button class="btn" onclick="runSearch()">🔍 Szukaj i analizuj</button>
    <button class="btn btn-secondary" id="pdfBtn" style="display:none" onclick="downloadPdf()">📄 Pobierz PDF</button>
    <div id="status"></div>
  </div>

  <!-- Podsumowanie -->
  <div id="summary" class="card">
    <div style="display:flex; gap:24px">
      <div><span id="cnt-polecam" style="font-size:24pt;font-weight:bold;color:#155724">0</span><br><small>POLECAM</small></div>
      <div><span id="cnt-ryzyko"  style="font-size:24pt;font-weight:bold;color:#856404">0</span><br><small>RYZYKO</small></div>
      <div><span id="cnt-odrzuc"  style="font-size:24pt;font-weight:bold;color:#721c24">0</span><br><small>ODRZUĆ</small></div>
      <div><span id="cnt-total"   style="font-size:24pt;font-weight:bold;color:#1a3a5c">0</span><br><small>ŁĄCZNIE</small></div>
    </div>
  </div>

  <!-- Wyniki -->
  <div id="results"></div>
</div>

<script>
let lastResults = [];
let lastCriteria = {};

async function runSearch() {
  const make = document.getElementById('make').value.trim();
  const budget = parseFloat(document.getElementById('budget').value);
  if (!make || !budget) { alert('Podaj markę i budżet'); return; }

  const sourcesVal = document.getElementById('sources').value;
  const sources = sourcesVal === 'copart' ? ['copart'] : sourcesVal === 'iaai' ? ['iaai'] : ['copart','iaai'];

  const criteria = {
    make,
    model: document.getElementById('model').value.trim() || null,
    year_from: parseInt(document.getElementById('year_from').value) || null,
    year_to: parseInt(document.getElementById('year_to').value) || null,
    budget_usd: budget,
    max_odometer_mi: parseInt(document.getElementById('max_odometer').value) || null,
    max_results: parseInt(document.getElementById('max_results').value) || 20,
    sources,
    excluded_damage_types: ['Flood','Fire'],
  };

  lastCriteria = criteria;
  setStatus('⏳ Scrapuję aukcje... (może potrwać kilka minut)');
  document.getElementById('results').innerHTML = '';
  document.getElementById('summary').style.display = 'none';
  document.getElementById('pdfBtn').style.display = 'none';

  try {
    const resp = await fetch('/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({criteria})
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || resp.statusText);
    }
    const data = await resp.json();
    lastResults = data;
    renderResults(data);
    setStatus(`✅ Gotowe — przeanalizowano ${data.length} lotów`);
    document.getElementById('pdfBtn').style.display = 'inline-block';
  } catch(e) {
    setStatus(`❌ Błąd: ${e.message}`);
  }
}

function renderResults(data) {
  const polecam = data.filter(x => x.analysis.recommendation === 'POLECAM').length;
  const ryzyko  = data.filter(x => x.analysis.recommendation === 'RYZYKO').length;
  const odrzuc  = data.filter(x => x.analysis.recommendation === 'ODRZUĆ').length;
  document.getElementById('cnt-polecam').textContent = polecam;
  document.getElementById('cnt-ryzyko').textContent  = ryzyko;
  document.getElementById('cnt-odrzuc').textContent  = odrzuc;
  document.getElementById('cnt-total').textContent   = data.length;
  document.getElementById('summary').style.display = 'block';

  const container = document.getElementById('results');
  container.innerHTML = data.map(item => {
    const lot = item.lot;
    const ai  = item.analysis;
    const flags = ai.red_flags.map(f => `<span>⚠ ${f}</span>`).join('');
    const img = lot.images && lot.images[0]
      ? `<img src="${lot.images[0]}" class="lot-img" onerror="this.style.display='none'">`
      : '';
    const reserve = lot.seller_reserve_usd ? `$${lot.seller_reserve_usd}` : '—';
    const sellerType = lot.seller_type || '—';
    const enrichedBadge = lot.enriched_by_extension ? '✓ Ext' : '';
    return `
    <div class="lot-card">
      ${img}
      <div class="lot-header">
        <div>
          <strong style="font-size:13pt">${lot.year || '?'} ${lot.make || ''} ${lot.model || ''}</strong>
          <span style="color:#888;font-size:9pt;margin-left:8px">${lot.source.toUpperCase()} | ${lot.lot_id} ${enrichedBadge}</span>
        </div>
        <div style="display:flex;align-items:center;gap:12px">
          <span class="score-big">${ai.score.toFixed(1)}/10</span>
          <span class="badge ${ai.recommendation}">${ai.recommendation}</span>
        </div>
      </div>
      <div class="lot-meta">
        <div class="meta-item"><strong>Przebieg</strong>${lot.odometer_mi || '—'} mi / ${lot.odometer_km || '—'} km</div>
        <div class="meta-item"><strong>Uszkodzenie</strong>${lot.damage_primary || '—'}</div>
        <div class="meta-item"><strong>Tytuł</strong>${lot.title_type || '—'}</div>
        <div class="meta-item"><strong>Aktualna oferta</strong>$${lot.current_bid_usd || '—'}</div>
        <div class="meta-item"><strong>Cena rezerwowa</strong>${reserve}</div>
        <div class="meta-item"><strong>Sprzedawca</strong>${sellerType}</div>
        <div class="meta-item"><strong>Lokalizacja</strong>${lot.location_city || ''}${lot.location_state ? ', '+lot.location_state : ''}</div>
        <div class="meta-item"><strong>Poduszki</strong>${lot.airbags_deployed ? '⚠ ODPALONE' : 'OK'}</div>
      </div>
      ${flags ? `<div class="flags" style="margin:8px 0">${flags}</div>` : ''}
      <div class="description">${ai.client_description_pl}</div>
      <div class="costs">
        Naprawa: <strong>$${ai.estimated_repair_usd || '—'}</strong>
        &nbsp;|&nbsp;
        Łączny koszt: <strong>$${ai.estimated_total_cost_usd || '—'}</strong>
      </div>
      ${ai.ai_notes ? `<p style="font-size:9pt;color:#555;margin-top:6px"><em>${ai.ai_notes}</em></p>` : ''}
      <p style="font-size:8pt;color:#999;margin-top:6px">
        <a href="${lot.url}" target="_blank">${lot.url}</a>
      </p>
      <div style="clear:both"></div>
    </div>`;
  }).join('');
}

async function downloadPdf() {
  setStatus('⏳ Generuję raport PDF...');
  try {
    const resp = await fetch('/report', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(lastResults)
    });
    if (!resp.ok) throw new Error(await resp.text());
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'raport_aut_usa.pdf'; a.click();
    setStatus('✅ Raport PDF pobrany');
  } catch(e) {
    setStatus(`❌ Błąd PDF: ${e.message}`);
  }
}

function setStatus(msg) {
  document.getElementById('status').textContent = msg;
}
</script>
</body>
</html>
```

---

## Plik: api/main.py

```python
import os
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from parser.models import ClientCriteria, AnalyzedLot, CarLot, AIAnalysis
from scraper.copart import CopartScraper
from scraper.iaai import IAAIScraper
from parser.copart_parser import parse_all_copart
from parser.iaai_parser import parse_all_iaai
from ai.analyzer import analyze_lots
from report.generator import generate_pdf_report

app = FastAPI(title="USA Car Finder", version="1.0.0")

HTML_CACHE_DIR = Path(os.getenv("HTML_CACHE_DIR", "./data/html_cache"))
USE_EXTENSIONS = os.getenv("USE_EXTENSIONS", "false").lower() == "true"

# Serwuj frontend
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


class SearchRequest(BaseModel):
    criteria: ClientCriteria


@app.post("/search", response_model=list[AnalyzedLot])
async def search_cars(request: SearchRequest):
    criteria = request.criteria
    all_lots = []

    # --- Scraping ---
    if "copart" in criteria.sources:
        scraper = CopartScraper()
        await scraper.scrape(criteria)
        copart_lots = parse_all_copart(HTML_CACHE_DIR / "copart")
        all_lots.extend(copart_lots)

    if "iaai" in criteria.sources:
        scraper = IAAIScraper()
        await scraper.scrape(criteria)
        iaai_lots = parse_all_iaai(HTML_CACHE_DIR / "iaai")
        all_lots.extend(iaai_lots)

    if not all_lots:
        raise HTTPException(status_code=404, detail="Brak wyników — sprawdź kryteria lub logi scrapera")

    # --- Wzbogacanie przez rozszerzenia Chrome (opcjonalne) ---
    if USE_EXTENSIONS:
        from scraper.extension_enricher import ExtensionEnricher
        enricher = ExtensionEnricher()
        lots_to_enrich = [
            (lot.url, Path(lot.html_file))
            for lot in all_lots if lot.html_file
        ]
        enriched_map = await enricher.enrich_all(lots_to_enrich)

        import re
        def parse_price(text):
            if not text: return None
            cleaned = re.sub(r"[^\d.]", "", str(text).replace(",", ""))
            try: return float(cleaned) if cleaned else None
            except: return None

        for lot in all_lots:
            ext = enriched_map.get(lot.url, {})
            if ext:
                lot.seller_reserve_usd = parse_price(
                    ext.get("seller_reserve") or ext.get("ahb_reserve")
                )
                lot.seller_type = ext.get("seller_type") or ext.get("ahb_seller_type")
                lot.full_vin = ext.get("full_vin") or lot.vin
                lot.delivery_cost_estimate_usd = parse_price(ext.get("delivery_cost"))
                lot.enriched_by_extension = True

    # --- Analiza AI ---
    analyzed = analyze_lots(all_lots, criteria)
    return analyzed


@app.post("/report")
async def generate_report(analyzed_lots: list[AnalyzedLot]):
    """Przyjmuje listę przeanalizowanych lotów i zwraca PDF."""
    output_path = generate_pdf_report(analyzed_lots)
    return FileResponse(
        path=str(output_path),
        media_type="application/pdf",
        filename=output_path.name,
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "use_extensions": USE_EXTENSIONS,
        "cache_dir": str(HTML_CACHE_DIR),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
```

---

## Plik: README.md

```markdown
# USA Car Finder

Aplikacja do wyszukiwania i analizy aut z aukcji Copart i IAAI z analizą AI.

## Szybki start

```bash
# 1. Zainstaluj zależności
pip install -r requirements.txt
playwright install chromium

# 2. Konfiguracja
cp .env.example .env
# Edytuj .env i wpisz ANTHROPIC_API_KEY

# 3. Uruchom
python -m api.main

# 4. Otwórz przeglądarkę
# http://localhost:8000
```

## Integracja rozszerzeń Chrome (opcjonalne)

Rozszerzenia AuctionGate i AutoHelperBot dostarczają dodatkowe dane:
pełny VIN, cenę rezerwową sprzedawcy, typ sprzedawcy.

```bash
# Pobierz pliki CRX i zmień rozszerzenie na .zip
# AuctionGate:   https://chrome-stats.com/d/ehpiejnmbdjkaplmbafaejdhodalfbie/download
# AutoHelperBot: https://chrome-stats.com/d/fojpkmgahmlajoheocnkebaoodepoekj/download

mkdir -p extensions/auctiongate extensions/autohelperbot
# Rozpakuj ZIP do odpowiednich katalogów

# Włącz w .env:
# USE_EXTENSIONS=true

# Przy pierwszym uruchomieniu zaloguj się raz w obu rozszerzeniach
# Sesja zostanie zapisana w ./data/chrome_profile/
```

## Architektura

```
Formularz → Scraper (Playwright) → HTML Cache → Parser → AI (Claude) → PDF Raport
                ↕ opcjonalnie
         Rozszerzenia Chrome
         (AuctionGate + AutoHelperBot)
         → pełny VIN, reserve price, seller type
```
```

---

## Po wygenerowaniu wszystkich plików wykonaj

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# Wpisz ANTHROPIC_API_KEY w pliku .env
python -m api.main
# Otwórz http://localhost:8000
```

---

## Uwagi dla Claude Code

1. Utwórz wszystkie pliki i katalogi zgodnie ze strukturą powyżej
2. Wszystkie `__init__.py` mogą być puste
3. Utwórz katalogi `data/html_cache/copart/`, `data/html_cache/iaai/`, `data/reports/`, `extensions/auctiongate/`, `extensions/autohelperbot/`
4. Selektory CSS w parserach (`copart_parser.py`, `iaai_parser.py`) mogą wymagać dostosowania po sprawdzeniu aktualnej struktury HTML stron aukcji — strony zmieniają się, więc po pierwszym pobraniu HTML należy zainspektować DOM i zaktualizować selektory
5. Selektory w `extension_enricher.py` (klasy CSS rozszerzeń) należy zweryfikować po zainstalowaniu rozszerzeń — każde rozszerzenie wstrzykuje własne elementy DOM o unikalnych klasach
