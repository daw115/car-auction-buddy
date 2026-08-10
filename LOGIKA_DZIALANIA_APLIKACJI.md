# Logika działania aplikacji

## Cel

Aplikacja ma obsłużyć zapytanie klienta o samochód z aukcji USA, pobrać realne dane z Copart i IAAI, odfiltrować oferty według kryteriów, wzbogacić je danymi z AutoHelperBot/AuctionGate, przeanalizować przez AI i wygenerować raport oraz HTML maila do klienta.

## Główne tryby pracy

1. Tryb testowy: `USE_MOCK_DATA=true` używa danych lokalnych, bez logowania i bez pobierania aukcji.
2. Tryb online: `USE_MOCK_DATA=false` uruchamia Playwright, loguje się przez zapisane sesje i pobiera aukcje z Copart/IAAI.
3. Tryb AI lokalny: `AI_ANALYSIS_MODE=local` wykonuje scoring bez API.
4. Tryb AI przez zewnętrzny model: `AI_ANALYSIS_MODE` przyjmuje `claude-code` (ustawienie produkcyjne w `.env` — Claude Code w trybie headless `claude -p`, uwierzytelnienie z sesji subskrypcji OAuth, BEZ klucza API; klucz z `.env` jest celowo usuwany ze środowiska podprocesu), a także `openai`, `anthropic`, `gemini`, `kiro` oraz `auto` (kolejno OpenAI → Anthropic → Gemini → Kiro → scoring lokalny). Provider da się nadpisać z dashboardu (`PUT /api/settings/ai-providers`) bez restartu usługi.

## Wejście od klienta

Użytkownik podaje:

- markę, model i opcjonalnie generację/wersję,
- rocznik od/do,
- budżet maksymalny,
- preferowane paliwo (`fuel_type` — filtr serwerowy Copart) i maksymalny przebieg (`max_odometer_mi`),
- okno zakończenia aukcji, np. od 12 godzin do 5 dni,
- budżet „pod klucz" w PLN (`budget_pln_from` / `budget_pln_to`) oraz formę rozliczenia (`settlement`: `private` albo `company`) — sufit ceny aukcyjnej liczy z tego `scoring/budget.py` osobno dla każdego stanu USA. Wymóg `seller_type=insurance` NIE jest parametrem klienta, tylko przełącznikiem pipeline'u (patrz „Kolejność filtrowania aukcji").

Zapytanie jest zapisywane w bazie klientów, aby można było wrócić do rekordu, raportów i historii wyszukiwań.

## Kolejność filtrowania aukcji

1. Najpierw ustawiany jest filtr daty aukcji i sortowanie od najbliższej aukcji do najpóźniejszej.
2. Z listy wyników aplikacja bierze pod uwagę tylko aukcje kończące się w zadanym oknie czasu.
3. Filtr sprzedawcy jest opcjonalny: włącza go `FILTER_SELLER_INSURANCE_ONLY=true` w `.env` albo przełącznik `seller_insurance_only` w dashboardzie. Domyślnie jest wyłączony, więc aplikacja NIE odrzuca ofert od dealerów. Domyślnie włączony jest natomiast filtr kabrioletów (`FILTER_EXCLUDE_CONVERTIBLE`, domyślnie `true`).
4. Kolejny filtr to typ uszkodzenia: priorytet mają mniejsze uszkodzenia, a flood/fire są traktowane jako mocny powód odrzucenia.
5. Dopiero po tych filtrach aplikacja otwiera szczegóły aukcji i zbiera pełne dane.

Jeżeli lista wyników nie zawiera żadnych aukcji zgodnych z czasem i seller type, aplikacja nie otwiera szczegółów bez potrzeby. Jeśli na pierwszej stronie nie ma wystarczających wyników, przechodzi na kolejne strony do limitu `SEARCH_MAX_PAGES`.

## Pobieranie danych

Dla każdej zakwalifikowanej aukcji aplikacja zbiera:

- dane podstawowe: lot, VIN jeśli dostępny, rok, marka, model, przebieg, lokalizacja, tytuł, silnik, skrzynia, napęd,
- dane aukcyjne: aktualna cena, buy now, data aukcji, źródło, URL,
- damage: primary/secondary damage, condition, keys, run and drive,
- seller type i seller name,
- dane dodatkowe z AutoHelperBot/AuctionGate, gdy sesja jest aktywna.

Sesje logowania są trzymane lokalnie w `playwright_profiles/*.json` oraz w profilu przeglądarki. Te pliki są ignorowane przez Git i nie mogą być commitowane.

## Analiza AI

Przed analizą działa pre-ranking heurystyczny: do modelu — i do zapisywanego pliku wejściowego `*_ai_input.json` — trafia tylko `AI_ANALYSIS_TOP_N` najbardziej obiecujących lotów (domyślnie 10), a nie pełna lista kandydatów ze scrape'u. Model ma:

- ocenić zgodność z kryteriami klienta,
- wskazać ryzyka zakupu i transportu,
- opisać, który czynnik z gotowego `unified_score` zadecydował o ocenie (kosztów model NIE liczy: `estimated_repair_usd` i `estimated_total_cost_usd` zostawia na 0, a wszystkie kwoty pochodzą z `pricing/import_calculator.py`),
- porównać oferty między sobą,
- wybrać najlepsze samochody do raportu.

Ocena 0–10 NIE pochodzi od modelu. Liczy ją deterministycznie `scoring/unified.py` (wagi bazowe: cena vs rynek 0.25, stan techniczny 0.20, tytuł i historia 0.15, przebieg vs rocznik 0.15, logistyka 0.10, wiarygodność oferty 0.10, dopasowanie do klienta 0.05), a wagi składowych, dla których brakuje danych, rozkładają się proporcjonalnie na resztę — brak sygnału nie obniża oceny. Model dostaje wynik gotowy w polu `unified_score` i tylko pisze uzasadnienie; jego własna liczba jest nadpisywana.

Progi rekomendacji: ≥ 7.5 → POLECAM, ≥ 5.0 → RYZYKO, poniżej → ODRZUĆ. Twarde dyskwalifikatory (zalanie/pożar, uszkodzenie konstrukcji, tytuł salvage przy wymaganym Clean, czerwone światło przy `risk="none"`) dają ocenę 0.0 i ODRZUĆ niezależnie od punktacji.

Budżet dyskwalifikatorem NIE jest. Cena ponad sufit daje osobny werdykt i rekomendację PONAD BUDŻET, a ocena liczy się normalnie — decyzję, czy zaproponować takie auto, podejmuje broker.

Do panelu trafia showcase: wszystkie POLECAM plus 2 najlepsze RYZYKO (`SHOWCASE_RYZYKO_LIMIT`), przycięty do `MAX_FINAL_RESULTS` (domyślnie 10). W pipelinie automatycznym klient dostaje 3–4 auta (`CLIENT_OFFERS_COUNT`, domyślnie 4).

## Raport i mail

Po analizie aplikacja generuje:

- plik danych wejściowych dla AI,
- prompt użyty do analizy,
- JSON z odpowiedzią AI,
- raport klienta,
- per-lot raporty HTML dla klienta i dla brokera (te powstają automatycznie po analizie).

HTML maila ofertowego NIE powstaje automatycznie — generuje go dopiero `POST /report/offer-email-html` dla lotów zatwierdzonych przez brokera w panelu (`included_in_report`), zgodnie ze strukturą z `przyklady_maili_README.md`.

Raporty są zapisywane w katalogu artefaktów i widoczne z poziomu rekordu klienta w aplikacji.

## Zasady bezpieczeństwa

- Nie commitujemy `.env`, kluczy API, cookies, storage state, profili Chromium ani cache przeglądarki.
- Jeżeli Copart/IAAI pokazuje CAPTCHA/security check, aplikacja czeka na ręczne przejście lub korzysta z zapisanej zalogowanej sesji.
- Rozszerzenia są opcjonalne. Gdy są wyłączone, aplikacja nadal może pobierać dane bezpośrednio, a AutoHelperBot może być odpytywany przez zalogowaną sesję web.
