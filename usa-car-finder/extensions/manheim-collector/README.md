# Manheim collector

Rozszerzenie, które przekazuje odpowiedzi wyszukiwarki Manheim do lokalnego
backendu USA Car Finder.

## Dlaczego w ogóle istnieje

Sesję Manheima utrzymuje wtyczka BidWise przez `chrome.debugger`, a Chrome
dopuszcza **jednego** klienta debuggera na kartę. Zmierzone na tej instalacji:

```
FAZA 1 (bez podpięcia, 20 s):                    karta żyje
FAZA 2 (podpięty Playwright, zero interakcji):   karta znika w ciągu 5 s
```

Playwright/CDP wypycha wtyczkę ze slotu, ta traci wstrzykiwanie autoryzacji
i zamyka kartę. Do tego Chrome ≥ 137 nie ładuje rozszerzeń z `--load-extension`,
a BidWise wczytana jako unpacked wyłącza sama siebie (`disable_reasons=1`).

Kolektor omija to wszystkie: działa jako content script w kontekście strony,
**nie dotyka `chrome.debugger`**, więc niczego wtyczce nie odbiera.

## Instalacja (raz)

1. W oknie Chrome uruchomionym przez `scripts/manheim_chrome_debug.sh` wejdź na
   `chrome://extensions`.
2. Włącz **Developer mode** (prawy górny róg).
3. **Load unpacked** → wskaż katalog `extensions/manheim-collector`.
4. Otwórz opcje rozszerzenia i ustaw:
   - adres backendu (domyślnie `http://127.0.0.1:8000`),
   - token — `MANHEIM_INGEST_TOKEN` albo `SCRAPER_API_TOKEN` z `.env`
     (gdy oba puste, endpoint działa bez autoryzacji, jak reszta lokalnie).

Ładowanie unpacked przez UI działa normalnie — usunięto tylko flagę
`--load-extension` z linii poleceń.

## Jak działa

| plik | świat | rola |
| --- | --- | --- |
| `page-hook.js` | MAIN | podmienia `fetch`/`XMLHttpRequest`, kopiuje odpowiedzi, zapamiętuje szablony żądań i **powtarza wyszukiwanie na zlecenie** |
| `bridge.js` | ISOLATED | jedyne miejsce widzące i `window`, i `chrome.runtime`; przenosi w obie strony |
| `background.js` | service worker | wysyła paczki na `/api/manheim/ingest` i co ~5 s pyta `/api/manheim/next-job` |

### Wyszukiwanie na zlecenie

Backend nie może odpytać Manheima sam, więc kierunek jest odwrócony: zostawia
zadanie, rozszerzenie je odbiera i wykonuje w kontekście zalogowanej strony.

```
źródło manheim → POST job {keyword}      (api/manheim_jobs.py)
rozszerzenie   → GET  /api/manheim/next-job
strona         → getSearches {keyword}        → {"id": …}
strona         → getExecuteSearchId {searchId} → wyniki (gzip w base64)
rozszerzenie   → POST /api/manheim/ingest {jobId, captures}
```

Szablony obu żądań pochodzą z ruchu samej aplikacji, więc **raz** trzeba
wyszukać ręcznie — potem trafiają do `chrome.storage` i przeżywają zarówno
przeładowanie karty, jak i restart przeglądarki. Bez tego każdy restart
serwera wymagałby ręcznej interwencji, a usługa ma wstawać sama.

Gdy szablonu nie ma (pierwsze uruchomienie profilu) albo nagłówki autoryzacji
wygasły, zlecenie kończy się czytelnym błędem, a źródło sięga po to, co
kolektor zebrał wcześniej.

Hook musi być w świecie MAIN, bo tylko tam widać wywołania samej aplikacji —
świat izolowany ma własny `window` i tych żądań nie zobaczy.

Backend trzyma rekordy z TTL (`MANHEIM_INGEST_TTL_MINUTES`, domyślnie 30 min)
i scala je po VIN-ie: SPA rozbija pojazd na osobne zapytania (opis pojazdu
osobno, status licytacji z `highBid`/`endTime` osobno).

## Po przeładowaniu rozszerzenia — przeładuj też kartę

Chrome wyrzuca content scripty z otwartych kart w chwili przeładowania
rozszerzenia. Objaw: zlecenie wraca z `Receiving end does not exist`. Sam
restart przeglądarki tego nie wymaga (karta ładuje się od nowa), ale klikając
↻ na kafelku w `chrome://extensions` trzeba potem odświeżyć kartę Manheima.

Uwaga na service workera: przy podbiciu wersji potrafi jeszcze przez chwilę
chodzić na starym kodzie, mimo że `chrome://extensions` pokazuje już nową.
Objawia się to niespójnością — content script zachowuje się po nowemu, worker
po staremu. Ratuje przeładowanie kafelka.

## Sprawdzenie

```bash
curl -s http://127.0.0.1:8000/api/manheim/status | python3 -m json.tool
```

Po zrobieniu wyszukiwania na Manheimie liczba `vehicles` powinna urosnąć.
Surowe paczki lądują w `data/manheim_ingest/` (`MANHEIM_INGEST_KEEP_RAW`,
domyślnie ostatnie 20) — służą do diagnostyki kształtu API, nie do produkcji.

## Zakres

Rozszerzenie **tylko czyta** ruch, który strona i tak wykonuje. Niczego nie
klika, nie licytuje i nie wysyła żądań do Manheima we własnym imieniu.
