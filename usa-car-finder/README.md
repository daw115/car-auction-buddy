# USA Car Finder

Aplikacja do wyszukiwania i analizy aut z aukcji Copart i IAAI z analizą AI.

## Szybki start

```bash
# 1. Zainstaluj zależności
pip install -r requirements.txt
playwright install chromium

# 2. Konfiguracja
cp .env.example .env
# Edytuj .env i wpisz OPENAI_API_KEY albo ANTHROPIC_API_KEY

# 3. Uruchom
python -m api.main

# 4. Otwórz przeglądarkę
# http://localhost:8000
```

## Tryb demo bez scrapingu i API

Frontend ma przełącznik `Tryb demo`, który używa danych z `scraper/mock_data.py`
i lokalnego scoringu. Możesz też wymusić tryb lokalny z terminala:

```bash
USE_MOCK_DATA=true AI_ANALYSIS_MODE=local python -m api.main
```

`AI_ANALYSIS_MODE`:
- `auto` - używa OpenAI, potem Claude, a przy błędzie przechodzi na lokalny scoring
- `openai` / `gpt` - używa OpenAI; bez poprawnego `OPENAI_API_KEY` przechodzi na lokalny scoring
- `anthropic` - używa Claude; bez `ANTHROPIC_API_KEY` przechodzi na lokalny scoring
- `local` - zawsze używa lokalnego scoringu

Jeśli chcesz, żeby brak klucza albo błąd API przerywał wyszukiwanie zamiast robić fallback,
ustaw `AI_ANALYSIS_STRICT=true`.

## Artefakty po wyszukiwaniu

Endpoint `POST /search` zapisuje komplet plików w `data/client_searches/` i zwraca linki
w polu `artifact_urls`:

- `ai_input` - pełny JSON lotów przekazywany do analizy
- `ai_prompt` - gotowy prompt/dane do wklejenia w zewnętrzne AI
- `analysis_json` - ranking, statusy i uzasadnienia w JSON
- `client_report` - raport Markdown gotowy do wklejenia klientowi

Pliki można pobrać przez `/artifacts/{filename}`. UI pokazuje te linki nad listą wyników.

## Raporty z panelu wyników

Po wyszukiwaniu i zatwierdzeniu aut aplikacja ma dwa generatory:

- `PDF techniczny` - raport porównawczy z tabelą, score i kalkulacją importu
- `Mail HTML` - gotowy mail ofertowy dla klienta, oparty o strukturę z `przyklady_maili_README.md`

Endpointy:

- `POST /report`
- `POST /report/offer-email-html`

## Integracja rozszerzeń Chromium (opcjonalne)

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
# KEEP_BROWSER_OPEN=true               # jeden stały Chrome z profilem data/chrome_profile
# BROWSER_CHANNEL=chromium             # Chrome >=137 ignoruje --load-extension (patrz sekcja Manheim)
# BROWSER_EXECUTABLE_PATH=             # opcjonalnie pełna ścieżka do binarki Chromium
# DISABLED_EXTENSIONS=                 # np. auctiongate, tylko awaryjnie
# USE_MOCK_DATA=false
# AI_ANALYSIS_MODE=auto                  # auto | anthropic | local
# Uwaga: AuctionGate potrafi zawiesić start bundled Chromium na swoim service
# workerze — stąd DISABLED_EXTENSIONS=auctiongate. Przejście na Google Chrome
# NIE jest już obejściem: od Chrome 137 rozszerzenia nie ładują się tam wcale.
# FILTER_SELLER_INSURANCE_ONLY=false   # opcjonalnie true, aby zostawić tylko seller_type=insurance
# FORCE_REFRESH=true                   # true = zawsze pobieraj świeże strony (bez cache)
# CACHE_MAX_AGE_HOURS=24               # po ilu godzinach cache lotu uznać za przeterminowany
# SEARCH_MAX_PAGES=5                   # ile stron wyników przeglądać na Copart/IAAI przed pobraniem detali
# SEARCH_DETAIL_MULTIPLIER=4           # ile detali pobrać względem Max wyników, poza ścisłym trybem testowym
# MAX_RESULTS_PER_SOURCE=100           # maks. kandydatów z jednego źródła po filtrach listy
# OPEN_ALL_PREFILTERED_DETAILS=true    # otwieraj wszystkie loty, które przeszły filtry listy
# COLLECT_ALL_PREFILTERED_RESULTS=true # max_results traktuj jako TOP po AI, nie limit surowych lotów
# STRICT_SCAN_MAX_RESULTS_THRESHOLD=3  # max_results <= 3 pobiera tylko tyle rekordów, bez zapasu
# BLOCK_MEDIA_ASSETS=false             # true = blokuj ładowanie obrazów/fontów (szybciej, ale mniej danych o mediach)
# MIN_AUCTION_WINDOW_HOURS=12          # dolna granica filtra końca aukcji
# MAX_AUCTION_WINDOW_HOURS=120         # górna granica filtra końca aukcji (5 dni)
# EXTENSION_IFRAME_WAIT_SECONDS=15     # ile czekać na iframe bota na stronie aukcji
# AUTOHELPERBOT_DIRECT_WAIT_SECONDS=20 # fallback: bezpośredni odczyt AutoHelperBot w tym samym profilu
# ORCHESTRATOR_MAX_RESULTS=10          # docelowo TOP 5 + 5 dodatkowych propozycji

# Przy pierwszym uruchomieniu zaloguj się raz w obu rozszerzeniach
# Sesja zostanie zapisana w ./data/chrome_profile/
# Gdy USE_EXTENSIONS=true, scraper odczytuje dane botów bezpośrednio z iframe
# na stronie detalu, zamiast liczyć na zapisanie iframe w HTML.
```

## Manheim (źródło uzupełniające, TOP 3)

Manheim wymaga konta dealerskiego, a sesję utrzymuje wtyczka **BidWise (Eridan)**.
Ustalenia z rozpoznania na żywo, wszystkie zmierzone:

| próba | wynik |
| --- | --- |
| wyłączenie BidWise | `search.manheim.com` → przekierowanie na publiczne `site.manheim.com` |
| Chrome ≥ 137 + `--load-extension` | wtyczka w ogóle się nie ładuje |
| Chromium + `--load-extension` | ładuje się, po ~10 s wyłącza SAMA SIEBIE (`disable_reasons=1`) |
| Playwright/CDP na karcie Manheima | karta znika w ciągu 5 s, także bez żadnej interakcji |

Przyczyna ostatniego: BidWise trzyma slot `chrome.debugger` (tak wstrzykuje
autoryzację), a Chrome dopuszcza jednego klienta debuggera na kartę. Dlatego
**dane nie są scrapowane, tylko przychodzą pushem ze strony** — przez własne
rozszerzenie `extensions/manheim-collector`, które nie dotyka debuggera.

```bash
# 1. Chrome z BidWise (raz: zainstaluj ze Web Store i zaloguj)
bash scripts/manheim_chrome_debug.sh

# 2. Kolektor: chrome://extensions → Developer mode → Load unpacked
#    → extensions/manheim-collector

# 3. .env
# MANHEIM_BACKEND_ENABLED=true
# MANHEIM_SOURCE_MODE=collector

# 4. Backend + wyszukiwanie na Manheimie w tym oknie
python -m api.main
curl -s http://127.0.0.1:8000/api/manheim/status
```

Jak to działa:

- SPA woła `POST onesearch-api.manheim.com/graphql`: `getSearches` z hasłem
  (`{"keyword":"toyota rav4",…}` — JSON zapakowany w string) zwraca `searchId`,
  a `getExecuteSearchId` pełne wyniki.
- Wyniki wracają jako **gzip w base64** w `stringifiedJSON` przy `compressed: true`
  (zmierzone: 1,13 MB → 100 lotów). Rozpakowuje to `parser/manheim_records.py`.
- Każdy lot przychodzi w dwóch fragmentach (opis + pod-obiekt z detalami), więc
  rekordy scalamy po VIN-ie: 200 surowych → 100 pojazdów.
- `api/manheim_ingest.py` trzyma je z TTL (`MANHEIM_INGEST_TTL_MINUTES`), a źródło
  `manheim` filtruje po kryteriach klienta i oddaje TOP 3.

Czego się spodziewać:

- `GET /api/capabilities` zwraca `manheim: {available: true, mode: "live"}` tylko
  przy komplecie konfiguracji; inaczej `unavailable` z
  `reason: manheim_session_not_configured`.
- Loty OVE / Buy Now / Private Store nie mają terminu zakończenia aukcji —
  domyślnie (`MANHEIM_IGNORE_AUCTION_WINDOW=true`) przechodzą przez filtr okna
  czasowego, inaczej Manheim zawsze dawałby 0 wyników.
- `FILTER_SELLER_INSURANCE_ONLY=true` wycina Manheima w całości — to rynek
  dealerski, `seller_type` zawsze `dealer`.
### Wyszukiwanie na żądanie

Źródło `manheim` nie czeka na to, aż operator sam czegoś poszuka — zleca hasło
i dostaje świeże wyniki. Kierunek jest odwrócony, bo backend nie ma jak wejść
na Manheima:

```
źródło manheim → zadanie {keyword}                (api/manheim_jobs.py)
rozszerzenie   → GET  /api/manheim/next-job       (co ~5 s, chrome.alarms)
strona         → getSearches {keyword}            → {"id": …}
strona         → getExecuteSearchId {searchId}    → wyniki
rozszerzenie   → POST /api/manheim/ingest {jobId} → backend budzi czekające źródło
```

Zmierzone na żywo: 100 pojazdów w ~7 sekund od zlecenia. Ręczne wyzwolenie
(bez odpalania analizy AI):

```bash
curl -s -X POST http://127.0.0.1:8000/api/manheim/search \
  -H "Content-Type: application/json" \
  -d '{"keyword":"Toyota RAV4","timeoutSeconds":70}'
```

Dwie rzeczy warte zapamiętania:

- Szablon żądania pochodzi z ruchu samej aplikacji, więc **po przeładowaniu
  karty trzeba raz wyszukać ręcznie**. Zanim to nastąpi, zlecenie kończy się
  czytelnym błędem, a źródło sięga po to, co kolektor zebrał wcześniej.
- Zadanie wydane, a nieodesłane w `MANHEIM_JOB_LEASE_SECONDS`, wraca do kolejki
  — service worker MV3 bywa usypiany w trakcie roboty.

## Architektura

```
Formularz → Scraper (Playwright) → HTML Cache → Parser → AI → Ranking/Markdown/PDF/Mail HTML
                ↕ opcjonalnie
         Rozszerzenia Chromium
         (AuctionGate + AutoHelperBot)
         → pełny VIN, reserve price, seller type
```

## Tryby danych

- `USE_MOCK_DATA=false` (domyślnie): prawdziwy scraping Copart/IAAI
- `USE_MOCK_DATA=true`: dane testowe z `scraper/mock_data.py`

## Zewnętrzny dashboard (np. car-auction-buddy) → lokalny serwer przez Cloudflare Tunnel

Backend wystawia synchroniczny adapter `POST /api/search` zgodny z kontraktem
[car-auction-buddy](https://github.com/daw115/car-auction-buddy):

- Body: `{ "criteria": ClientCriteria }`
- Response: `{ listings: CarLot[], source, job_id, criteria, vin_coverage, analysis_notice }`
- Idempotency: ten sam `criteria` w oknie `IDEMPOTENCY_TTL_MIN` (default 30 min) zwraca ten sam `job_id`.
- Auth: `Authorization: Bearer <SCRAPER_API_TOKEN>` (gdy zmienna ustawiona; pusta = endpoint otwarty).

### .env

```bash
SCRAPER_API_TOKEN=<długi-losowy-string>           # opcjonalny, ale zalecany dla publicznego tunelu
DASHBOARD_ORIGINS=https://twoj-dashboard.workers.dev,http://localhost:5173
IDEMPOTENCY_TTL_MIN=30
JOB_DB_PATH=./data/jobs.db
```

### Cloudflare Tunnel (quick mode, bez konta)

```bash
# 1. Zainstaluj cloudflared
brew install cloudflared    # macOS
# lub: https://github.com/cloudflare/cloudflared/releases

# 2. Uruchom backend
python -m api.main

# 3. W drugim terminalu — szybki tunel z losową subdomeną
cloudflared tunnel --url http://localhost:8000
# Wypisze: https://<random>.trycloudflare.com
```

W dashboardzie (Cloudflare Workers) ustaw sekrety:

```bash
SCRAPER_BASE_URL=https://<random>.trycloudflare.com
SCRAPER_API_TOKEN=<ten sam długi-losowy-string>
```

### Stała subdomena (z kontem CF)

```bash
cloudflared tunnel login
cloudflared tunnel create usa-car-finder
cloudflared tunnel route dns usa-car-finder scraper.twoja-domena.pl
# config.yml: tunnel: <id>; ingress: [{ hostname: scraper.twoja-domena.pl, service: http://localhost:8000 }, ...]
cloudflared tunnel run usa-car-finder
```

### Sanity check

```bash
# zewnętrznie:
curl -X POST https://<tunel>/api/search \
  -H "Authorization: Bearer $SCRAPER_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"criteria":{"make":"Toyota","budget_usd":20000}}'
# oczekiwane: {"listings":[...],"source":"live","job_id":"...",...}
```
