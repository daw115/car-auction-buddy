# Architektura Playwright w AutoScout US

## Przegląd

Aplikacja używa Playwright jako biblioteki Python do automatyzacji przeglądarki w scraperach. Playwright działa jako embedded browser engine - nie wymaga zewnętrznego serwera, wszystko działa w procesie Python.

## Instalacja i konfiguracja

```bash
# Instalacja biblioteki Python
pip install playwright

# Pobranie binarek przeglądarki Chromium
playwright install chromium
```

## Architektura scraperów

### Async API

Wszystkie scrapers używają asynchronicznego API Playwright:

```python
from playwright.async_api import async_playwright

async with async_playwright() as p:
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context(storage_state='playwright_profiles/copart.json')
    page = await context.new_page()
    await page.goto(url)
```

### Storage State - zapisane sesje logowania

Kluczowy mechanizm: zamiast logowania przy każdym uruchomieniu, scrapers ładują zapisane sesje z plików JSON.

**Lokalizacja:** `playwright_profiles/`
- `copart.json` - ciasteczka/localStorage z zalogowanej sesji Copart
- `iaai.json` - sesja IAAI
- `amerpol.json` - sesja Amerpol (opcjonalna)

**Tworzenie sesji:**

```bash
# Uruchom helper logowania
python -m backend.services.scrapers.login_helper copart

# Otwiera się przeglądarka z GUI
# Zaloguj się ręcznie
# Sesja zostaje zapisana do playwright_profiles/copart.json
```

**Implementacja w kodzie:**

```python
# backend/services/scrapers/base.py
def storage_state_path(source: str) -> Path:
    return Path("playwright_profiles") / f"{source}.json"

# backend/services/scrapers/copart.py
state_file = storage_state_path("copart")
context = await browser.new_context(storage_state=str(state_file))
```

### Headless mode

**Konfiguracja:**
- `headless=True` - przeglądarka działa bez GUI (produkcja)
- `headless=False` - przeglądarka widoczna (debugging)

**Anti-detection:**

```python
browser = await p.chromium.launch(
    headless=True,
    args=["--disable-blink-features=AutomationControlled"]
)
context = await browser.new_context(
    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
    viewport={"width": 1365, "height": 900},
    locale="en-US",
)
```

### Selektory CSS

Scrapers używają selektorów CSS do znajdowania elementów DOM:

```python
# Pojedynczy element
vin_el = await page.query_selector("[data-uname='lotdetailVinvalue']")

# Wiele elementów
lot_links = await page.query_selector_all("a[href*='/lot/']")

# Pobieranie atrybutów
href = await link.get_attribute("href")
src = await img.get_attribute("src")
```

**Strategie pobierania zdjęć (5 strategii per scraper):**

1. **Src attribute:** `img[src*='cs.copart.com']`
2. **Data-src (lazy loading):** `img[data-src*='cs.copart.com']`
3. **Gallery containers:** `.image-gallery img`, `[class*='gallery'] img`
4. **Regex w HTML:** `re.findall(r'https://cs\.copart\.com/.*_ful\.jpg', content)`
5. **Regex any size + konwersja:** znajdź thumbnails, zamień na `_ful.jpg`

### Timeouts i czekanie

```python
# Timeout dla page.goto
await page.goto(url, wait_until="domcontentloaded", timeout=30000)

# Czekanie na selektor (dynamiczny content)
await page.wait_for_selector("a[href*='/lot/']", timeout=15000)

# Statyczny delay (dla JavaScript)
await page.wait_for_timeout(3000)
```

## Workflow pipeline

### 1. Trigger wyszukiwania

FastAPI endpoint `/inquiry/{id}/search` wywołuje:

```python
# backend/routes/dashboard.py
background_tasks.add_task(_run_async, run_search_pipeline(inquiry_id))
```

### 2. Równoległe scrapowanie

```python
# backend/tasks.py:run_search_pipeline()
results = await asyncio.gather(
    *[scrape_source(source, mod) for source, mod in _active_scrapers()],
)
```

**Aktywne scrapers:**
- `copart_scraperapi` - używa ScraperAPI proxy (stabilniejsze niż Playwright headless)
- `iaai` - Playwright z storage_state

### 3. Proces scrapowania (per scraper)

```python
async def search(criteria: SearchCriteria) -> list[ScrapedListing]:
    # 1. Ładowanie storage_state (zalogowana sesja)
    state_file = storage_state_path("iaai")
    context = await browser.new_context(storage_state=str(state_file))
    
    # 2. Otwieranie strony wyszukiwania
    await page.goto(search_url)
    await page.wait_for_selector("a[href*='/VehicleDetail/']")
    
    # 3. Zbieranie linków do aukcji
    cards = await page.query_selector_all(".table-row-inner")
    for card in cards:
        link = await card.query_selector("a.heading-7")
        href = await link.get_attribute("href")
        results.append(ScrapedListing(source="iaai", source_url=href))
    
    # 4. Dla każdego auta: detail page + zdjęcia
    for listing in results:
        await page.goto(listing.source_url)
        await _enrich_detail(page, listing)  # 5 strategii pobierania zdjęć
    
    return results
```

### 4. Zapis do bazy

```python
# backend/tasks.py:_persist_scraped()
for item in scraped_items:
    listing = Listing(
        inquiry_id=inquiry_id,
        source=item.source,
        source_url=item.source_url,
        photos_json=json.dumps(item.photos),  # Lista URL-i zdjęć
        ...
    )
    session.add(listing)
```

### 5. Analiza AI

```python
# backend/tasks.py:analyze_one()
photos = json.loads(listing.photos_json)
result = await analyzer.analyze_listing(listing_data, photos)
# Claude Sonnet 4.6 analizuje zdjęcia, zwraca damage_score, repair_estimate
```

## Problemy i rozwiązania

### Problem: Headless detection

**Objaw:** Copart blokuje headless Chrome, zwraca pustą stronę lub captcha.

**Rozwiązanie:** Używamy `copart_scraperapi.py` zamiast Playwright:

```python
# backend/tasks.py
from backend.services.scrapers import copart_scraperapi as copart
```

ScraperAPI to płatne proxy które rotuje IP i user-agenty, omija detection.

### Problem: Dynamiczny content

**Objaw:** Selektory zwracają 0 elementów mimo że są widoczne w przeglądarce.

**Rozwiązanie:** Czekanie na elementy + dodatkowy delay:

```python
await page.wait_for_selector("a[href*='/lot/']", timeout=15000)
await page.wait_for_timeout(3000)  # Extra wait dla JavaScript
```

### Problem: Rate limiting

**Objaw:** Giełdy blokują IP po zbyt wielu requestach.

**Rozwiązanie:** Random delay między requestami:

```python
# backend/services/scrapers/base.py
async def jitter():
    await asyncio.sleep(random.uniform(1.5, 4.0))

# Użycie
await page.goto(url)
await jitter()
```

### Problem: 0 zdjęć mimo że są na stronie

**Objaw:** `listing.photos = []` mimo że strona ma galerię.

**Rozwiązanie:** 5 strategii pobierania (fallback chain):

```python
# Strategia 1: src attribute
imgs = await page.query_selector_all("img[src*='cs.copart.com']")

# Strategia 2: data-src (lazy loading)
imgs = await page.query_selector_all("img[data-src*='cs.copart.com']")

# Strategia 3: gallery containers
imgs = await page.query_selector_all(".image-gallery img")

# Strategia 4: regex w HTML
content = await page.content()
urls = re.findall(r'https://cs\.copart\.com/.*_ful\.jpg', content)

# Strategia 5: regex any size + konwersja do _ful
urls = re.findall(r'https://cs\.copart\.com/.*\.(jpg|png)', content)
full_urls = [url.replace("_thb.jpg", "_ful.jpg") for url in urls]
```

## Timeouts i limity

### Scraper timeouts (backend/tasks.py)

```python
SCRAPER_TIMEOUT_S = 180  # 3 minuty per scraper (Railway jest wolniejsze)

scraped = await asyncio.wait_for(
    mod.search(criteria), 
    timeout=SCRAPER_TIMEOUT_S
)
```

### Page timeouts

```python
# page.goto
await page.goto(url, timeout=30000)  # 30s

# wait_for_selector
await page.wait_for_selector(sel, timeout=15000)  # 15s
```

### Rate limiting (backend/services/rate_limit.py)

```python
# Max 30 zapytań/dzień per źródło
# Zapisywane w bazie: ScraperRun(source, inquiry_id, timestamp)
```

## Debugging scraperów

### Debug scripts

**Copart:**
```bash
python debug_copart_selectors.py
# Otwiera przeglądarkę (headless=False)
# Testuje wszystkie 5 strategii pobierania zdjęć
# Zapisuje screenshot: /tmp/copart_page.png
```

**IAAI:**
```bash
python debug_iaai_selectors.py
# Analogicznie dla IAAI
```

### Logi

```python
# backend/services/scrapers/copart.py
log.info(f"Copart photos for {url}: {len(photos)} total - {photo_counts}")
# photo_counts = {"strategy1_src": 5, "strategy2_data_src": 3, ...}
```

### Headless=False dla debugowania

```python
# Zmień w scraperze
browser = await p.chromium.launch(headless=False)
# Przeglądarka się otworzy, możesz obserwować co się dzieje
```

## Struktura plików

```
backend/services/scrapers/
├── base.py              # SearchCriteria, ScrapedListing, jitter(), storage_state_path()
├── copart.py            # Playwright scraper (obecnie nieużywany - headless detection)
├── copart_scraperapi.py # ScraperAPI proxy (używany w produkcji)
├── iaai.py              # Playwright scraper (używany)
├── amerpol.py           # Playwright scraper (używany)
└── login_helper.py      # Narzędzie do tworzenia storage_state

playwright_profiles/
├── copart.json          # Zapisana sesja Copart
├── iaai.json            # Zapisana sesja IAAI
└── amerpol.json         # Zapisana sesja Amerpol (opcjonalna)

debug_copart_selectors.py  # Debug script dla Copart
debug_iaai_selectors.py    # Debug script dla IAAI
```

## Koszty i limity

### Playwright (darmowe)
- Binarki Chromium: ~300MB
- RAM: ~200-500MB per browser instance
- CPU: zależy od złożoności strony

### ScraperAPI (płatne)
- $49/miesiąc za 100k requestów
- Używane tylko dla Copart (headless detection)
- IAAI/Amerpol używają darmowego Playwright

### Rate limiting giełd
- Copart: ~30 zapytań/dzień per IP (szacunek)
- IAAI: ~50 zapytań/dzień per IP (szacunek)
- Amerpol: brak limitu (polska strona, mniejszy ruch)

## Best practices

1. **Zawsze używaj storage_state** - nie loguj się przy każdym uruchomieniu
2. **Dodawaj jitter()** - random delay chroni przed banem
3. **5 strategii pobierania** - fallback chain zwiększa success rate
4. **Loguj photo_counts** - łatwo zidentyfikować która strategia działa
5. **Timeout 180s** - Railway jest wolniejsze niż localhost
6. **Headless=False dla debug** - zobacz co się dzieje w przeglądarce
7. **Screenshot przy błędach** - `await page.screenshot(path='/tmp/error.png')`
8. **Sprawdzaj storage_state** - jeśli scraper zwraca 0 wyników, może sesja wygasła

## Troubleshooting

### Scraper zwraca 0 wyników

1. Sprawdź czy storage_state istnieje: `ls playwright_profiles/`
2. Sprawdź czy sesja jest aktualna: uruchom `login_helper.py`
3. Sprawdź logi: czy timeout? czy captcha?
4. Uruchom debug script z `headless=False`

### Scraper zwraca 0 zdjęć

1. Sprawdź logi: `photo_counts` - która strategia znalazła 0?
2. Uruchom debug script - zobacz screenshot
3. Sprawdź czy selektory są aktualne (giełdy zmieniają layout)
4. Dodaj nową strategię jeśli potrzeba

### Timeout po 180s

1. Sprawdź czy strona się ładuje (może być down)
2. Sprawdź czy nie ma captcha (headless detection)
3. Zwiększ timeout jeśli Railway jest wolne
4. Rozważ ScraperAPI proxy

### Headless detection (captcha/pusta strona)

1. Użyj ScraperAPI proxy (jak Copart)
2. Dodaj więcej anti-detection tricks:
   - `args=["--disable-blink-features=AutomationControlled"]`
   - Realistyczny user-agent
   - Viewport jak prawdziwa przeglądarka
3. Rozważ `headless=False` (wymaga X server na Railway)
