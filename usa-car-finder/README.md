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
# BROWSER_CHANNEL=chrome               # Google Chrome; AuctionGate blokuje start bundled Chromium
# BROWSER_EXECUTABLE_PATH=             # opcjonalnie pełna ścieżka, jeśli channel=chrome nie wystarczy
# DISABLED_EXTENSIONS=                 # np. auctiongate, tylko awaryjnie
# USE_MOCK_DATA=false
# AI_ANALYSIS_MODE=auto                  # auto | anthropic | local
# Uwaga: pełny AuctionGate ładuje się poprawnie w Google Chrome. Bundled Chromium
# potrafi zawiesić start na service workerze tego rozszerzenia.
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
