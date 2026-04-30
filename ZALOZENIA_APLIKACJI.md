# ZAŁOŻENIA APLIKACJI AUTOSCOUT US

## SPIS TREŚCI

1. [Executive Summary](#executive-summary)
2. [Architektura Techniczna](#architektura-techniczna)
3. [Frontend - Vanilla JavaScript](#frontend---vanilla-javascript)
4. [Backend - FastAPI](#backend---fastapi)
5. [Scrapers - Playwright](#scrapers---playwright)
6. [Rozszerzenia Chrome](#rozszerzenia-chrome)
7. [Analiza AI - Claude Sonnet](#analiza-ai---claude-sonnet)
8. [Kalkulator Opłacalności](#kalkulator-opłacalności)
9. [Generowanie Raportów PDF](#generowanie-raportów-pdf)
10. [Integracje Zewnętrzne](#integracje-zewnętrzne)
11. [Workflow Użytkownika](#workflow-użytkownika)
12. [Modele Danych](#modele-danych)
13. [Konfiguracja i Zmienne Środowiskowe](#konfiguracja-i-zmienne-środowiskowe)
14. [Strategie Anti-Bot](#strategie-anti-bot)
15. [Instrukcje Uruchomienia](#instrukcje-uruchomienia)
16. [Ograniczenia i Zastrzeżenia](#ograniczenia-i-zastrzeżenia)

---

## EXECUTIVE SUMMARY

### Cel Biznesowy

AutoScout US to aplikacja webowa dla polskich importerów samochodów, umożliwiająca:
- Automatyczne wyszukiwanie aut na aukcjach amerykańskich (Copart, IAAI)
- Analizę opłacalności zakupu przez AI (Claude Sonnet 4.6)
- Kalkulację kosztów importu do Polski (transport, cła, VAT, akcyza)
- Generowanie profesjonalnych raportów PDF dla klientów

### Główne Funkcje

1. **Wyszukiwanie i Scraping**
   - Równoległe scrapowanie Copart + IAAI przez Playwright
   - Filtrowanie po marce, modelu, roczniku, przebiegu, budżecie
   - Cache HTML (24h) dla optymalizacji

2. **Analiza AI**
   - Claude Sonnet 4.6 Thinking ocenia każdy lot
   - Scoring 0-10 z bonusem za lokalizację (wschód +1.5, zachód -1.0)
   - Rekomendacje: POLECAM / RYZYKO / ODRZUĆ
   - Szacowanie kosztów naprawy i całkowitych kosztów

3. **Kalkulator Opłacalności**
   - 1000+ lokalizacji z predefiniowanymi stawkami towing
   - Automatyczne przeliczenie dla osoby prywatnej i firmy
   - Formuły: prowizja 8%, cło 10%, VAT DE 21%, VAT PL 23%, akcyza 3.1%/18.6%

4. **Raport PDF**
   - TOP 5 najlepszych lotów + dodatkowe propozycje
   - 1 strona A4 per auto z danymi, kalkulacją, zdjęciami
   - Język polski, ton handlowy

### Grupa Docelowa

- Polscy brokerzy importowi
- Firmy zajmujące się sprowadzaniem aut z USA
- Dealerzy samochodów używanych

---

## ARCHITEKTURA TECHNICZNA

### Stack Technologiczny

**Frontend:**
- Vanilla JavaScript (ES6+) - **NIE React/Vue/Angular**
- HTML5 + CSS3 (Grid/Flexbox)
- Fetch API do komunikacji z backendem
- Single Page Application (SPA)

**Backend:**
- FastAPI 0.111.0 (Python 3.9+)
- Uvicorn 0.29.0 (ASGI server)
- Pydantic 2.7.1 (walidacja danych)

**Scraping:**
- Playwright 1.44.0 (async API)
- BeautifulSoup4 + lxml (parsing HTML)
- Chromium (embedded browser)

**AI:**
- Anthropic Claude API
- Model: claude-sonnet-4-6-thinking
- Max tokens: 8192

**PDF Generation:**
- WeasyPrint 62.3
- Jinja2 (templating)

**Integracje:**
- Gmail API (IMAP + App Password)
- Telegram Bot API
- NBP API (kurs USD/PLN - planowane)

### Struktura Katalogów

```
carsmillionaire/
├── usa-car-finder/                    # Główna aplikacja
│   ├── api/
│   │   ├── main.py                    # FastAPI endpoints
│   │   └── static/
│   │       ├── index.html             # Frontend SPA
│   │       ├── calculator.js          # Logika kalkulatora
│   │       └── calculator-data.js     # 1000+ lokalizacji towing
│   ├── scraper/
│   │   ├── automated_scraper.py       # Orchestrator scraperów
│   │   ├── copart.py                  # Copart scraper (Playwright)
│   │   ├── iaai.py                    # IAAI scraper (Playwright)
│   │   ├── extension_enricher.py      # Integracja rozszerzeń Chrome
│   │   └── mock_data.py               # Dane testowe
│   ├── parser/
│   │   ├── models.py                  # Modele Pydantic
│   │   ├── copart_parser.py           # Parser HTML Copart
│   │   └── iaai_parser.py             # Parser HTML IAAI
│   ├── ai/
│   │   └── analyzer.py                # Claude API integration
│   ├── report/
│   │   └── generator.py               # PDF generation
│   └── email_integration/
│       ├── gmail_client.py            # IMAP client
│       └── email_parser.py            # Parsing HTML emails
├── playwright_profiles/
│   ├── copart.json                    # Sesja Copart (storage state)
│   └── iaai.json                      # Sesja IAAI (storage state)
├── chrome_extensions/
│   ├── auctiongate/                   # AuctionGate CRX
│   └── autohelperbot/                 # AutoHelperBot CRX
├── data/
│   ├── html_cache/                    # Cache stron (24h TTL)
│   │   ├── copart/
│   │   └── iaai/
│   ├── chrome_profile/                # Profil Chrome (cookies, localStorage)
│   └── reports/                       # Wygenerowane PDF
├── PLAYWRIGHT_ARCHITECTURE.md         # Dokumentacja scraperów
├── GEMINI_PROMPT.md                   # Prompt AI (nieużywany)
├── KALKULATOR_ZALOZENIA.md            # Formuły kalkulatora
└── .env                               # Zmienne środowiskowe
```

### Przepływ Danych

```
[1] USER REQUEST
    ↓
    POST /search {criteria}
    
[2] AUTOMATED SCRAPER
    ↓
    ├── CopartScraper.scrape() → list[(html_path, url)]
    └── IAAIScraper.scrape() → list[(html_path, url)]
    
[3] PARSING
    ↓
    ├── parse_copart_html() → CarLot
    └── parse_iaai_html() → CarLot
    
[4] FILTERING
    ↓
    ├── Filter: make/model/year/odometer
    ├── Filter: auction_date (12h-168h window)
    └── Sort by auction date → limit to max_results
    
[5] ENRICHMENT (opcjonalne, USE_EXTENSIONS=true)
    ↓
    ExtensionEnricher.enrich_all()
    ├── Otwórz każdy lot z rozszerzeniami Chrome
    ├── Czekaj na iframe z AutoHelperBot/AuctionGate
    └── Wyciągnij: full_vin, seller_type, seller_reserve_usd
    
[6] AI ANALYSIS
    ↓
    analyze_lots(lots, criteria) → (top_recommendations, all_results)
    ├── Model: claude-sonnet-4-6-thinking
    ├── System prompt: ekspert od importu aut z USA do Polski
    ├── Analiza: lokalizacja, uszkodzenia, koszty transportu
    └── Output: score (0-10), recommendation, repair_cost
    
[7] RESPONSE
    ↓
    SearchResponse {
        top_recommendations: AnalyzedLot[] (TOP 5)
        all_results: AnalyzedLot[] (wszystkie)
    }
    
[8] FRONTEND RENDERING
    ↓
    ├── TOP 5 z zielonymi kartami
    ├── Pozostałe 5 jako "Inne propozycje"
    └── Każda karta: score, metadane, red flags, kalkulator preview
    
[9] USER ACTIONS
    ↓
    ├── Zmiana rekomendacji (POLECAM/RYZYKO/ODRZUĆ)
    ├── Usunięcie/dodanie do raportu
    └── Przeliczenie w kalkulatorze (auto-fill)
    
[10] REPORT GENERATION
    ↓
    POST /report {approved_lots}
    → generate_pdf_report() → PDF download
```

### Baza Danych

**BRAK tradycyjnej bazy danych (PostgreSQL/MySQL).**

System używa:
- **Cache HTML na dysku**: `./data/html_cache/copart/`, `./data/html_cache/iaai/`
- **Storage state Playwright**: `./playwright_profiles/*.json` (sesje logowania)
- **Raporty PDF**: `./data/reports/`
- **Profil Chrome**: `./data/chrome_profile/` (cookies, localStorage)

**Uzasadnienie:**
- Aplikacja działa w trybie "stateless" - każde wyszukiwanie jest niezależne
- Cache HTML wystarczy do optymalizacji (24h TTL)
- Brak potrzeby przechowywania historii wyszukiwań
- Prostsze deployment (brak migracji, backupów bazy)

---

## FRONTEND - VANILLA JAVASCRIPT

### Architektura

**Single Page Application** bez frameworka (React/Vue/Angular).

**Lokalizacja:** `/usa-car-finder/api/static/`

**Pliki:**
- `index.html` - główny interfejs
- `calculator.js` - logika kalkulatora
- `calculator-data.js` - dane lokalizacji i stawek towing (1000+ wpisów)

### Główne Ekrany

#### 1. Formularz Wyszukiwania

**Pola:**
- Marka (text input, required)
- Model (text input, optional)
- Budżet maksymalny (number, USD, required)
- Rocznik od-do (number, optional)
- Maksymalny przebieg (number, mile, optional)
- Źródła aukcji (checkboxes: Copart, IAAI, oba)
- Maksymalna liczba wyników (number, default: 30)

**Przycisk:** "Szukaj i analizuj"

**Walidacja:**
- Marka i budżet są wymagane
- Rocznik "od" <= "do"
- Przebieg > 0

#### 2. Wyniki Wyszukiwania

**Sekcja TOP 5:**
- Zielone obramowanie kart
- Badge "POLECAM" / "RYZYKO" / "ODRZUĆ"
- Automatycznie wybrane przez AI

**Sekcja "Inne propozycje":**
- Standardowe obramowanie
- Dodatkowe 5 lotów poza TOP 5

**Karta aukcji (szczegóły poniżej)**

#### 3. Kalkulator Opłacalności

**Sekcja po prawej stronie lub na dole.**

**Pola wejściowe:**
- Kwota licytacji (USD)
- Stan (dropdown: FL, CA, NY, TX, ...)
- Lokalizacja (dropdown: yard + miasto + stawka towing)
- Towing (USD, auto-fill z lokalizacji)
- Koszty dodatkowe (USD, default: 300)
- Załadunki (USD, default: 560)
- Fracht (USD, default: 1050)
- Kurs USD/PLN (default: 4.0)
- Akcyza (%, default: 3.1% dla prywatnej, 18.6% dla firmy)
- Dokładka do prowizji (PLN, optional)

**Wyniki (3 KPI):**
- Suma USA (USD)
- Osoba prywatna z akcyzą (PLN)
- Firma brutto z akcyzą (PLN)

**Szczegółowe rozliczenie:**
- Koszty USA (bid, prowizja 8%, towing, dodatkowe, załadunki, fracht)
- Osoba prywatna (baza odprawy DE, cło 10%, VAT DE 21%, transport, akcyza)
- Firma (cło 10%, VAT PL 23%, transport, akcyza)
- Prowizje (2 warianty: basic 1800+2%, premium 3600+4%)
- Wynagrodzenie pracownika (2 warianty)

### Prezentacja Karty Aukcji

**Nagłówek:**
- Rok, marka, model (np. "2020 Toyota Camry LE")
- Źródło (badge: COPART / IAAI)
- Lot ID (link do aukcji)

**Score i Rekomendacja:**
- Score: 8.5/10 (duża liczba, kolor zależny od wartości)
- Badge: POLECAM (zielony) / RYZYKO (żółty) / ODRZUĆ (czerwony)
- Dropdown do zmiany rekomendacji (edytowalne przez użytkownika)

**Metadane (2 kolumny):**
- Przebieg: 45,000 mi (72,420 km)
- Uszkodzenie: Front End
- Tytuł: Salvage
- Aktualna oferta: $5,500
- Cena rezerwowa: $6,200 (jeśli dostępna z rozszerzenia)
- Sprzedawca: Insurance (jeśli dostępne z rozszerzenia)
- Lokalizacja: NJ, Newark
- Poduszki: Deployed (jeśli tak)
- Kluczyki: Yes/No

**Red Flags (żółte tagi):**
- "Deployed airbags"
- "Salvage title"
- "High mileage"
- "Frame damage" (czerwony tag)
- "Flood damage" (czerwony tag)

**Opis kliencki (po polsku):**
```
Toyota Camry 2018, 45k mil, lokalizacja NJ (wschód - tani transport 1400 USD). 
Uszkodzenia: Front End, szacunek naprawy 2500 USD. Aktualna oferta 5500 USD 
poniżej rezerwy 6200 USD - prawdopodobnie cena wzrośnie. Całkowity koszt 
z transportem i naprawą: 9900 USD. Sprzedawca: ubezpieczyciel (insurance) 
- cena negocjowalna.
```

**Koszty:**
- Szacowana naprawa: $2,500 (z AI)
- Łączny koszt: $9,900 (bid + repair + transport + fees)

**Kalkulator Preview:**
- Osoba prywatna: 42,000 PLN
- Firma brutto: 48,500 PLN
- Towing: $400 (auto z lokalizacji NJ)

**Kontrolki:**
- Przycisk "Przelicz w kalkulatorze" (auto-fill danych)
- Przycisk "Usuń z raportu" / "Dodaj do raportu"
- Link "Zobacz aukcję" (otwiera w nowej karcie)

**Zdjęcia (galeria):**
- Miniaturki 4-6 zdjęć
- Kliknięcie otwiera lightbox z pełnym rozmiarem

### Zarządzanie Stanem

**Globalna zmienna:**
```javascript
window.searchData = {
  top_recommendations: AnalyzedLot[],
  all_results: AnalyzedLot[]
}
```

**Inline state:**
- Każdy lot ma flagę `included_in_report: boolean`
- Zmiana rekomendacji aktualizuje `analysis.recommendation`
- Brak Redux/MobX/Zustand - prosty imperatywny model

**DOM manipulation:**
- Bezpośrednia aktualizacja klas CSS (`classList.add/remove`)
- `innerHTML` do renderowania kart
- Event listeners na przyciskach

### Komunikacja z Backendem

**Fetch API:**
```javascript
// POST /search
const response = await fetch('/search', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({criteria: {
    make: 'Toyota',
    model: 'Camry',
    year_from: 2018,
    year_to: 2020,
    budget_usd: 15000,
    max_odometer_mi: 80000,
    excluded_damage_types: ['Flood', 'Fire'],
    max_results: 30,
    sources: ['copart', 'iaai']
  }})
});

const data = await response.json();
// data = SearchResponse {top_recommendations, all_results}
```

**POST /report:**
```javascript
const response = await fetch('/report', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    approved_lots: allLots.filter(lot => lot.included_in_report)
  })
});

const blob = await response.blob();
const url = window.URL.createObjectURL(blob);
const a = document.createElement('a');
a.href = url;
a.download = 'raport.pdf';
a.click();
```

### Kluczowe Funkcje JavaScript

**runSearch()** - główne wyszukiwanie:
```javascript
async function runSearch() {
  const criteria = {
    make: document.getElementById('make').value,
    model: document.getElementById('model').value || null,
    // ... pozostałe pola
  };
  
  const response = await fetch('/search', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({criteria})
  });
  
  window.searchData = await response.json();
  renderApprovalScreen();
}
```

**renderApprovalScreen()** - renderowanie wyników:
```javascript
function renderApprovalScreen() {
  const {top_recommendations, all_results} = window.searchData;
  
  const topHtml = top_recommendations.map(lot => renderLotCard(lot, true)).join('');
  const othersHtml = all_results.filter(lot => !lot.is_top_recommendation)
    .slice(0, 5)
    .map(lot => renderLotCard(lot, false))
    .join('');
  
  document.getElementById('topRecommendations').innerHTML = topHtml;
  document.getElementById('otherResults').innerHTML = othersHtml;
}
```

**renderLotCard()** - generowanie HTML karty:
```javascript
function renderLotCard(analyzedLot, isTop) {
  const {lot, analysis} = analyzedLot;
  const borderClass = isTop ? 'border-green' : '';
  const badgeClass = {
    'POLECAM': 'badge-green',
    'RYZYKO': 'badge-yellow',
    'ODRZUĆ': 'badge-red'
  }[analysis.recommendation];
  
  return `
    <div class="lot-card ${borderClass}" data-lot-id="${lot.lot_id}">
      <div class="card-header">
        <h3>${lot.year} ${lot.make} ${lot.model}</h3>
        <span class="badge ${badgeClass}">${analysis.recommendation}</span>
        <span class="source-badge">${lot.source.toUpperCase()}</span>
      </div>
      <div class="card-body">
        <div class="score">Score: ${analysis.score.toFixed(1)}/10</div>
        <div class="metadata">
          <div>Przebieg: ${lot.odometer_mi} mi (${lot.odometer_km} km)</div>
          <div>Uszkodzenie: ${lot.damage_primary}</div>
          <div>Tytuł: ${lot.title_type}</div>
          <div>Oferta: $${lot.current_bid_usd}</div>
          <div>Lokalizacja: ${lot.location_state}, ${lot.location_city}</div>
        </div>
        <div class="red-flags">
          ${analysis.red_flags.map(flag => `<span class="tag">${flag}</span>`).join('')}
        </div>
        <div class="description">${analysis.client_description_pl}</div>
        <div class="costs">
          <div>Naprawa: $${analysis.estimated_repair_usd}</div>
          <div>Łącznie: $${analysis.estimated_total_cost_usd}</div>
        </div>
        <div class="calculator-preview">
          ${estimateLotTotalPln(lot, analysis)}
        </div>
        <div class="controls">
          <select onchange="changeRecommendation('${lot.lot_id}', this.value)">
            <option value="POLECAM" ${analysis.recommendation === 'POLECAM' ? 'selected' : ''}>POLECAM</option>
            <option value="RYZYKO" ${analysis.recommendation === 'RYZYKO' ? 'selected' : ''}>RYZYKO</option>
            <option value="ODRZUĆ" ${analysis.recommendation === 'ODRZUĆ' ? 'selected' : ''}>ODRZUĆ</option>
          </select>
          <button onclick="toggleLotInReport('${lot.lot_id}')">
            ${analyzedLot.included_in_report ? 'Usuń z raportu' : 'Dodaj do raportu'}
          </button>
          <button onclick="fillCalculatorFromLot('${lot.lot_id}')">Przelicz w kalkulatorze</button>
          <a href="${lot.url}" target="_blank">Zobacz aukcję</a>
        </div>
      </div>
    </div>
  `;
}
```

**changeRecommendation()** - zmiana badge'a:
```javascript
function changeRecommendation(lotId, newRecommendation) {
  const lot = findLotById(lotId);
  lot.analysis.recommendation = newRecommendation;
  
  // Aktualizuj badge w DOM
  const card = document.querySelector(`[data-lot-id="${lotId}"]`);
  const badge = card.querySelector('.badge');
  badge.className = `badge badge-${newRecommendation === 'POLECAM' ? 'green' : newRecommendation === 'RYZYKO' ? 'yellow' : 'red'}`;
  badge.textContent = newRecommendation;
}
```

**toggleLotInReport()** - dodaj/usuń z raportu:
```javascript
function toggleLotInReport(lotId) {
  const lot = findLotById(lotId);
  lot.included_in_report = !lot.included_in_report;
  
  // Aktualizuj przycisk
  const card = document.querySelector(`[data-lot-id="${lotId}"]`);
  const button = card.querySelector('button[onclick*="toggleLotInReport"]');
  button.textContent = lot.included_in_report ? 'Usuń z raportu' : 'Dodaj do raportu';
}
```

**fillCalculatorFromLot()** - auto-fill kalkulatora:
```javascript
function fillCalculatorFromLot(lotId) {
  const lot = findLotById(lotId);
  
  document.getElementById('calcBid').value = lot.lot.current_bid_usd || 0;
  document.getElementById('calcState').value = lot.lot.location_state || 'FL';
  buildLocationOptions(); // Odśwież dropdown lokalizacji
  setTowingFromLocation(); // Auto-fill towing
  
  // Scroll do kalkulatora
  document.getElementById('calculator').scrollIntoView({behavior: 'smooth'});
  
  // Przelicz
  calculateImportCosts();
}
```

**approveAndGeneratePdf()** - finalna generacja PDF:
```javascript
async function approveAndGeneratePdf() {
  const allLots = [
    ...window.searchData.top_recommendations,
    ...window.searchData.all_results.filter(lot => !lot.is_top_recommendation)
  ];
  
  const response = await fetch('/report', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({approved_lots: allLots})
  });
  
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `raport_${new Date().toISOString().split('T')[0]}.pdf`;
  a.click();
}
```

---

## BACKEND - FASTAPI

### Endpointy API

**Lokalizacja:** `/usa-car-finder/api/main.py`

#### POST /search

**Request:**
```json
{
  "criteria": {
    "make": "Toyota",
    "model": "Camry",
    "year_from": 2018,
    "year_to": 2020,
    "budget_usd": 15000,
    "max_odometer_mi": 80000,
    "excluded_damage_types": ["Flood", "Fire"],
    "max_results": 30,
    "sources": ["copart", "iaai"]
  }
}
```

**Response:**
```json
{
  "top_recommendations": [
    {
      "lot": { /* CarLot */ },
      "analysis": { /* AIAnalysis */ },
      "is_top_recommendation": true,
      "included_in_report": true
    }
  ],
  "all_results": [ /* wszystkie AnalyzedLot */ ]
}
```

**Pipeline:**
1. Walidacja `ClientCriteria` przez Pydantic
2. `AutomatedScraper.search_cars(criteria)` → równoległe scrapowanie Copart + IAAI
3. Parsowanie HTML → lista `CarLot`
4. Filtrowanie: make/model/rok/przebieg → okno aukcji (12h-168h) → max_results
5. Opcjonalne wzbogacanie przez `ExtensionEnricher` (jeśli `USE_EXTENSIONS=true`)
6. `analyze_lots(all_lots, criteria, top_n=5)` → Claude API
7. Zwrócenie `SearchResponse`

**Timeout:** Brak explicite, ale scrapers mają timeout 180s per źródło

#### POST /report

**Request:**
```json
{
  "approved_lots": [
    {
      "lot": { /* CarLot */ },
      "analysis": { /* AIAnalysis */ },
      "is_top_recommendation": true,
      "included_in_report": true
    }
  ]
}
```

**Response:** PDF file (application/pdf)

**Pipeline:**
1. Filtrowanie lotów: tylko `included_in_report=true`
2. `generate_pdf_report(lots_for_report)` → WeasyPrint + Jinja2
3. Zapis do `./data/reports/report_TIMESTAMP.pdf`
4. `FileResponse` z PDF

#### GET /health

**Response:**
```json
{
  "status": "ok",
  "use_extensions": false,
  "use_mock_data": false,
  "cache_dir": "./data/html_cache"
}
```

### Modele Pydantic

**Lokalizacja:** `/usa-car-finder/parser/models.py`

#### ClientCriteria

```python
class ClientCriteria(BaseModel):
    make: str                                    # Wymagane
    model: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    budget_usd: float                            # Wymagane
    max_odometer_mi: Optional[int] = None
    allowed_damage_types: list[str] = []
    excluded_damage_types: list[str] = ["Flood", "Fire"]  # Domyślnie
    max_results: int = 30
    sources: list[str] = ["copart", "iaai"]      # Domyślnie oba
```

#### CarLot

```python
class CarLot(BaseModel):
    # Identyfikacja
    source: str                                  # "copart" | "iaai"
    lot_id: str
    url: str
    html_file: Optional[str] = None              # Ścieżka do cache HTML
    
    # Dane podstawowe
    vin: Optional[str] = None                    # Częściowy VIN (Copart ukrywa ostatnie 6)
    full_vin: Optional[str] = None               # Pełny VIN z rozszerzenia
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    odometer_mi: Optional[int] = None
    odometer_km: Optional[int] = None
    
    # Uszkodzenia i tytuł
    damage_primary: Optional[str] = None         # "Front End", "Rear End", etc.
    damage_secondary: Optional[str] = None
    title_type: Optional[str] = None             # "Clean", "Salvage", "Rebuilt", "Parts Only", "Flood"
    
    # Ceny
    current_bid_usd: Optional[float] = None
    buy_now_price_usd: Optional[float] = None
    seller_reserve_usd: Optional[float] = None   # Z rozszerzenia (cena rezerwowa)
    
    # Sprzedawca (z rozszerzenia)
    seller_type: Optional[str] = None            # "insurance" | "dealer" | "unknown"
    
    # Lokalizacja
    location_state: Optional[str] = None         # "FL", "CA", "NY", etc.
    location_city: Optional[str] = None
    
    # Aukcja
    auction_date: Optional[str] = None           # "YYYY-MM-DD HH:MM:SS" (UTC)
    keys: Optional[bool] = None
    airbags_deployed: Optional[bool] = None
    
    # Media
    images: list[str] = []                       # Lista URL-i zdjęć
    
    # Metadane
    enriched_by_extension: bool = False          # Czy wzbogacone przez rozszerzenia
    delivery_cost_estimate_usd: Optional[float] = None
    raw_data: dict = {}                          # Surowe dane z parsera
```

#### AIAnalysis

```python
class AIAnalysis(BaseModel):
    lot_id: str
    score: float                                 # 0.0-10.0 (walidacja: ge=0, le=10)
    recommendation: str                          # "POLECAM" | "RYZYKO" | "ODRZUĆ"
    red_flags: list[str] = []                    # ["Deployed airbags", "Salvage title", ...]
    estimated_repair_usd: Optional[int] = None   # Szacunek kosztów naprawy
    estimated_total_cost_usd: Optional[int] = None  # Bid + repair + transport + fees
    client_description_pl: str                   # Opis po polsku dla klienta (3-5 zdań)
    ai_notes: Optional[str] = None               # Szczegółowe uwagi techniczne dla brokera
```

#### AnalyzedLot

```python
class AnalyzedLot(BaseModel):
    lot: CarLot
    analysis: AIAnalysis
    is_top_recommendation: bool = False          # Czy lot jest w TOP 5
    included_in_report: bool = True              # Czy lot ma być w raporcie (edytowalne)
```

#### SearchResponse

```python
class SearchResponse(BaseModel):
    top_recommendations: list[AnalyzedLot] = []  # TOP 5 wybranych przez AI
    all_results: list[AnalyzedLot] = []          # Wszystkie wyniki (TOP 5 + pozostałe)
```

### Pipeline Przetwarzania

**Lokalizacja:** `/usa-car-finder/scraper/automated_scraper.py`

```python
class AutomatedScraper:
    async def search_cars(self, criteria: ClientCriteria) -> List[CarLot]:
        all_lots = []
        
        # 1. Scraping Copart
        if "copart" in criteria.sources:
            scraper = CopartScraper()
            saved_files = await scraper.scrape(criteria)
            for path, url in saved_files:
                lot = parse_copart_html(Path(path))
                lot.url = url
                all_lots.append(lot)
        
        # 2. Scraping IAAI
        if "iaai" in criteria.sources:
            scraper = IAAIScraper()
            saved_files = await scraper.scrape(criteria)
            for path, url in saved_files:
                lot = parse_iaai_html(Path(path))
                lot.url = url
                all_lots.append(lot)
        
        # 3. Filtrowanie po make/model/rok/przebieg
        all_lots = self._filter_by_client_criteria(all_lots, criteria)
        
        # 4. Filtrowanie po dacie aukcji (12h-168h window)
        all_lots = self._filter_by_auction_date(
            all_lots,
            min_hours=self.min_auction_window_hours,  # 12h
            max_hours=self.max_auction_window_hours   # 168h (7 dni)
        )
        
        # 5. Sortowanie po dacie aukcji + limit max_results
        all_lots.sort(key=self._auction_sort_key)
        if criteria.max_results:
            all_lots = all_lots[:criteria.max_results]
        
        # 6. Wzbogacanie danymi z rozszerzeń (opcjonalne)
        if self.use_extensions:
            all_lots = await self._enrich_with_extensions(all_lots)
        
        # 7. Opcjonalne filtrowanie po seller_type=insurance
        if self.filter_insurance_only:
            all_lots = [lot for lot in all_lots 
                       if lot.seller_type == "insurance" or lot.seller_type is None]
        
        return all_lots
```

**Filtrowanie po dacie aukcji:**
```python
def _filter_by_auction_date(self, lots: List[CarLot], min_hours: int, max_hours: int):
    now = datetime.now(timezone.utc)
    earliest = now + timedelta(hours=min_hours)
    deadline = now + timedelta(hours=max_hours)
    
    filtered = []
    for lot in lots:
        if not lot.auction_date:
            continue  # Brak daty - odrzuć
        
        # Parsuj datę aukcji
        if len(lot.auction_date) == 10:  # "YYYY-MM-DD"
            auction_dt = datetime.strptime(lot.auction_date, "%Y-%m-%d").replace(
                hour=23, minute=59, tzinfo=timezone.utc
            )
        else:  # "YYYY-MM-DD HH:MM:SS"
            auction_dt = datetime.strptime(lot.auction_date[:19], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        
        # Zachowaj loty w oknie czasowym
        if earliest <= auction_dt <= deadline:
            filtered.append(lot)
    
    return filtered
```

---

## SCRAPERS - PLAYWRIGHT

### Architektura Scraperów

**Playwright** - embedded browser automation w Python (async API).

**Lokalizacja:**
- `/usa-car-finder/scraper/copart.py` - Copart scraper
- `/usa-car-finder/scraper/iaai.py` - IAAI scraper
- `/usa-car-finder/scraper/base.py` - klasy bazowe (nieużywane w aktualnej implementacji)

### Storage State (Sesje Logowania)

**Kluczowy mechanizm:** Zamiast logowania przy każdym uruchomieniu, scrapers ładują zapisane sesje z plików JSON.

**Lokalizacja:** `playwright_profiles/`
- `copart.json` - ciasteczka/localStorage z zalogowanej sesji Copart
- `iaai.json` - sesja IAAI

**Tworzenie sesji:**
```bash
# Uruchom helper logowania (nie zaimplementowany w aktualnym kodzie)
python -m backend.services.scrapers.login_helper copart

# Otwiera się przeglądarka z GUI
# Zaloguj się ręcznie
# Sesja zostaje zapisana do playwright_profiles/copart.json
```

**Implementacja w kodzie:**
```python
from playwright.async_api import async_playwright

async with async_playwright() as p:
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context(
        storage_state='playwright_profiles/copart.json'
    )
    page = await context.new_page()
    await page.goto(url)
```

### 3-Fazowy Proces Scrapowania

#### Faza 1: Wyszukiwanie

```python
# Copart
search_url = f"https://www.copart.com/lotSearchResults?query={make}+{model}"
await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
await page.wait_for_selector("a[href*='/lot/']", timeout=15000)

# Zbieranie linków do lotów
lot_links = await page.eval_on_selector_all(
    "a[href*='/lot/']",
    "els => els.map(e => e.href)"
)
```

#### Faza 2: Pobieranie Szczegółów

```python
for url in lot_links:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    
    # Czekaj na dynamiczny content
    await page.wait_for_timeout(3000)  # JavaScript lazy-load
    
    # Pobierz HTML
    html = await page.content()
    
    # Zapisz do cache
    cache_path = HTML_CACHE_DIR / f"{source}" / f"{lot_id}.html"
    cache_path.write_text(html, encoding="utf-8")
```

#### Faza 3: Parsowanie HTML

```python
# parser/copart_parser.py
from bs4 import BeautifulSoup

def parse_copart_html(path: Path) -> Optional[CarLot]:
    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    
    # Wyciąga JSON z <script> tag
    script = soup.find("script", string=re.compile("cachedSolrLotDetailsStr"))
    json_str = re.search(r'cachedSolrLotDetailsStr\s*=\s*"(.+?)"', script.string).group(1)
    data = json.loads(json_str.replace('\\"', '"'))
    
    # Mapowanie na CarLot
    return CarLot(
        source="copart",
        lot_id=data["ln"],
        vin=data["fv"],  # Częściowy VIN
        year=data["lcy"],
        make=data["mkn"],
        model=data["lm"],
        odometer_mi=data["od"],
        damage_primary=data["dd"],
        title_type=data["ts"],
        current_bid_usd=data["dynamicLotDetails"]["currentBid"],
        location_state=data["yn"],
        auction_date=data["ad"],
        images=[img["link"]["href"] for img in data.get("imagesList", {}).get("images", [])]
    )
```

### Strategie Pobierania Zdjęć

**5 strategii fallback chain:**

1. **Src attribute:** `img[src*='cs.copart.com']`
2. **Data-src (lazy loading):** `img[data-src*='cs.copart.com']`
3. **Gallery containers:** `.image-gallery img`, `[class*='gallery'] img`
4. **Regex w HTML:** `re.findall(r'https://cs\.copart\.com/.*_ful\.jpg', content)`
5. **Regex any size + konwersja:** znajdź thumbnails, zamień na `_ful.jpg`

```python
async def _enrich_detail(page, listing):
    photos = []
    
    # Strategia 1: src attribute
    imgs = await page.query_selector_all("img[src*='cs.copart.com']")
    for img in imgs:
        src = await img.get_attribute("src")
        if src and "_ful.jpg" in src:
            photos.append(src)
    
    # Strategia 2: data-src (lazy loading)
    if not photos:
        imgs = await page.query_selector_all("img[data-src*='cs.copart.com']")
        for img in imgs:
            src = await img.get_attribute("data-src")
            if src:
                photos.append(src)
    
    # Strategia 3: gallery containers
    if not photos:
        imgs = await page.query_selector_all(".image-gallery img")
        for img in imgs:
            src = await img.get_attribute("src")
            if src and "copart.com" in src:
                photos.append(src)
    
    # Strategia 4: regex w HTML
    if not photos:
        content = await page.content()
        photos = re.findall(r'https://cs\.copart\.com/.*_ful\.jpg', content)
    
    # Strategia 5: regex any size + konwersja
    if not photos:
        content = await page.content()
        urls = re.findall(r'https://cs\.copart\.com/.*\.(jpg|png)', content)
        photos = [url.replace("_thb.jpg", "_ful.jpg") for url in urls]
    
    listing.photos = list(set(photos))  # Deduplikacja
```

### Anti-Detection Techniques

**User-Agent Spoofing:**
```python
user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
context = await browser.new_context(user_agent=user_agent)
```

**Automation Detection Bypass:**
```python
browser = await p.chromium.launch(
    headless=True,
    args=["--disable-blink-features=AutomationControlled"]
)
```

**Realistic Browser Fingerprint:**
```python
context = await browser.new_context(
    viewport={"width": 1365, "height": 900},
    locale="en-US",
    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
)
```

**Random Jitter (1.5-4s delay):**
```python
import random

async def jitter():
    await asyncio.sleep(random.uniform(1.5, 4.0))

# Użycie
await page.goto(url)
await jitter()
```

### Cache System

**Lokalizacja:** `./data/html_cache/copart/`, `./data/html_cache/iaai/`

**TTL:** 24 godziny (konfigurowalny przez `CACHE_MAX_AGE_HOURS`)

**Mechanizm:**
```python
cache_path = HTML_CACHE_DIR / source / f"{lot_id}.html"

# Sprawdź czy cache jest świeży
if cache_path.exists() and not FORCE_REFRESH:
    age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
    if age_hours < CACHE_MAX_AGE_HOURS:
        print(f"[Cache] Używam cache dla {lot_id} (wiek: {age_hours:.1f}h)")
        return cache_path

# Cache nieświeży lub FORCE_REFRESH=true - pobierz na nowo
await page.goto(url)
html = await page.content()
cache_path.write_text(html, encoding="utf-8")
```

### Timeouts i Limity

**Scraper timeout:**
```python
SCRAPER_TIMEOUT_S = 180  # 3 minuty per scraper

scraped = await asyncio.wait_for(
    scraper.scrape(criteria),
    timeout=SCRAPER_TIMEOUT_S
)
```

**Page timeouts:**
```python
# page.goto
await page.goto(url, timeout=30000)  # 30s

# wait_for_selector
await page.wait_for_selector(sel, timeout=15000)  # 15s

# wait_for_timeout (statyczny delay)
await page.wait_for_timeout(3000)  # 3s dla JavaScript
```

### Headless Mode

**Konfiguracja:**
- `headless=True` - przeglądarka działa bez GUI (produkcja)
- `headless=False` - przeglądarka widoczna (debugging)

**Problem:** Copart wykrywa headless Chrome i blokuje.

**Rozwiązanie (w dokumentacji, nieużywane w kodzie):** ScraperAPI proxy

```python
# Dokumentacja wspomina copart_scraperapi.py, ale w aktualnym kodzie używany jest Playwright
```

---

## ROZSZERZENIA CHROME (OPCJONALNE WZBOGACANIE)

### Dostępne Rozszerzenia

**Lokalizacja:** `chrome_extensions/`

1. **AuctionGate** (0.15.2_0)
   - Pełny VIN (Copart ukrywa ostatnie 6 znaków)
   - Cena rezerwowa sprzedawcy (`seller_reserve_usd`)
   - Kalkulator kosztów dostawy

2. **AutoHelperBot** (1.3.9_0)
   - Typ sprzedawcy (`seller_type`: "insurance" | "dealer" | "unknown")
   - Dodatkowe metadane

### Mechanizm Wzbogacania

**Lokalizacja:** `/usa-car-finder/scraper/extension_enricher.py`

**Proces:**
1. Otwórz stronę lotu z rozszerzeniami Chrome (headless=False)
2. Czekaj 15s na wstrzyknięcie iframe przez rozszerzenie
3. Znajdź iframe z `autohelperbot.com` lub `auctiongate.io`
4. Wyciągnij dane z iframe przez `evaluate()`
5. Zapisz wzbogacony HTML do cache

**Implementacja:**
```python
class ExtensionEnricher:
    async def enrich_all(self, lots_to_enrich: List[Tuple[str, Path]]) -> Dict[str, dict]:
        """
        Wzbogaca loty danymi z rozszerzeń Chrome.
        
        Args:
            lots_to_enrich: Lista (url, cache_path) dla każdego lotu
            
        Returns:
            Dict[url, enriched_data] - mapa URL → dane z rozszerzeń
        """
        enriched_map = {}
        
        async with async_playwright() as p:
            # Launch persistent context z rozszerzeniami
            context = await p.chromium.launch_persistent_context(
                user_data_dir="./data/chrome_profile",
                headless=False,  # MUSI być False
                args=[
                    f"--disable-extensions-except={extensions}",
                    f"--load-extension={extensions}"
                ]
            )
            
            page = context.pages[0] if context.pages else await context.new_page()
            
            for url, cache_path in lots_to_enrich:
                await page.goto(url, timeout=60000)
                await asyncio.sleep(15)  # Czekaj na iframe
                
                # Znajdź iframe z rozszerzeniem
                for frame in page.frames:
                    if "autohelperbot.com" in frame.url or "auctiongate.io" in frame.url:
                        data = await frame.evaluate("""
                            () => {
                                // Wyciągnij dane z DOM iframe
                                return {
                                    full_vin: document.querySelector('[data-vin]')?.textContent,
                                    seller_reserve_usd: parseFloat(document.querySelector('[data-reserve]')?.textContent),
                                    seller_type: document.querySelector('[data-seller-type]')?.textContent
                                };
                            }
                        """)
                        
                        enriched_map[url] = {
                            **data,
                            "enriched_by_extension": True
                        }
                        break
            
            await context.close()
        
        return enriched_map
```

### Wymagania

**Konfiguracja:**
- `USE_EXTENSIONS=true` w `.env`
- `CHROME_EXECUTABLE_PATH` wskazujący na Google Chrome
- Rozpakowane CRX w `chrome_extensions/auctiongate/`, `chrome_extensions/autohelperbot/`

**Ograniczenia:**
- **Tylko lokalnie** - wymaga GUI (headless=False)
- **Nie działa na Railway** - brak interfejsu graficznego
- **Wolniejsze** - 15s delay per lot dla iframe injection
- **Wymaga autoryzacji** - rozszerzenia wymagają logowania do ich serwisów

### Dane Wzbogacone

**CarLot po wzbogaceniu:**
```python
CarLot(
    source="copart",
    lot_id="99854415",
    vin="1HGBH41JXM",              # Częściowy VIN z Copart
    full_vin="1HGBH41JXMN109186",  # Pełny VIN z rozszerzenia ✓
    current_bid_usd=5500,
    seller_reserve_usd=6200,        # Z rozszerzenia ✓
    seller_type="insurance",        # Z rozszerzenia ✓
    enriched_by_extension=True      # Flaga ✓
)
```

---

## ANALIZA AI - CLAUDE SONNET

### Model i Konfiguracja

**Model:** `claude-sonnet-4-6-thinking`
**Max tokens:** 8192
**API:** Anthropic Claude API
**Klucz:** `ANTHROPIC_API_KEY` w `.env`

**Lokalizacja:** `/usa-car-finder/ai/analyzer.py`

### System Prompt

```python
SYSTEM_PROMPT = """Jesteś ekspertem od importu aut z USA do Polski.
Analizujesz dane z aukcji Copart i IAAI dla klienta-brokera importowego.

PRIORYTET LOKALIZACJI - WSCHODNIE WYBRZEŻE USA:
Stany wschodnie (łatwy i tani transport do Polski):
- NY, NJ, PA, CT, MA, RI, VT, NH, ME, MD, DE, VA, NC, SC, GA, FL
- Transport morski: 1400-1600 USD, czas: 3-4 tygodnie
- PREFERUJ te stany - dodaj +1.5 do score

Stany środkowe (średni transport):
- OH, MI, IN, IL, WI, MN, IA, MO, KY, TN, AL, MS, LA, AR
- Transport: 1600-1800 USD, czas: 4-5 tygodni
- Neutralne dla score

Stany zachodnie (drogi transport):
- CA, OR, WA, NV, AZ, UT, CO, NM, TX (zachodni)
- Transport: 1800-2200 USD, czas: 5-6 tygodni
- ODEJMIJ -1.0 od score (chyba że wyjątkowo dobra oferta)

KOSZTY STAŁE DO UWZGLĘDNIENIA:
- Transport USA → Polska: 1400-2200 USD (zależnie od lokalizacji)
- Cło + akcyza: ok. 800 USD ekwiwalent
- Homologacja + rejestracja: ok. 500 USD

ZASADY OCENY USZKODZEŃ:
- FLOOD / WATER DAMAGE → automatycznie ODRZUĆ (ukryta korozja, elektronika)
- FIRE → automatycznie ODRZUĆ
- DEPLOYED AIRBAGS → duże ryzyko, nalicz 1500-3000 USD do naprawy
- FRAME/STRUCTURAL DAMAGE → duże ryzyko, może nie przejść homologacji PL
- REBUILT TITLE → ryzyko, trudniej sprzedać w Polsce
- FRONT END / REAR END → standardowe szkody, szacuj 1000-4000 USD

ZASADY UŻYCIA CENY REZERWOWEJ (seller_reserve_usd):
- Jeśli aktualna oferta < rezerwa: auto prawdopodobnie nie zostanie sprzedane lub cena wzrośnie znacznie
- Jeśli oferta >= rezerwa: sprzedaż prawie pewna po tej cenie
- Uwzględnij to w szacunkach total cost

ZASADY UŻYCIA TYPU SPRZEDAWCY (seller_type):
- "insurance": ubezpieczyciel chce szybko pozbyć auta, ceny bardziej negocjowalne
- "dealer": reseller, cena zazwyczaj bliższa rynkowej, mniejszy margines

SZCZEGÓŁOWA ANALIZA - dla każdego lota MUSISZ podać:
1. Dlaczego wybrałeś ten lot (konkretne zalety)
2. Wszystkie dane techniczne (VIN, przebieg, rok, uszkodzenia, tytuł)
3. Analiza lokalizacji i kosztów transportu
4. Analiza ceny (bid, rezerwa, typ sprzedawcy)
5. Szacunek naprawy z uzasadnieniem
6. Całkowity koszt z rozbiciem
7. Czerwone flagi i ryzyka
8. Rekomendacja z uzasadnieniem

Zwróć WYŁĄCZNIE poprawny JSON array. Bez żadnego tekstu przed ani po.
"""
```

### Funkcja Analizy

```python
def analyze_lots(lots: List[CarLot], criteria: ClientCriteria, top_n: int = 5) -> Tuple[List[AnalyzedLot], List[AnalyzedLot]]:
    """
    Analizuje loty i zwraca (top_recommendations, all_results).
    
    Returns:
        tuple: (TOP N najlepszych lotów, wszystkie przeanalizowane loty)
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    # Przygotuj dane lotów dla AI
    lots_data = []
    for lot in lots:
        lots_data.append({
            "lot_id": lot.lot_id,
            "source": lot.source,
            "year": lot.year,
            "make": lot.make,
            "model": lot.model,
            "odometer_mi": lot.odometer_mi,
            "damage_primary": lot.damage_primary,
            "title_type": lot.title_type,
            "current_bid_usd": lot.current_bid_usd,
            "seller_reserve_usd": lot.seller_reserve_usd,  # Z rozszerzenia
            "seller_type": lot.seller_type,                # Z rozszerzenia
            "location_state": lot.location_state,
            "airbags_deployed": lot.airbags_deployed,
            "keys": lot.keys,
            "enriched_by_extension": lot.enriched_by_extension
        })
    
    # User prompt z kryteriami klienta
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
- lot_id (string)
- score (liczba 0.0–10.0)
  WAŻNE: Dodaj +1.5 dla wschodu (NY,NJ,PA,CT,MA,RI,VT,NH,ME,MD,DE,VA,NC,SC,GA,FL)
  WAŻNE: Odejmij -1.0 dla zachodu (CA,OR,WA,NV,AZ,UT,CO,NM)
- recommendation (string: "POLECAM", "RYZYKO" lub "ODRZUĆ")
- red_flags (array of strings)
- estimated_repair_usd (int lub null)
- estimated_total_cost_usd (int - bid + repair + transport + 500 inne)
- client_description_pl (string - 3-5 zdań po polsku, SZCZEGÓŁOWO)
- ai_notes (string - SZCZEGÓŁOWE uwagi techniczne dla brokera)
"""
    
    # Wywołanie Claude API
    message = client.messages.create(
        model="claude-sonnet-4-6-thinking",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    # Parsowanie JSON z odpowiedzi
    raw = message.content[0].text.strip()
    
    # Usuń markdown code blocks jeśli są
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()
    
    # Parsuj JSON
    try:
        analyses_data = json.loads(raw)
    except json.JSONDecodeError as e:
        # Retry z mniejszą liczbą lotów (max 10)
        if len(lots) > 10:
            lots = lots[:10]
            # Ponów request...
        else:
            raise Exception(f"AI zwróciło niepoprawny JSON: {e}")
    
    # Mapowanie wyników na AnalyzedLot
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
            ai_notes=ad.get("ai_notes")
        )
        results.append(AnalyzedLot(lot=lots_by_id[lot_id], analysis=analysis))
    
    # Sortowanie: POLECAM > RYZYKO > ODRZUĆ, potem po score malejąco
    order = {"POLECAM": 0, "RYZYKO": 1, "ODRZUĆ": 2}
    results.sort(key=lambda x: (order.get(x.analysis.recommendation, 99), -x.analysis.score))
    
    # Wybierz TOP N najlepszych
    top_results = results[:top_n]
    for lot in top_results:
        lot.is_top_recommendation = True
    
    return top_results, results
```

### Przykład Odpowiedzi AI

```json
[
  {
    "lot_id": "99854415",
    "score": 8.5,
    "recommendation": "POLECAM",
    "red_flags": ["Deployed airbags"],
    "estimated_repair_usd": 2500,
    "estimated_total_cost_usd": 9900,
    "client_description_pl": "Toyota Camry 2018, 45k mil, lokalizacja NJ (wschód - tani transport 1400 USD). Uszkodzenia: Front End, szacunek naprawy 2500 USD. Aktualna oferta 5500 USD poniżej rezerwy 6200 USD - prawdopodobnie cena wzrośnie. Całkowity koszt z transportem i naprawą: 9900 USD. Sprzedawca: ubezpieczyciel (insurance) - cena negocjowalna.",
    "ai_notes": "Lokalizacja: NJ - wschód, tani transport morski 1400 USD, czas 3-4 tygodnie. Bonus +1.5 do score za lokalizację. Uszkodzenia: Front End - standardowe szkody, naprawa 2500 USD (zderzak, maska, lampy, chłodnica). Deployed airbags - dodatkowe 1500 USD. Cena: aktualna oferta 5500 USD < rezerwa 6200 USD - prawdopodobnie cena wzrośnie do 6200 USD. Sprzedawca: insurance - ubezpieczyciel chce szybko sprzedać, cena negocjowalna. Całkowity koszt: 6200 (bid) + 2500 (repair) + 1400 (transport) + 500 (inne) = 10600 USD. Rekomendacja: POLECAM - dobra lokalizacja, standardowe uszkodzenia, negocjowalna cena."
  }
]
```

### Retry Mechanism

**Problem:** Claude czasami zwraca niepoprawny JSON (np. z komentarzami, markdown).

**Rozwiązanie:** Retry z mniejszą liczbą lotów (max 10):
```python
try:
    analyses_data = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"[AI] Błąd parsowania JSON: {e}")
    
    # Zapisz pełną odpowiedź do debugowania
    with open("/tmp/ai_response_error.txt", "w") as f:
        f.write(raw)
    
    # Retry z mniejszą liczbą lotów
    if len(lots) > 10:
        lots = lots[:10]
        # Ponów request z 10 lotami...
    else:
        raise Exception(f"AI zwróciło niepoprawny JSON: {e}")
```

---

## KALKULATOR OPŁACALNOŚCI

### Lokalizacja i Implementacja

**Frontend:** `/usa-car-finder/api/static/calculator.js`
**Dane:** `/usa-car-finder/api/static/calculator-data.js` (1000+ lokalizacji)

### Formuły Kalkulatora

#### Koszty USA

```javascript
const auctionFeeUsd = bidUsd * 0.08;  // Prowizja aukcyjna 8%
const usaTotalUsd = 
  additionalCostsUsd +   // Domyślnie 300 USD
  bidUsd + 
  auctionFeeUsd + 
  towingUsd +            // Auto z lokalizacji (1000+ stawek)
  loadingUsd +           // Domyślnie 560 USD
  freightUsd;            // Domyślnie 1050 USD

const usaTotalPln = usaTotalUsd * usdRate;  // Domyślnie 4.0
```

#### Osoba Prywatna

```javascript
const privateCustomsBasePln = 
  (usaTotalPln * 0.4) +                    // 40% wartości
  (550 * usdRate);                         // Stała baza akcyzy 550 USD

const privateDutyPln = privateCustomsBasePln * 0.1;  // Cło 10%
const privateVatDePln = (privateCustomsBasePln + privateDutyPln) * 0.21;  // VAT DE 21%

const privateDeFeesPln = 
  3000 +                  // Odprawa DE
  privateDutyPln + 
  privateVatDePln + 
  2500;                   // Transport w Polsce

const privateBeforeExcisePln = usaTotalPln + privateDeFeesPln;
const privateExcisePln = (privateBeforeExcisePln * 0.5) * exciseRate;  // Domyślnie 3.1%

const privateTotalPln = privateBeforeExcisePln + privateExcisePln;
```

#### Firma

```javascript
const companyDutyPln = usaTotalPln * 0.1;  // Cło 10%

const companyDeFeesPln = 
  3000 +           // Odprawa DE
  companyDutyPln;

const companyExcisePln = 
  ((bidUsd + 550) * usdRate) * exciseRate;  // Domyślnie 18.6%

const companyNetPln = usaTotalPln + companyDeFeesPln + companyExcisePln;
const companyGrossPln = 
  (companyNetPln * 1.23) +  // VAT PL 23%
  2100;                      // Transport w Polsce
```

#### Prowizje Brokera

```javascript
// Wariant Basic
const brokerBasicNetPln = 
  (bidUsd * 0.02 * usdRate) +  // 2% ceny
  1800;                         // Baza 1800 PLN

const brokerBasicGrossPln = brokerBasicNetPln * 1.23;  // VAT 23%

// Wariant Premium
const brokerPremiumNetPln = 
  (bidUsd * 0.04 * usdRate) +  // 4% ceny
  3600;                         // Baza 3600 PLN

const brokerPremiumGrossPln = brokerPremiumNetPln * 1.23;  // VAT 23%
```

#### Wynagrodzenie Pracownika

```javascript
// Wariant Basic
const employeeBasicPln = 
  (brokerBasicNetPln * 0.4) +      // 40% prowizji basic
  (topupPln * 0.2) +               // 20% dokładki
  150;                             // Stała 150 PLN

// Wariant Premium
const employeePremiumPln = 
  (brokerPremiumNetPln * 0.3) +    // 30% prowizji premium
  (topupPln * 0.2);                // 20% dokładki
```

### 1000+ Lokalizacji z Stawkami Towing

**Format danych:**
```javascript
window.TOWING_LOCATIONS = [
  {
    state: "FL",
    city: "MIAMI",
    yard: "MIAMI NORTH",
    towingUsd: 350
  },
  {
    state: "CA",
    city: "LOS ANGELES",
    yard: "FONTANA",
    towingUsd: 650
  },
  // ... 1000+ wpisów
];
```

**Automatyczny dobór towing:**
```javascript
function towingForLocation(state, city) {
  if (!state) return 1000;  // Domyślnie
  
  if (city) {
    const normalizedCity = city.trim().toUpperCase();
    const match = locations.find(
      item => item.state === state && 
              item.city.trim().toUpperCase() === normalizedCity
    );
    if (match) return match.towingUsd;
  }
  
  // Jeśli brak dokładnego dopasowania - mediana dla stanu
  return stateMedianTowing(state);
}

function stateMedianTowing(state) {
  const values = locations
    .filter(item => item.state === state)
    .map(item => item.towingUsd)
    .sort((a, b) => a - b);
  
  if (!values.length) return 1000;
  return values[Math.floor(values.length / 2)];
}
```

### Prezentacja Wyników

**3 KPI (duże liczby):**
- Suma USA: $15,850
- Osoba prywatna z akcyzą 3.1%: 68,500 PLN
- Firma brutto z akcyzą 18.6%: 82,300 PLN

**Szczegółowe rozliczenie (tabele):**
- Koszty USA (bid, prowizja, towing, dodatkowe, załadunki, fracht)
- Osoba prywatna (baza odprawy, cło, VAT DE, transport, akcyza)
- Firma (cło, VAT PL, transport, akcyza)
- Prowizje (basic netto/brutto, premium netto/brutto)
- Wynagrodzenie pracownika (basic, premium)

---

## GENEROWANIE RAPORTÓW PDF

### Technologia

**WeasyPrint 62.3** - konwersja HTML → PDF
**Jinja2** - templating HTML

**Lokalizacja:** `/usa-car-finder/report/generator.py`

### Struktura Raportu

**Strona tytułowa:**
- Logo (opcjonalnie)
- Tytuł: "Raport Aukcji USA - [Data]"
- Podsumowanie: liczba lotów, TOP 5, budżet klienta
- Kryteria wyszukiwania

**1 strona A4 per auto:**
- Nagłówek: Rok, marka, model, źródło, lot ID
- Score i rekomendacja (duży badge)
- Zdjęcie główne (jeśli dostępne)
- Metadane (2 kolumny):
  - VIN, przebieg, uszkodzenia, tytuł
  - Cena aukcyjna, lokalizacja, data aukcji
- Red flags (żółte/czerwone tagi)
- Opis kliencki (po polsku, 3-5 zdań)
- Kalkulacja kosztów:
  - Szacowana naprawa
  - Łączny koszt (bid + repair + transport + fees)
  - Osoba prywatna (PLN)
  - Firma brutto (PLN)
- Zalety (bullet points)
- Ryzyka (bullet points)
- Weryfikacja (checklist):
  - [ ] Sprawdzono VIN w Carfax/AutoCheck
  - [ ] Zweryfikowano historię serwisową
  - [ ] Oszacowano koszty naprawy przez mechanika
  - [ ] Potwierdzono dostępność części

### Implementacja

```python
from weasyprint import HTML
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

def generate_pdf_report(lots: List[AnalyzedLot]) -> Path:
    """
    Generuje PDF z zatwierdzonych lotów.
    
    Args:
        lots: Lista AnalyzedLot z included_in_report=True
        
    Returns:
        Path do wygenerowanego PDF
    """
    # Przygotuj dane dla template
    report_data = {
        "title": f"Raport Aukcji USA - {datetime.now().strftime('%Y-%m-%d')}",
        "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M'),
        "total_lots": len(lots),
        "top_count": sum(1 for lot in lots if lot.is_top_recommendation),
        "lots": lots
    }
    
    # Renderuj HTML z Jinja2
    env = Environment(loader=FileSystemLoader('templates'))
    template = env.get_template('report.html.j2')
    html_content = template.render(**report_data)
    
    # Konwertuj HTML → PDF
    output_path = Path("./data/reports") / f"report_{int(time.time())}.pdf"
    HTML(string=html_content).write_pdf(output_path)
    
    return output_path
```

### Template Jinja2 (fragment)

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    @page { size: A4; margin: 2cm; }
    body { font-family: Arial, sans-serif; }
    .lot-page { page-break-after: always; }
    .badge-green { background: #10b981; color: white; }
    .badge-yellow { background: #f59e0b; color: white; }
    .badge-red { background: #ef4444; color: white; }
  </style>
</head>
<body>
  <!-- Strona tytułowa -->
  <div class="title-page">
    <h1>{{ title }}</h1>
    <p>Wygenerowano: {{ generated_at }}</p>
    <p>Liczba lotów: {{ total_lots }} (TOP {{ top_count }})</p>
  </div>
  
  <!-- Strona per auto -->
  {% for analyzed_lot in lots %}
  <div class="lot-page">
    <h2>{{ analyzed_lot.lot.year }} {{ analyzed_lot.lot.make }} {{ analyzed_lot.lot.model }}</h2>
    <span class="badge badge-{{ analyzed_lot.analysis.recommendation|lower }}">
      {{ analyzed_lot.analysis.recommendation }}
    </span>
    <p>Score: {{ analyzed_lot.analysis.score }}/10</p>
    
    <div class="metadata">
      <div>VIN: {{ analyzed_lot.lot.full_vin or analyzed_lot.lot.vin }}</div>
      <div>Przebieg: {{ analyzed_lot.lot.odometer_mi }} mi</div>
      <div>Uszkodzenia: {{ analyzed_lot.lot.damage_primary }}</div>
      <div>Tytuł: {{ analyzed_lot.lot.title_type }}</div>
      <div>Cena: ${{ analyzed_lot.lot.current_bid_usd }}</div>
      <div>Lokalizacja: {{ analyzed_lot.lot.location_state }}</div>
    </div>
    
    <div class="red-flags">
      {% for flag in analyzed_lot.analysis.red_flags %}
      <span class="tag">{{ flag }}</span>
      {% endfor %}
    </div>
    
    <p>{{ analyzed_lot.analysis.client_description_pl }}</p>
    
    <div class="costs">
      <div>Naprawa: ${{ analyzed_lot.analysis.estimated_repair_usd }}</div>
      <div>Łącznie: ${{ analyzed_lot.analysis.estimated_total_cost_usd }}</div>
    </div>
  </div>
  {% endfor %}
</body>
</html>
```

---

## INTEGRACJE ZEWNĘTRZNE

### Copart API (Scraping)

**Endpoint:** https://www.copart.com
**Metoda:** Playwright headless browser automation
**Dane pobierane:**
- Lot ID, VIN (częściowy - ukryte ostatnie 6 znaków), rok, marka, model
- Przebieg (mile), lokalizacja (stan, miasto)
- Uszkodzenia (primary/secondary), typ tytułu
- Cena aukcyjna, Buy Now, data aukcji
- Zdjęcia (5 strategii pobierania)

**Storage state:** `playwright_profiles/copart.json`

### IAAI API (Scraping)

**Endpoint:** https://www.iaai.com
**Metoda:** Playwright headless browser automation
**Dane:** Analogiczne do Copart
**Storage state:** `playwright_profiles/iaai.json`

### Claude API (Anthropic)

**Model:** claude-sonnet-4-6-thinking
**Endpoint:** https://api.anthropic.com/v1/messages
**Klucz:** `ANTHROPIC_API_KEY=qua-3fe84831eb5df3856a4790c2461ae1bf`
**Max tokens:** 8192

**Zadania:**
- Analiza lotów z aukcji
- Ocena damage_score (0-10)
- Szacowanie repair_cost_min/max
- Risk flags (frame_damage, flood_damage, fire_damage, airbag_deployed)
- Investment recommendation (POLECAM/RYZYKO/ODRZUĆ)
- Opis po polsku dla klienta

### Gmail API (Monitoring Alertów)

**Protokół:** IMAP + App Password
**Credentials:**
- `GMAIL_ADDRESS=damiansomano@gmail.com`
- `GMAIL_APP_PASSWORD=cplbgqmrikgqawou`

**Funkcja:** Automatyczne pobieranie alertów email z Copart/IAAI

**Lokalizacja:** `/usa-car-finder/email_integration/gmail_client.py`

### Telegram Bot (Notyfikacje)

**Credentials:**
- `TELEGRAM_BOT_TOKEN=8527421679:AAEY8aqDzm2rsUUpTiOLEG6mrelNxLizops`
- `TELEGRAM_CHAT_ID=7594790035`

**Funkcja:** Wysyłanie notyfikacji o nowych lotach spełniających kryteria (score >7, ROI >30%)

### NBP API (Kurs USD/PLN)

**Endpoint:** http://api.nbp.pl/api/exchangerates/rates/a/usd/
**Status:** Dokumentowany w `KALKULATOR_ZALOZENIA.md`, implementacja nieznana
**Funkcja:** Automatyczna aktualizacja kursu USD/PLN (codziennie)

---

## WORKFLOW UŻYTKOWNIKA

### Scenariusz 1: Wyszukiwanie i Raport

**Krok 1: Formularz wyszukiwania**
```
Użytkownik:
- Otwiera http://localhost:8000
- Wypełnia: Toyota Camry, 2018-2020, budżet $15000, max 80k mil
- Wyklucza: Flood, Fire
- Klik "Szukaj i analizuj"
```

**Krok 2: Backend - Search Pipeline**
```
POST /search
→ AutomatedScraper.search_cars(criteria)
  → Równolegle: CopartScraper + IAAIScraper (Playwright)
  → Cache HTML (jeśli FORCE_REFRESH=false i cache <24h)
  → Parser HTML → list[CarLot]
  → Opcjonalnie: ExtensionEnricher (pełny VIN, reserve price)
→ analyze_lots(all_lots, criteria, top_n=5)
  → Claude API: analiza każdego lotu
  → Ranking według score + ROI
  → TOP 5 + 5 dodatkowych
→ SearchResponse(top_recommendations, all_results)
```

**Krok 3: Frontend - Przegląd wyników**
```
- Wyświetla TOP 5 z zielonymi kartami
- Pozostałe 5 jako "Inne propozycje"
- Użytkownik może:
  - Usunąć loty z raportu (included_in_report=false)
  - Zmienić rekomendację (POLECAM/RYZYKO/ODRZUĆ)
  - Przeliczyć w kalkulatorze (auto-fill)
  - Zatwierdzić wybrane loty
```

**Krok 4: Generowanie raportu**
```
POST /report
→ generate_pdf_report(approved_lots)
  → Jinja2 template: report.html.j2
  → WeasyPrint: HTML → PDF
  → Zapis: ./data/reports/report_TIMESTAMP.pdf
→ FileResponse (download PDF)
```

### Scenariusz 2: Monitoring Email (Automatyczny)

**Krok 1: Gmail Client**
```
- Cron/scheduler pobiera nowe emaile z Copart/IAAI
- gmail_client.py używa IMAP + App Password
```

**Krok 2: Email Parser**
```
- email_parser.py ekstrahuje dane lotów z HTML emails
- Tworzy obiekty CarLot
```

**Krok 3: Analiza + Notyfikacja**
```
- Claude API analizuje nowe loty
- Jeśli score >7 i ROI >30%:
  → Wysyła notyfikację Telegram
```

### Scenariusz 3: Generator Ofert Handlowych (DOCX)

**Input:** Raport PDF/DOCX z analizą aut
**Output:** Dokument DOCX z ofertą handlową

**Proces:**
1. Ekstrakcja danych z raportu źródłowego
2. Scalanie duplikatów (po VIN/Lot ID)
3. Redakcja treści (usunięcie krzykliwych sformułowań)
4. Generowanie karty per auto (1 strona A4)
5. Dodanie strony tytułowej z podsumowaniem
6. Renderowanie DOCX → PNG (weryfikacja layoutu)

**Agent:** `agent-oferta-auto-usa.md` (prompt dla Claude)
**Instrukcja:** `claude_code_instrukcja_raport_ofertowy.md`

---

## KONFIGURACJA I ZMIENNE ŚRODOWISKOWE

### Plik .env

**Lokalizacja:** `/usa-car-finder/.env`

```bash
# AI
ANTHROPIC_API_KEY=qua-3fe84831eb5df3856a4790c2461ae1bf

# Scraping
MAX_RESULTS_PER_SOURCE=30
HEADLESS=false                 # true w produkcji
SLOW_MO_MS=0
USE_EXTENSIONS=false           # true dla pełnego VIN + reserve price
USE_MOCK_DATA=false            # true dla testów
FORCE_REFRESH=true             # true = zawsze świeże dane
CACHE_MAX_AGE_HOURS=24

# Filtering
MIN_AUCTION_WINDOW_HOURS=12
MAX_AUCTION_WINDOW_HOURS=168  # 7 dni
FILTER_SELLER_INSURANCE_ONLY=false

# Paths
HTML_CACHE_DIR=./data/html_cache
REPORTS_DIR=./data/reports
CHROME_PROFILE_DIR=./data/chrome_profile
CHROME_EXECUTABLE_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome

# Email
GMAIL_ADDRESS=damiansomano@gmail.com
GMAIL_APP_PASSWORD=cplbgqmrikgqawou
CLIENT_EMAIL=damiansomano@gmail.com

# Telegram
TELEGRAM_BOT_TOKEN=8527421679:AAEY8aqDzm2rsUUpTiOLEG6mrelNxLizops
TELEGRAM_CHAT_ID=7594790035
```

### Opis Zmiennych

**AI:**
- `ANTHROPIC_API_KEY` - klucz API Claude (wymagany)

**Scraping:**
- `MAX_RESULTS_PER_SOURCE` - max liczba lotów per źródło (Copart/IAAI)
- `HEADLESS` - tryb headless przeglądarki (true=bez GUI, false=z GUI)
- `SLOW_MO_MS` - opóźnienie między akcjami Playwright (0=brak, 1500=1.5s)
- `USE_EXTENSIONS` - czy używać rozszerzeń Chrome (true=tak, false=nie)
- `USE_MOCK_DATA` - czy używać danych testowych (true=tak, false=nie)
- `FORCE_REFRESH` - czy zawsze pobierać świeże dane (true=tak, false=użyj cache)
- `CACHE_MAX_AGE_HOURS` - TTL cache HTML (domyślnie 24h)

**Filtering:**
- `MIN_AUCTION_WINDOW_HOURS` - minimalne okno aukcji (domyślnie 12h)
- `MAX_AUCTION_WINDOW_HOURS` - maksymalne okno aukcji (domyślnie 168h = 7 dni)
- `FILTER_SELLER_INSURANCE_ONLY` - czy filtrować tylko ubezpieczycieli (true=tak)

**Paths:**
- `HTML_CACHE_DIR` - katalog cache HTML
- `REPORTS_DIR` - katalog raportów PDF
- `CHROME_PROFILE_DIR` - profil Chrome (cookies, localStorage)
- `CHROME_EXECUTABLE_PATH` - ścieżka do Google Chrome (dla rozszerzeń)

**Email:**
- `GMAIL_ADDRESS` - adres Gmail
- `GMAIL_APP_PASSWORD` - hasło aplikacji Gmail (nie hasło konta!)
- `CLIENT_EMAIL` - email klienta (do wysyłki raportów)

**Telegram:**
- `TELEGRAM_BOT_TOKEN` - token bota Telegram
- `TELEGRAM_CHAT_ID` - ID czatu do wysyłki notyfikacji

---

## STRATEGIE ANTI-BOT I RATE LIMITING

### User-Agent Spoofing

```python
user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
context = await browser.new_context(user_agent=user_agent)
```

### Automation Detection Bypass

```python
browser = await p.chromium.launch(
    headless=True,
    args=["--disable-blink-features=AutomationControlled"]
)
```

### Realistic Browser Fingerprint

```python
context = await browser.new_context(
    viewport={"width": 1365, "height": 900},
    locale="en-US",
    timezone_id="America/New_York"
)
```

### Random Jitter (1.5-4s)

```python
import random
import asyncio

async def jitter():
    await asyncio.sleep(random.uniform(1.5, 4.0))

# Użycie
await page.goto(url)
await jitter()
await page.click("button")
await jitter()
```

### Storage State (Wygląda jak Prawdziwy Użytkownik)

```python
# Zamiast logowania przy każdym uruchomieniu
context = await browser.new_context(
    storage_state='playwright_profiles/copart.json'
)
# Przeglądarka ma zapisane cookies, localStorage, sessionStorage
# Wygląda jak kontynuacja sesji prawdziwego użytkownika
```

### Cache HTML (Zmniejsza Liczbę Requestów)

```python
cache_path = HTML_CACHE_DIR / source / f"{lot_id}.html"

if cache_path.exists() and not FORCE_REFRESH:
    age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
    if age_hours < CACHE_MAX_AGE_HOURS:
        return cache_path  # Użyj cache, nie rób nowego requestu

# Cache nieświeży - pobierz na nowo
await page.goto(url)
html = await page.content()
cache_path.write_text(html)
```

### Rate Limiting Giełd

**Copart:** ~30 zapytań/dzień per IP (szacunek)
**IAAI:** ~50 zapytań/dzień per IP (szacunek)

**Strategia:**
- Cache HTML (24h TTL) - zmniejsza liczbę requestów
- Random jitter (1.5-4s) - nie wygląda jak bot
- Storage state - nie loguj się przy każdym uruchomieniu
- Scraping w nocy (mniejszy ruch) - opcjonalnie

---

## TIMEOUTS I LIMITY

### Scraper Timeout

```python
SCRAPER_TIMEOUT_S = 180  # 3 minuty per scraper (Railway jest wolniejsze)

scraped = await asyncio.wait_for(
    mod.search(criteria),
    timeout=SCRAPER_TIMEOUT_S
)
```

### Page Timeouts

```python
# page.goto
await page.goto(url, timeout=30000)  # 30s

# wait_for_selector
await page.wait_for_selector(sel, timeout=15000)  # 15s

# wait_for_timeout (statyczny delay)
await page.wait_for_timeout(3000)  # 3s dla JavaScript
```

### Cache TTL

```python
CACHE_MAX_AGE_HOURS = 24  # 24 godziny

# Sprawdź wiek cache
age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
if age_hours < CACHE_MAX_AGE_HOURS:
    # Cache świeży - użyj
else:
    # Cache nieświeży - pobierz na nowo
```

---

## INSTRUKCJE URUCHOMIENIA

### Wymagania Systemowe

**Python:** 3.9+
**Node.js:** Nie wymagany (frontend to Vanilla JS)
**System operacyjny:** macOS, Linux, Windows (z WSL)
**RAM:** Minimum 4GB (8GB zalecane)
**Dysk:** 2GB wolnego miejsca (cache HTML + Chromium)

### Instalacja Zależności

```bash
cd usa-car-finder

# Utwórz wirtualne środowisko
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# lub
venv\Scripts\activate  # Windows

# Zainstaluj zależności Python
pip install -r requirements.txt

# Zainstaluj przeglądarki Playwright
playwright install chromium
```

### Konfiguracja .env

```bash
# Skopiuj przykładowy plik
cp .env.example .env

# Edytuj .env i uzupełnij:
nano .env

# Wymagane:
ANTHROPIC_API_KEY=twoj-klucz-api

# Opcjonalne (dla rozszerzeń Chrome):
USE_EXTENSIONS=false
CHROME_EXECUTABLE_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

### Tworzenie Storage State (Sesje Logowania)

**Opcja 1: Ręczne logowanie (zalecane)**

```bash
# Uruchom Playwright w trybie GUI
python3 -c "
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    
    # Copart
    page.goto('https://www.copart.com')
    input('Zaloguj się ręcznie, potem naciśnij Enter...')
    context.storage_state(path='../playwright_profiles/copart.json')
    
    # IAAI
    page.goto('https://www.iaai.com')
    input('Zaloguj się ręcznie, potem naciśnij Enter...')
    context.storage_state(path='../playwright_profiles/iaai.json')
    
    browser.close()
"
```

**Opcja 2: Użyj istniejących sesji**

Jeśli masz już zapisane sesje w `playwright_profiles/`, możesz je użyć bezpośrednio.

### Uruchomienie Serwera

```bash
# Tryb development (auto-reload)
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Tryb production
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

**Otwórz przeglądarkę:** http://localhost:8000

### Testowanie z Mock Data

```bash
# Ustaw w .env
USE_MOCK_DATA=true

# Uruchom serwer
uvicorn api.main:app --reload
```

Mock data pozwala testować frontend i AI bez scrapowania prawdziwych aukcji.

### Deployment na Railway

**1. Przygotuj projekt:**
```bash
# Dodaj Procfile
echo "web: uvicorn api.main:app --host 0.0.0.0 --port \$PORT" > Procfile

# Dodaj runtime.txt
echo "python-3.9" > runtime.txt
```

**2. Deploy:**
```bash
# Zainstaluj Railway CLI
npm install -g @railway/cli

# Login
railway login

# Deploy
railway up
```

**3. Ustaw zmienne środowiskowe w Railway Dashboard:**
- `ANTHROPIC_API_KEY`
- `HEADLESS=true`
- `USE_EXTENSIONS=false` (rozszerzenia nie działają bez GUI)
- `FORCE_REFRESH=false` (użyj cache)

### Troubleshooting

**Problem: Playwright nie może znaleźć Chromium**
```bash
playwright install chromium
```

**Problem: Scraper zwraca 0 wyników**
```bash
# Sprawdź czy storage_state istnieje
ls playwright_profiles/

# Sprawdź czy sesja jest aktualna (zaloguj się ponownie)
```

**Problem: Claude API zwraca błąd 401**
```bash
# Sprawdź klucz API
echo $ANTHROPIC_API_KEY

# Wygeneruj nowy klucz na https://console.anthropic.com
```

**Problem: Timeout po 180s**
```bash
# Zwiększ timeout w automated_scraper.py
SCRAPER_TIMEOUT_S = 300  # 5 minut
```

---

## OGRANICZENIA I ZASTRZEŻENIA

### Rozszerzenia Chrome

**Ograniczenie:** Tylko lokalnie (headless=False)
**Powód:** Rozszerzenia Chrome nie działają w trybie headless
**Konsekwencja:** Nie można używać na Railway (brak GUI)
**Rozwiązanie:** Używaj standardowego scrapowania bez rozszerzeń w produkcji

### Rate Limiting Aukcji

**Copart:** ~30 zapytań/dzień per IP
**IAAI:** ~50 zapytań/dzień per IP
**Konsekwencja:** Przekroczenie limitu = ban IP (24h-7 dni)
**Rozwiązanie:**
- Cache HTML (24h TTL)
- Random jitter (1.5-4s)
- Scraping w nocy (mniejszy ruch)
- Rotacja IP (proxy, VPN)

### Koszty Naprawy - Szacunki

**Ograniczenie:** AI szacuje koszty na podstawie zdjęć
**Powód:** Brak fizycznej inspekcji pojazdu
**Konsekwencja:** Rzeczywiste koszty mogą być wyższe (ukryte uszkodzenia)
**Rozwiązanie:**
- Dodaj bufor bezpieczeństwa +10-15%
- Zawsze weryfikuj przez mechanika przed zakupem
- Sprawdź VIN w Carfax/AutoCheck

### Wartość Sprzedaży - Zależna od Rynku

**Ograniczenie:** Szacunki oparte na Otomoto.pl, AutoScout24.pl
**Powód:** Rynek samochodów używanych jest dynamiczny
**Konsekwencja:** Wartość sprzedaży może być niższa niż szacowana
**Rozwiązanie:**
- Sprawdź aktualne ceny przed zakupem
- Uwzględnij sezonowość (zima/lato)
- Rozważ popularność modelu w Polsce

### Czas Sprzedaży

**Założenie:** 30-90 dni
**Rzeczywistość:** Może być dłuższy (3-6 miesięcy)
**Konsekwencja:** Koszty magazynowania, finansowania
**Rozwiązanie:**
- Uwzględnij koszty magazynowania w kalkulacji
- Nie kupuj więcej niż możesz sprzedać w 3 miesiące

### Headless Detection

**Problem:** Copart wykrywa headless Chrome
**Status:** Dokumentacja wspomina ScraperAPI proxy, ale kod używa Playwright
**Rozwiązanie:** Storage state + anti-detection techniques (user-agent, automation bypass)

### Brak Tradycyjnej Bazy Danych

**Ograniczenie:** Brak historii wyszukiwań, statystyk
**Powód:** Aplikacja działa w trybie "stateless"
**Konsekwencja:** Nie można analizować trendów, popularnych modeli
**Rozwiązanie:** Dodaj PostgreSQL/MySQL jeśli potrzebna analityka

### Bufor Bezpieczeństwa

**Zalecenie:** Zawsze dodaj 10-15% bufora do Total Investment
**Powód:**
- Ukryte uszkodzenia (nie widoczne na zdjęciach)
- Wzrost cen części (inflacja)
- Nieprzewidziane koszty (dodatkowe opłaty, naprawy)
- Wahania kursów walut (USD/PLN)

**Przykład:**
```
Total Investment (AI): $15,000
Bufor 15%: $2,250
Total Investment (bezpieczny): $17,250
```

---

## PODSUMOWANIE

### Kluczowe Cechy Aplikacji

1. **Automatyzacja** - Równoległe scrapowanie Copart + IAAI przez Playwright
2. **Inteligencja** - Claude Sonnet 4.6 analizuje każdy lot (score, rekomendacje, koszty)
3. **Lokalizacja** - Bonus za wschód USA (+1.5), penalty za zachód (-1.0)
4. **Kalkulator** - 1000+ lokalizacji z stawkami towing, automatyczne przeliczenie
5. **Raport PDF** - Profesjonalny dokument dla klienta (TOP 5 + dodatkowe)

### Stack Technologiczny

- **Frontend:** Vanilla JavaScript (nie React!)
- **Backend:** FastAPI + Playwright + Claude API
- **Baza danych:** Brak (cache HTML, storage state)
- **Deployment:** Railway (lub dowolny ASGI server)

### Główne Wyzwania

1. **Anti-bot detection** - Storage state, user-agent spoofing, random jitter
2. **Rate limiting** - Cache HTML (24h), scraping w nocy
3. **Headless detection** - Storage state zamiast logowania
4. **Rozszerzenia Chrome** - Tylko lokalnie (headless=False)

### Następne Kroki

1. **Instalacja** - Python 3.9+, Playwright, zależności
2. **Konfiguracja** - .env (ANTHROPIC_API_KEY), storage_state
3. **Uruchomienie** - uvicorn api.main:app --reload
4. **Testowanie** - Mock data (USE_MOCK_DATA=true)
5. **Deployment** - Railway (HEADLESS=true, USE_EXTENSIONS=false)

### Dokumentacja Dodatkowa

- `PLAYWRIGHT_ARCHITECTURE.md` - Szczegóły scraperów
- `GEMINI_PROMPT.md` - Prompt AI (nieużywany, zastąpiony Claude)
- `KALKULATOR_ZALOZENIA.md` - Formuły kalkulatora
- `usa_car_finder_prompt.md` - Oryginalny prompt budowy
- `README.md` - Quick start guide

---

**Wersja dokumentu:** 1.0  
**Data:** 2026-04-28  
**Autor:** Claude Sonnet 4.6  
**Przeznaczenie:** Kompletna dokumentacja założeń dla modeli AI (Claude, Gemini) do zbudowania aplikacji od zera

