# Logika działania aplikacji

## Cel

Aplikacja ma obsłużyć zapytanie klienta o samochód z aukcji USA, pobrać realne dane z Copart i IAAI, odfiltrować oferty według kryteriów, wzbogacić je danymi z AutoHelperBot/AuctionGate, przeanalizować przez AI i wygenerować raport oraz HTML maila do klienta.

## Główne tryby pracy

1. Tryb testowy: `USE_MOCK_DATA=true` używa danych lokalnych, bez logowania i bez pobierania aukcji.
2. Tryb online: `USE_MOCK_DATA=false` uruchamia Playwright, loguje się przez zapisane sesje i pobiera aukcje z Copart/IAAI.
3. Tryb AI lokalny: `AI_ANALYSIS_MODE=local` wykonuje scoring bez API.
4. Tryb AI przez API: `AI_ANALYSIS_MODE=openai`, `anthropic` albo `auto` wysyła przygotowany pakiet danych do modelu.

## Wejście od klienta

Użytkownik podaje:

- markę, model i opcjonalnie generację/wersję,
- rocznik od/do,
- budżet maksymalny,
- preferowane paliwo, skrzynię, napęd i przebieg,
- okno zakończenia aukcji, np. od 12 godzin do 5 dni,
- wymaganie `seller_type=insurance`.

Zapytanie jest zapisywane w bazie klientów, aby można było wrócić do rekordu, raportów i historii wyszukiwań.

## Kolejność filtrowania aukcji

1. Najpierw ustawiany jest filtr daty aukcji i sortowanie od najbliższej aukcji do najpóźniejszej.
2. Z listy wyników aplikacja bierze pod uwagę tylko aukcje kończące się w zadanym oknie czasu.
3. Następnie odrzuca oferty, które na liście nie spełniają warunku `insurance`.
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

Aplikacja zapisuje jeden plik wejściowy dla AI z pełną listą kandydatów. Model ma:

- ocenić zgodność z kryteriami klienta,
- wskazać ryzyka zakupu i transportu,
- policzyć/opisać przewidywany koszt importu,
- porównać oferty między sobą,
- wybrać najlepsze samochody do raportu.

Domyślna selekcja TOP 5 bazuje na wyniku AI, ale wynik powstaje po wcześniejszym filtrowaniu technicznym: czas aukcji, seller insurance, damage, budżet i kompletność danych.

## Raport i mail

Po analizie aplikacja generuje:

- plik danych wejściowych dla AI,
- prompt użyty do analizy,
- JSON z odpowiedzią AI,
- raport klienta,
- HTML maila zgodny z `przyklady_maili_README.md`.

Raporty są zapisywane w katalogu artefaktów i widoczne z poziomu rekordu klienta w aplikacji.

## Zasady bezpieczeństwa

- Nie commitujemy `.env`, kluczy API, cookies, storage state, profili Chromium ani cache przeglądarki.
- Jeżeli Copart/IAAI pokazuje CAPTCHA/security check, aplikacja czeka na ręczne przejście lub korzysta z zapisanej zalogowanej sesji.
- Rozszerzenia są opcjonalne. Gdy są wyłączone, aplikacja nadal może pobierać dane bezpośrednio, a AutoHelperBot może być odpytywany przez zalogowaną sesję web.
