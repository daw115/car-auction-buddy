# Audyt sesji — usacar-api (2026-07-19)

Zapis diagnozy i zmian wykonanych na backendzie `usacar-api` (serwer WSL2,
`moneybitches.organof.org`) w ramach jednej ciągłej sesji roboczej.
Dokument opisuje wyłącznie backend (to repozytorium) — równoległa praca
nad frontendem (Lovable, `car-auction-buddy`) jest śledzona w osobnym
repozytorium platformy Lovable, poza tym gitem.

## 1. Punkt wyjścia: dlaczego raport dla brokera się nie generował

Diagnoza wykazała **awarię klucza API**, nie błąd w kodzie:
- `ANTHROPIC_API_KEY` używany przez proxy `api.oneprovider.dev` był nieważny
  (potwierdzone bezpośrednim testem: `401 INVALID_API_KEY`).
- Raporty klient+broker generowane są jednym wywołaniem LLM
  (`render_pair_hybrid`) — gdy ono pada, klient i tak dostaje zapasowy,
  bezpłatny raport szablonowy (Jinja2, bez AI), ale **broker nie miał
  żadnego fallbacku** — stąd wrażenie "nic się nie generuje dla brokera",
  mimo że część systemu (klient) pozornie działała.
- Ostatni skutecznie wygenerowany raport brokerski przed sesją: 27 maja
  (prawie 2 miesiące przestoju, z przerywanymi błędami: connection error,
  invalid key, 502 — provider `oneprovider.dev` był niestabilny od dawna).

**Fix natychmiastowy:** przełączenie `AI_ANALYSIS_MODE` i
`LLM_REPORTS_PROVIDER` na Gemini (bezpośrednie, darmowe API Google, klucz
w `.env` był ważny i nieużywany) — zweryfikowane end-to-end na realnych
danych z produkcji.

## 2. Rozszerzenie: Kiro CLI jako trzeci provider AI

Na życzenie: dodanie Kiro (`kiro-cli`, oficjalny tryb headless,
`KIRO_API_KEY`) jako alternatywy dla Gemini/Anthropic. Zbadane i odrzucone:
nieoficjalne proxy (`kiro-gateway` i podobne) — okazały się niepotrzebne,
bo `KIRO_API_KEY` to udokumentowany, pierwszoplanowy mechanizm auth Kiro
CLI, nie wymaga żadnego pośrednika.

Zaimplementowane we wszystkich 7 miejscach aplikacji korzystających z AI
(patrz commit `feat(ai): dodaj Kiro CLI...`): analiza/scoring lotów,
raporty klient+broker, parsowanie wiadomości klienta, legacy LLM raport,
normalizacja nazw modeli, agent ofert, wykrywanie uszkodzeń ramy
(to ostatnie na Gemini, nie Kiro — zadanie wizyjne, `kiro-cli` nie ma
potwierdzonego wejścia obrazkowego w headless mode).

Napotkany i naprawiony bug uboczny: Gemini w dwóch nowych integracjach
(frame_damage_vision, model_normalization) nie miał wyłączonego
"thinking mode" (`thinkingConfig.thinkingBudget=0`) — bez tego tryb
myślenia zjadał cały budżet tokenów, ucinając odpowiedź w połowie JSON-a.
Złapane na żywych testach przed wdrożeniem.

## 3. Architektura: dashboard-konfigurowalne ustawienia

Wybór providera/modelu AI i część filtrów scrapera były wcześniej
dostępne wyłącznie przez edycję `.env` na serwerze (SSH). Zbudowany nowy
magazyn ustawień (`api/settings_db.py`, SQLite key-value) + 4 pary
endpointów (`GET`/`PUT`) pozwalające sterować zachowaniem aplikacji z
zewnętrznego dashboardu, **bez restartu usługi**:

- `/api/settings/ai-providers` — provider per zadanie (5 zadań)
- `/api/settings/ai-models` — model per provider (dla Kiro: żywa lista
  z `kiro-cli --list-models`, nie zaszyta na sztywno)
- `/api/settings/pipeline-filters` — `seller_insurance_only`,
  `exclude_convertible` (ten drugi wcześniej w ogóle nie miał zmiennej
  konfiguracyjnej — był zaszyty na sztywno w kodzie scrapera)
- `/api/settings/default-criteria` — domyślne kryteria wyszukiwania

Każdy override ma pierwszeństwo przed `.env`, sprawdzany przy każdym
wywołaniu (lokalny SQLite, <1ms) — zmiana z dashboardu działa natychmiast.
Zweryfikowane empirycznie: przełączenie providera na Kiro z poziomu API
zadziałało na kolejnym wyszukiwaniu bez restartu procesu.

Przy okazji: kolejka ponownego sprawdzania (`/api/queue`) dostała tryb
`recurring` — cykliczne sprawdzanie bez końca (opcjonalnie zakotwiczone
do konkretnej godziny UTC), obok istniejącego trybu jednorazowego
"sprawdzaj do skutku i wyłącz się".

## 4. Bug produkcyjny: status `interrupted` przy restarcie usługi

Znaleziony podczas testowania batch-pollingu we frontendzie: restart
usługi (deploy) w trakcie aktywnego scrape'a dawał **niedeterministyczny**
wynik — czasem poprawny status `interrupted`, czasem mylące `done` z 0
lotami (wyglądające jak legalny pusty wynik wyszukiwania). Zależało od
dokładnego mikrosekundowego momentu, w którym `SIGTERM` przerywał
wykonanie Playwrighta.

Zweryfikowane empirycznie: 3 kontrolowane restarty usługi w trakcie
realnych, aktywnych scrape'ów (na żywej produkcji, za zgodą i przy
koordynacji z operatorem). Naprawione przez jawną detekcję
`TargetClosedError` (nowa klasa `ServiceInterruptedError` +
`jobs.mark_interrupted()`) — teraz deterministyczne, z czytelnym
komunikatem błędu w polu `error` joba. Dotyczy nie tylko testów: **każdy
przyszły deploy backendu w trakcie realnego wyszukiwania klienta** miałby
wcześniej ten sam problem.

## 5. Raport brokerski: przejrzystość filtrów i uzasadnienia decyzji

- Nowa sekcja "Powód decyzji" — natychmiast pod score/rekomendacją,
  zamiast zakopanej w środku dokumentu. Dodana do obu wariantów raportu
  (szablonowy i AI-hybrid — ten drugi wcześniej NIE miał żadnej sekcji
  kryteriów/filtrów).
- Lista filtrów pipeline (`_build_pipeline_rules`) przepisana z
  częściowo zaszytej na sztywno (z błędem etykietowania — "auction
  window" pokazywało rocznik zamiast realnego okna czasowego) na w pełni
  dynamiczną, respektującą te same override'y z dashboardu co scraper.
- Naprawiony drobny bug wyświetlania: puste pola pokazywały dosłowne
  "None" zamiast "—".

## 6. Znane, celowo nietknięte sprawy

- **`ANTHROPIC_API_KEY` (proxy `api.oneprovider.dev`) wciąż nieważny.**
  Gemini/Kiro są teraz providerami domyślnymi, więc to nie blokuje
  działania — ale mechanizm fallbacku do Anthropic (gdy Gemini/Kiro
  zawiodą) jest dziś bezużyteczny, dopóki klucz nie zostanie odnowiony
  albo `ANTHROPIC_BASE_URL` nie wróci na oficjalne API.
- **Bezpieczeństwo frontendu** (hardcoded master password, brak rate
  limitu logowania w `PasswordGate`) — znalezione i naprawione, ale w
  repozytorium Lovable, nie tutaj.
- **`data/`, `logs/`** — pozostawione poza gitem (runtime cache/dane),
  zgodnie z dotychczasową konwencją tego repo (brak wpisów w
  `.gitignore`, ale też nigdy nie były trackowane).
- **`test_ahb.py`, `test_parser.py`, `test_system_param.py`** — untracked
  pliki sprzed tej sesji, nietknięte (nie moja praca, nieznany kontekst).

## Commity tej sesji

1. `feat(ai)` — Kiro CLI jako provider (7 miejsc w kodzie)
2. `feat(settings)` — dashboard ustawień (4 pary endpointów, bez restartu)
3. `fix(jobs)` — deterministyczny status `interrupted`
4. `feat(broker-report)` — przejrzystość filtrów + "Powód decyzji"
