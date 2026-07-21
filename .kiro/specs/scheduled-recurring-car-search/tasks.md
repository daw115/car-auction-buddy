# Implementation Plan: Scheduled Recurring Car Search

## Overview

Plan wdraża funkcję kolejno w trzech izolowanych strumieniach: **A)** Ubuntu FastAPI w osobnym, nieprodukcyjnym worktree, **B)** canonical Lovable GUI `daw115/car-auction-buddy-096c3bf9`, **C)** walidacja kontraktu, bezpieczeństwa i E2E. Każdy liść DAG-u jest w osobnej fali, dzięki czemu `spec-task-execution` wykonuje zadania ściśle po kolei. Plan obejmuje wyłącznie kod i testy; nie autoryzuje commitów, pushy, merge'y ani żadnych działań produkcyjnych.

## Tasks

### A. Ubuntu backend — isolated worktree, persistence, API and worker

- [x] 1. Utrwalić kontrakt i izolację backendu
  - [x] 1.1 Dodać wersjonowane fixture'y kontraktu i kodowe guardy izolowanego worktree
    - W osobnym worktree utworzonym z dokładnie potwierdzonego wdrożonego release/commitu dodać fixture'y JSON dla requestów, odpowiedzi, błędów, capability, historii i kryteriów oraz testowy manifest wersji kontraktu.
    - Docelowy obszar: istniejący backendowy katalog fixture'ów/testów kontraktowych, ustalony po odczycie struktury worktree; kod aplikacji tylko w potwierdzonych obszarach `api/main.py`, `api/watch_queue_db.py`, `api/client_database.py` lub nowych modułach obok nich.
    - Dodać guard testowy odrzucający produkcyjną ścieżkę SQLite i aktywny checkout; nie odczytywać ani nie modyfikować zawartości produkcyjnego `watch_queue.db` lub bazy Search_Record.
    - _Requirements: 5.1, 6.1, 7.3, 9.4, 11.3_

  - [x]\* 1.2 Dodać legacy golden tests przed zmianami funkcjonalnymi
    - Scharakteryzować istniejące `POST/GET/DELETE /api/queue`, retry-until-found, recurring prototype, active-list, delete, interval, Telegram i współdzielony semaphore.
    - Dowieść, że legacy rows pozostają `schedule_kind IS NULL`, nie trafiają do native list/limitu i nie są migrowane ani reinterpretowane.
    - Docelowy obszar: istniejące backendowe testy kolejki/API w izolowanym worktree; bez zmian w aktywnym Ubuntu checkout.
    - _Requirements: 3.3, 7.4, 8.1, 9.4, 10.1_

- [ ] 2. Zaimplementować strict schemas, konfigurację i addytywną migrację
  - [x] 2.1 Dodać Pythonowe modele domenowe i API dla scheduled search
    - Zaimplementować strict request/response/error models dla CRUD, toggle, list, execution history, timestamps, capability i immutable attribution; odrzucać unknown keys oraz client-controlled owner/actor/status/counters/IDs/`searched_by`.
    - Normalizować wyłącznie jawne defaulty (`sources`, notifications off), bez clampowania `interval_hours`, `max_results` lub unsupported sources.
    - Docelowy obszar: nowe/potwierdzone moduły modeli pod `api/` i istniejąca konfiguracja backendu.
    - _Requirements: 1.1, 1.2, 2.1, 2.3, 5.1, 5.2, 7.3, 10.5, 11.3_
  - [x] 2.2 Zaimplementować addytywny, idempotentny migration runner na fixture databases
    - Rozszerzyć kod migracji `api/watch_queue_db.py` o nullable/default-safe kolumny native schedule, indeksy i ledger executions/attempts/notifications, ze strukturalnym version check i transakcyjną powtarzalnością.
    - Nie backfillować, nie reclassify, nie przepisywać i nie drukować legacy rows. Kod migracji ma działać wyłącznie na temp/fixture/kopii strukturalnej w tej fazie.
    - Dla unikalności Search_Record `job_id` najpierw wykryć strukturę fixture/staging schema i użyć dopiero potwierdzonych nazw tabeli/kolumny; nie zgadywać nazw produkcyjnego schematu i nie otwierać produkcyjnego SQLite.
    - _Requirements: 3.3, 7.4, 8.1, 11.3_

  - [x]\* 2.3 Napisać property test strict validation i atomic rejection
    - **Property 1: Strict validation, atomic rejection and precedence**
    - Użyć Hypothesis (`max_examples=100`) z boundaries, bool-vs-int, fractional, missing, unknown, Unicode, unsupported sources i równoczesnym naruszeniem limitu; persistence ma pozostać bez zmian, a walidacja ma poprzedzać limit.
    - **Validates: Requirements 1.2, 1.5, 2.3, 5.1, 5.2**

  - [x]\* 2.4 Napisać property test dokładnej domeny konfiguracji limitu
    - **Property 12: Limit configuration has an exact domain**
    - Użyć Hypothesis (`max_examples=100`) dla absent, poprawnych integerów i malformed explicit values; absent daje 20, invalid explicit value wyłącza capability i worker bez coercion/default fallback.
    - **Validates: Requirements 8.2, 8.3**

  - [x]\* 2.5 Dodać testy addytywnej migracji i kompatybilności schematu
    - Uruchamiać migrację na empty, legacy-only, partially migrated i current temp SQLite; sprawdzić DDL, constraints, repeatability, transactional rollback i zachowanie legacy fixture rows.
    - Dodać strukturalny fixture record store potwierdzający unique non-null job ID oraz `insert-or-read-existing`; test ma failować, jeśli nazwy/constraint nie zostały potwierdzone.
    - Docelowy obszar: backendowe testy migracji/repository i fixture'y z 1.1; nigdy produkcyjna ścieżka DB.
    - _Requirements: 3.3, 7.4, 8.1, 11.3_

- [ ] 3. Zaimplementować repository i management service
  - [x] 3.1 Dodać native CRUD, toggle, detail i ordered-list do repository
    - W `api/watch_queue_db.py` zaimplementować create, strict atomic patch z optimistic version, same-state no-op, soft delete, global detail/list, active counts i stabilne sortowanie `next_run_at`/ID.
    - Create i disabled→enabled wykonać w jednym `BEGIN IMMEDIATE`; native queries filtrują `scheduled_recurring_v1`, legacy queries jawnie `schedule_kind IS NULL`.
    - _Requirements: 1.1, 1.3, 1.4, 2.1, 2.2, 2.4, 2.5, 3.1, 3.2, 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 8.1, 8.5_

  - [ ] 3.2 Dodać management service z trusted owner i stabilnymi błędami
    - Walidować przed transakcją limitu, wyprowadzać immutable owner wyłącznie z trusted actor, stosować exact limit policy i mapować outcomes na sanitized versioned DTO/error envelopes.
    - Pozwolić wszystkim autoryzowanym operatorom zarządzać globalną listą, zachowując pierwotnego ownera i zapisując mutating actor osobno.
    - Docelowy obszar: nowy/potwierdzony service module pod `api/` oraz repository z 3.1.
    - _Requirements: 1.1, 1.4, 1.5, 2.1, 2.2, 2.3, 4.4, 4.5, 5.2, 6.1, 8.1, 8.4, 8.5, 11.3_

  - [ ]\* 3.3 Napisać property test poprawnego utworzenia
    - **Property 2: Valid creation initializes trusted state**
    - Hypothesis (`max_examples=100`) ma sprawdzić canonical criteria, enabled, session-derived immutable owner, dokładne `created_at + interval_hours` i notifications off przy braku pola.
    - **Validates: Requirements 1.1, 1.3, 10.5**

  - [ ]\* 3.4 Napisać property test per-owner active limit
    - **Property 3: Per-owner active limit is invariant**
    - Generować command sequences create/enable/disable/delete/limit-change dla wielu ownerów; count-increasing success nie może przekroczyć limitu, rejection jest atomic, a obniżenie limitu nie wyłącza istniejących rows.
    - **Validates: Requirements 1.4, 4.4, 8.1, 8.5**
  - [ ]\* 3.5 Napisać property test edit round-trip i czasu
    - **Property 4: Edit round-trip and time recalculation**
    - Generować non-empty patches dla enabled/disabled; submitted fields round-trip, omitted fields pozostają, a tylko interval edit ustawia termin od edit time.
    - **Validates: Requirements 2.1, 2.4, 2.5**

  - [ ]\* 3.6 Napisać property test idempotentnego delete
    - **Property 5: Delete is idempotent and terminal for planning**
    - Generować existing/missing/repeated IDs; delete zawsze kończy tym samym publicznym stanem i blokuje detail, claim oraz nowy termin.
    - **Validates: Requirements 3.1, 3.2**

  - [ ]\* 3.7 Napisać property test pełnej tabeli toggle
    - **Property 6: Toggle follows the complete transition table**
    - Generować stany, owner counts, actors i clocks; dowieść reguł disable/enable oraz pełnego no-op dla same-state bez zmiany version/timestamps/next run/config.
    - **Validates: Requirements 4.1, 4.2, 4.3**

  - [ ]\* 3.8 Napisać property test globalnej listy
    - **Property 7: Global listing is complete and ordered**
    - Generować multi-owner native/legacy/deleted collections; zwracać każdy non-deleted native schedule raz, komplet pól i stabilny next-run/null/ID order.
    - **Validates: Requirements 6.1**

  - [ ]\* 3.9 Dodać targeted repository i real-SQLite concurrency tests
    - Pokryć missing edit/toggle bez write, exact-limit count/limit, same-state no-op, lowered limit oraz race create/enable/edit/delete na wielu połączeniach do temp SQLite.
    - Sprawdzić bounded busy/conflict errors, brak lost updates i count native enabled nigdy ponad limit.
    - _Requirements: 1.4, 2.2, 4.4, 4.5, 8.1, 8.4, 8.5_

- [ ] 4. Udostępnić API, capability, readiness i OpenAPI
  - [ ] 4.1 Dodać FastAPI routes i trusted actor boundary
    - W `api/main.py` i potwierdzonych router/service modules dodać `/api/queue/schedules` CRUD/state/detail/history z zaprojektowanymi metodami/statusami.
    - Wymagać service-authenticated `X-Site-User`, sprawdzić allowlist przed body validation/repository i nigdy nie przyjmować browser-controlled attribution.
    - Zachować legacy `/api/queue` bez zmian.
    - _Requirements: 1.2, 2.2, 3.2, 4.5, 5.2, 6.1, 7.3, 8.4, 11.1, 11.2, 11.3_

  - [ ] 4.2 Zaimplementować versioned capability i readiness gates
    - Publikować `scheduled_searches_v1` wyłącznie przy zgodnym criteria contract, poprawnym limit config, gotowym repository/record uniqueness oraz wymaganych flagach; worker flag ma pozostać domyślnie off.
    - Degradować readiness i zatrzymywać claims przy invalid config/schema/heartbeat zamiast clamp, fallbacku lub drugiego schedulera; utrzymać bind contract `127.0.0.1:8000` w konfiguracji/testach release.
    - Docelowy obszar: istniejące backend capability/readiness/config modules i `api/main.py`.
    - _Requirements: 5.1, 7.1, 8.2, 8.3, 9.1, 9.2, 9.4_

  - [ ]\* 4.3 Dodać exact OpenAPI/capability contract tests
    - Sprawdzić paths, methods, status codes, strict schemas, pagination, errors, capability/readiness, criteria version, `max_results=100`, trzy źródła i brak clampowania.
    - Porównać z fixture'ami 1.1 i zachować legacy OpenAPI golden tests; nowe routes pozostają addytywne.
    - _Requirements: 1.2, 2.2, 2.3, 3.2, 4.5, 5.2, 6.1, 7.3, 8.4, 9.1, 9.3, 11.3_

  - [ ]\* 4.4 Dodać targeted API authorization i secret-safety tests
    - Pokryć malformed/empty patch, 404, 409, idempotent missing delete, exact owner, invalid actor przed validation/repository i immutable owner przy mutacji przez innego operatora.
    - Wstrzykiwać secret-like canaries w upstream failures; response/log diagnostics nie mogą ujawnić tokenów, headers, URL, SQL/path, raw body ani Telegram identifiers.
    - _Requirements: 2.2, 3.2, 4.5, 8.4, 11.1, 11.2, 11.3_

- [ ] 5. Zaimplementować ledger, lease, idempotency i Search_Record integration
  - [ ] 5.1 Dodać idempotentny adapter Search_Record na potwierdzonym fixture schema
    - Po strukturalnym discovery fixture/staging schema zaimplementować unique non-null job-ID migration oraz `insert-or-read-existing` używając wyłącznie potwierdzonych nazw tabeli/kolumny.
    - Używać deterministic `job_id = schedule:{execution_id}`; capability pozostaje off, jeśli constraint nie jest dowiedziony. Nie czytać danych ani schematu produkcyjnego SQLite w tej fazie.
    - Docelowy obszar: potwierdzony writer/repository Search_Record pod `api/` i addytywny migration module; bez zgadywania nazw backendowego schematu.
    - _Requirements: 3.3, 3.4, 7.2, 7.4, 11.3_

  - [ ] 5.2 Dodać execution ledger, attempts, claim, lease i fenced finalizers
    - W `api/watch_queue_db.py` zaimplementować atomic due claim, unique `(schedule_id, scheduled_for)`, immutable snapshots, lease takeover, heartbeat CAS token+generation, attempt logging, success/failure finalization i cursor history.
    - Success wymaga jednego record także dla zero results i inkrementuje raz; failure nie tworzy record i zachowuje success counters; deleted schedule nie dostaje kolejnego terminu.
    - _Requirements: 3.1, 3.3, 3.4, 7.1, 7.2, 7.3, 7.4, 7.5, 9.2_

  - [ ] 5.3 Zaimplementować native scheduled-execution adapter
    - Użyć istniejącego local search pipeline i shared semaphore, trusted `searched_by`, stabilnych execution/job/idempotency IDs, heartbeat i klasyfikacji retryable/terminal.
    - Maksymalnie 3 próby search z 0/30/120 s i jitter ±20%; po sukcesie search ponawiać tylko lookup/finalization, nie scraping.
    - Ustawić `suppress_completion_notify=true`, `persist_failure_record=false`; scheduled failure ma być pomijany przez terminal backfill bez zmiany legacy behavior.
    - Docelowy obszar: istniejący worker/search runner pod `api/` oraz nowy adjacent adapter po potwierdzeniu layoutu.
    - _Requirements: 3.4, 7.1, 7.2, 7.4, 7.5, 9.2, 10.3_

  - [ ] 5.4 Wpiąć native dispatch do istniejącego lifespan scheduler hosta
    - Rozdzielać native rows do nowego adaptera, a `schedule_kind IS NULL` do niezmienionego legacy handlera; oba używają tego samego `SEARCH_MAX_CONCURRENT` semaphore.
    - Odzyskiwać expired leases po restarcie, nie dopuszczać overlap dla due slot i pozwolić claimed execution dokończyć snapshot po edit/disable/delete.
    - Nie dodawać Cloudflare/pg_cron/GitHub/public-hook scheduler fallbacku.
    - _Requirements: 3.1, 3.4, 4.1, 7.1, 8.1, 9.2, 9.4_

  - [ ] 5.5 Dokończyć history i record-link integration
    - Zwracać newest-first sanitized execution DTOs także po soft delete oraz linkować tylko unique successful records danego schedule.
    - Nie modyfikować ani nie usuwać wcześniejszych Search_Record; running delete ma zachować finalny record i history.
    - Docelowy obszar: repository/service/routes z 3–5 oraz istniejący records lookup adapter.
    - _Requirements: 3.3, 3.4, 7.3, 11.3_

  - [ ]\* 5.6 Napisać property test due selection
    - **Property 8: Due selection is sound and complete**
    - Hypothesis (`max_examples=100`) generuje status/deletion/time/lease/in-flight sets; claim zwraca wszystkie i tylko eligible native schedules z exact immutable snapshots.
    - **Validates: Requirements 7.1**

  - [ ]\* 5.7 Napisać property test exactly-once success
    - **Property 9: Successful finalization has exactly-once effects**
    - Generować result counts ≥0, times i repeated/reordered finalizers; dowieść jednego ledger terminal, record link, counter increment, exact metadata, cleared error i fixed-delay next run.
    - **Validates: Requirements 7.2, 7.4**
  - [ ]\* 5.8 Napisać property test exclusive record filtering
    - **Property 10: Execution-to-record filtering is exclusive**
    - Generować cross-schedule histories z success/failure/deleted i duplicate-looking records; history jednego schedule pokazuje wszystkie i tylko jego unique successful links.
    - **Validates: Requirements 7.3**

  - [ ]\* 5.9 Napisać property test terminal failure
    - **Property 11: Terminal failure preserves schedule intent**
    - Generować retryable/non-retryable/unavailable/exhausted outcomes; failure ma być sanitized, fixed-delay, enabled/non-deleted, bez zmiany success counters/result i bez Search_Record.
    - **Validates: Requirements 7.5, 9.2**

  - [ ]\* 5.10 Dodać worker lifecycle, recovery i Search_Record integration tests
    - Pokryć zero/positive success, retry exhaustion, unavailable capability, restart takeover, stale fencing, crash po record insert przed ledger finalize, edit/disable/delete during run i failure-backfill suppression.
    - Fake runner ma potwierdzić shared semaphore, stable job/idempotency, brak duplicate scrape/insert/finalize i brak next run po delete.
    - _Requirements: 3.1, 3.3, 3.4, 4.1, 7.1, 7.2, 7.4, 7.5, 9.2_

  - [ ]\* 5.11 Dodać multi-worker claim/finalizer concurrency tests
    - Ścigać dwa worker instances na temp SQLite przez due claims, lease expiry, heartbeat i finalize; tylko jeden execution identity/valid lease/record/counter effect na slot.
    - Sprawdzić recovery tego samego execution ID i deterministic job ID oraz odrzucenie starego generation.
    - _Requirements: 7.1, 7.2, 7.4, 8.1_

- [ ] 6. Zaimplementować bounded notifications
  - [ ] 6.1 Dodać idempotentny global Telegram notification adapter
    - Snapshotować opt-in, wysyłać jeden logiczny message ze wszystkimi ofertami tylko po successful positive-result execution, z unique `(execution_id, channel)` i co najwyżej jednym retry po 30 s.
    - Disabled/zero result pozostają silent; notification failure zmienia tylko diagnostics, nigdy execution/record success.
    - Docelowy obszar: istniejący Telegram integration i nowy adjacent schedule adapter/ledger repository.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ]\* 6.2 Napisać property test bounded notification policy
    - **Property 14: Notification policy is bounded and independent**
    - Hypothesis (`max_examples=100`) generuje results, opt-in, duplicate finalization i notifier outcomes; zero/one logical broadcast, all offers, stable key, max 2 attempts i success isolation.
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4**

  - [ ]\* 6.3 Dodać notification unit i worker integration tests
    - Fake Telegram pokrywa zero/positive, duplicate offers across executions, duplicate delivery, retry/exhaustion, sanitized logs oraz niezmienione legacy Telegram golden behavior; bez outbound network.
    - _Requirements: 7.4, 10.1, 10.2, 10.3, 10.4_

- [ ] 7. Backend checkpoint — Ensure all tests pass
  - Ensure all Ubuntu unit, PBT, migration, repository, concurrency, API, OpenAPI, capability/readiness, worker, notification, security and legacy golden tests pass; ask the user if questions arise.
  - Używać wyłącznie izolowanego worktree, temp DB i fixture'ów; nie dotykać aktywnego checkoutu ani produkcyjnego SQLite.

### B. Canonical Lovable GUI — `daw115/car-auction-buddy-096c3bf9`

- [ ] 8. Zaimplementować canonical server-only transport i BFF contract
  - [ ] 8.1 Rozszerzyć canonical `src/lib/backend-transport.server.ts`
    - Dodać server-only `actorSiteUser`, allowlist `SITE_USERS` i `X-Site-User` dla obu wybranych transportów; partial Ubuntu config ma failować przed fetch.
    - Nie replayować mutation, nie wykonywać runtime fallbacku i nie omijać selector. Przed edycją sprawdzić working tree i zachować wszystkie istniejące niezacommitowane realtime/rerun/transport zmiany bez reset/clean/stash/mass-format.
    - Lokalny starszy `src/server/backend-transport.server.ts` jest wyłącznie referencją; nie kopiować do niego canonical rollout.
    - _Requirements: 9.1, 9.4, 11.2, 11.3_
  - [ ] 8.2 Dodać canonical shared schemas i public types
    - W `src/lib/` dodać strict TypeScript/Zod schemas dla requests, schedule, limits, errors, executions, history cursors i capability; mutable input nie może zawierać owner/actor/status/counters/secrets.
    - Zakodować integer 1–168, daily=24, strict criteria bez `searched_by`, exact owner i allowlisted sanitized errors.
    - _Requirements: 1.2, 2.3, 5.1, 5.2, 5.3, 6.1, 6.2, 7.3, 8.4, 11.3_

  - [ ] 8.3 Dodać canonical `src/lib/scheduled-searches.server.ts`
    - Zaimplementować create/update/toggle/delete/list/detail/history wyłącznie przez `backendRequest`, z session actor, strict response parsing i sanitized public error mapping.
    - Nie czytać `UBUNTU_*`, `CF_ACCESS_*`, `API_BASE_URL`, `SCRAPER_*`, nie używać direct fetch, old `/api/queue` ani lokalnego `src/server/scraper-queue.server.ts`; missing capability/route to deployment error bez fallbacku.
    - _Requirements: 1.1, 2.1, 3.1, 3.2, 4.1, 4.2, 6.1, 7.3, 8.4, 9.1, 9.4, 9.5, 11.3_

  - [ ]\* 8.4 Napisać property test unified fail-closed transport
    - **Property 13: Unified transport fails closed**
    - fast-check/Vitest (`numRuns:100`) generuje wszystkie subsets czterech Ubuntu vars i outcomes; proper subset nie robi fetch/write, complete wybiera Ubuntu, empty wybiera legacy z unavailable v1, bez replay/fallback.
    - **Validates: Requirements 9.1, 9.4**

  - [ ]\* 8.5 Napisać property test public secret non-disclosure
    - **Property 15: Public boundaries never disclose secrets**
    - fast-check/Vitest (`numRuns:100`) generuje nested secret-like keys, body, URLs, headers, credentials, SQL/path i canaries; public DTO/errors zawierają tylko allowlisted fields i zero canaries.
    - **Validates: Requirements 11.3**

  - [ ]\* 8.6 Dodać canonical transport/server-contract unit tests
    - Sprawdzić actor headers, exact route/method/body/cursor, response validation, stable errors, capability mismatch, partial config, no direct env/fetch, no old queue fallback i brak mutation replay.
    - Docelowy obszar: istniejące canonical test directories dla `src/lib/*.server.ts`; nie zmieniać lokalnych referencyjnych `src/server/*.server.ts`.
    - _Requirements: 2.2, 3.2, 4.5, 7.3, 8.4, 9.1, 9.4, 9.5, 11.3_

- [ ] 9. Dodać authenticated canonical server functions
  - [ ] 9.1 Utworzyć `src/functions/scheduled-searches.functions.ts`
    - Zaimplementować siedem server functions z `siteSessionMiddleware` przed każdym validator; jedynym actor source jest `context.siteUser`, przekazywany do `src/lib/scheduled-searches.server.ts`.
    - Unauthorized ma poprzedzać validation/backend; zwracać wyłącznie publiczne validated DTO/error unions.
    - _Requirements: 1.1, 2.1, 3.1, 4.1, 6.1, 7.3, 11.1, 11.2, 11.3_

  - [ ]\* 9.2 Rozszerzyć `siteSessionMiddleware` inventory/import tests
    - Dowieść ochrony dokładnie raz dla create/edit/delete/toggle/list/detail/history oraz braku unprotected alias/export do browser bundle.
    - _Requirements: 11.1, 11.2_

  - [ ]\* 9.3 Dodać authorization-order i actor-spoofing tests
    - Użyć malformed unauthenticated payloads i injected owner/actor headers; authorization wygrywa, validator/adapter/fetch spies są untouched, valid session przekazuje exact `session.sub`.
    - _Requirements: 11.1, 11.2, 11.3_

  - [ ]\* 9.4 Dodać BFF contract integration tests
    - Przetestować wszystkie functions z mock sessions i oboma transport branches: optimistic version, idempotent delete, limit, capability unavailable, fail-closed i no runtime fallback.
    - _Requirements: 2.2, 3.2, 4.5, 8.4, 9.1, 9.4, 9.5, 11.1, 11.2, 11.3_

- [ ] 10. Zaimplementować canonical GUI list/dialog/detail/history
  - [ ] 10.1 Dodać query keys, queries i mutations
    - Dodać React Query integration dla capability, server-ordered global list, detail i cursor history oraz scoped optimistic updates, pending, invalidation i rollback.
    - Nie mieszać native schedules z legacy queue; capability missing jest deployment-unavailable.
    - Docelowy obszar: istniejąca canonical data/query layer ustalona po odczycie repo.
    - _Requirements: 2.5, 3.1, 4.1, 4.2, 6.1, 6.4, 7.3, 9.3, 9.5_

  - [ ] 10.2 Zbudować create/edit dialog na canonical criteria controls
    - Reuse istniejących kontrolek criteria, dodać strict integer interval i zawsze dostępne „Codziennie” wysyłające dokładnie 24, Telegram default off, field errors i active_count/limit.
    - Edit wysyła non-empty patch z expected version i zachowuje omitted values.
    - Docelowy obszar: potwierdzone canonical form/dialog components; nie modyfikować starszego lokalnego GUI.
    - _Requirements: 1.1, 1.2, 1.4, 2.1, 2.3, 5.2, 5.3, 5.4, 8.4, 10.5_

  - [ ] 10.3 Zbudować listę, stany i mutation controls
    - Renderować rozłączne loading, deployment-unavailable, fetch-error+retry, successful-empty+instructions i populated.
    - Pokazać pełny owner, criteria summary, enabled/disabled, next/last run, successful runs, last result count i niezależny last-error badge; dodać pending edit/toggle/delete oraz confirmation.
    - Docelowy obszar: potwierdzone canonical route/component directories.
    - _Requirements: 3.1, 4.1, 4.2, 6.1, 6.2, 6.3, 6.4, 8.4, 9.3, 9.5_

  - [ ] 10.4 Dodać canonical route i navigation entry
    - W istniejącym TanStack route/navigation layout wpiąć scheduled searches, owner/status filters, create/list controls i capability gate.
    - Nie naruszyć unrelated realtime/rerun UI; lokalne niezacommitowane `records-panel`, stream, route i rerun files pozostają referencyjne i nietknięte.
    - _Requirements: 1.1, 6.1, 6.3, 6.4, 9.5_

  - [ ] 10.5 Zbudować detail i paginowaną execution history
    - Pokazać immutable criteria/owner/config, status/attempts/sanitized errors i `/records?recordId=...` wyłącznie dla success; history działa także po soft delete.
    - Docelowy obszar: canonical route/detail components i query layer z 10.1.
    - _Requirements: 3.3, 3.4, 7.3, 9.3, 11.3_

  - [ ]\* 10.6 Dodać GUI rendering/accessibility unit tests
    - Pokryć daily=24, exact owner, empty/list error/row error/deployment unavailable, retry, controls, limit values, zero-result success, history links, labels, focus i keyboard.
    - _Requirements: 5.3, 5.4, 6.2, 6.3, 6.4, 7.3, 8.4, 9.3, 9.5_

  - [ ]\* 10.7 Dodać GUI mutation integration tests
    - Symulować create/edit/toggle/idempotent delete, optimistic updates, conflict/limit/backend errors, rollback/retry i concurrent actions; bez stale state i legacy mutation leaks.
    - _Requirements: 1.1, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 4.4, 6.4, 8.4, 9.1_

### C. Cross-contract, security, import guards and E2E validation

- [ ] 11. Zintegrować kontrakty i pełne automated gates
  - [ ]\* 11.1 Dodać consumer/provider cross-contract tests
    - Walidować te same versioned fixture'y 1.1 po stronie FastAPI i canonical TypeScript dla request/success/error/capability/cursor/owner/timestamp/zero-result/failure.
    - Failować na clamp, unknown-field stripping, enum drift, brakach pól oraz zmianie status/method/path; fixture'y są jedynym współdzielonym artefaktem, bez kopiowania backend implementation.
    - _Requirements: 1.2, 2.3, 5.1, 6.1, 7.2, 7.3, 7.5, 8.4, 9.1, 11.3_

  - [ ]\* 11.2 Dodać authenticated cross-stack contract integration tests
    - Przeprowadzić in-process/fake-network flow od `siteSessionMiddleware` przez canonical `src/lib/*.server.ts` do FastAPI fixture/provider dla CRUD/list/history/fail-closed/sanitized errors.
    - Dowieść exact server-derived actor, braku browser control nad secret/header i braku fallbacku do legacy `/api/queue`.
    - _Requirements: 1.1, 2.1, 3.2, 4.2, 6.1, 7.3, 9.1, 9.4, 11.1, 11.2, 11.3_
  - [ ]\* 11.3 Dodać security, server-only import i artifact guards
    - Rozszerzyć static checks: browser nie importuje `src/lib/*.server.ts`; scheduled manager nie używa direct fetch/backend env/old queue; local `src/server/*.server.ts` nie jest canonical targetem.
    - Skanować test build artifacts z syntetycznymi canaries, nigdy real secrets; dowieść braku bearerów, CF headers, DB paths i raw upstream values.
    - _Requirements: 9.4, 11.3_

  - [ ]\* 11.4 Dodać izolowane E2E/smoke tests
    - W testowym środowisku z fake clock/backend wykonać login dla każdego SITE_USERS, create/edit/toggle/list/detail/history/delete/repeated delete, limit, wszystkie UI states i history→record.
    - Sprawdzić readiness/capability, manual search/jobs/records i legacy queue golden behavior bez produkcyjnych sekretów, networku, interwału ani SQLite.
    - _Requirements: 1.1, 2.1, 3.1, 3.2, 4.1, 4.2, 6.1, 6.2, 6.3, 6.4, 7.3, 8.4, 9.1, 9.3, 9.5, 11.1_

  - [ ] 11.5 Wpiąć non-interactive quality gates do istniejącego CI
    - Zaktualizować tylko potrzebne test/CI scripts tak, by uruchamiały targeted Python pytest/Hypothesis/migration/repository/concurrency/OpenAPI/security/legacy golden oraz canonical Vitest/fast-check/Testing Library, TypeScript, lint, build i import guard.
    - Używać single-run flags, nie watch/server commands; zachować istniejące realtime/rerun commands, nie mass-formatować i nie przepisywać unrelated files.
    - Docelowy obszar: istniejące backend i canonical CI/test config files, po potwierdzeniu ich nazw w każdym repo.
    - _Requirements: 7.4, 8.1, 9.1, 9.4, 11.1, 11.3_

- [ ] 12. Final code checkpoint — Ensure all tests pass
  - Ensure all targeted backend and canonical GUI unit, 15 property, migration, repository, concurrency, API/OpenAPI, contract, worker, notification, security, middleware, import-guard, E2E, TypeScript, lint and build checks pass; ask the user if questions arise.
  - Potwierdzić, że legacy golden tests są green, diff ogranicza się do zamierzonych feature/test/CI files, a wszystkie wcześniejsze niezacommitowane realtime/rerun zmiany pozostały nienaruszone.
  - Potwierdzić brak zmian w aktywnym Ubuntu checkout, brak dostępu do danych produkcyjnego SQLite i brak commit/push/merge/deploy.

- [ ] 13. HARD STOP — osobna jawna zgoda przed każdym działaniem produkcyjnym
  - Po zadaniu 12 wykonanie **musi się zatrzymać**. Ukończenie tasks, „wdrażaj po kolei”, akceptacja designu ani brak odpowiedzi nie zezwalają na dalszy krok.
  - Poza tym planem pozostają i nie mogą być automatycznie wykonane: produkcyjna migracja, odczyt/modyfikacja danych SQLite, zmiana aktywnego checkoutu, systemd/env/drop-in, release symlink/switch, reload/restart `usacar-api.service`/watchdog/cloudflared, worker enable, zmiana transport ownership oraz GUI deploy.
  - Przed osobną zgodą przygotować dokładny, nazwany command set i artefakty dla konkretnego etapu: backend release/commit i osobno canonical GUI commit; read-only preflight aktywnego release/service/OpenAPI oraz bind `127.0.0.1:8000`; schema version/checksum bez odczytu row contents; pełny backup plików DB z weryfikacją restore; migration dry-run na kopii; env/systemd/release diff; downtime; abort criteria; rollback; postflight health/capability/worker-heartbeat/manual search/jobs/records/legacy queue/no-new-native-claims.
  - Backend i GUI są osobnymi approval/deployment events. Każda zmiana komend/release albo failed preflight wymaga ponownej jawnej zgody. Rollback: najpierw stop new claims, potem GUI mutations, potem release rollback; bez `DROP`, destructive backfill lub ręcznej edycji danych.

## Notes

- Zadania z `*` są opcjonalnymi zadaniami automated testing zgodnie z formatem spec; 15 properties ma dokładnie po jednym osobnym PBT z designu. Testy example/integration/OpenAPI/security/E2E uzupełniają, a nie zastępują PBT.
- DAG jest celowo całkowicie sekwencyjny: jedna leaf task na falę. Checkpointy 7, 12 i 13 są top-level i dlatego zgodnie z formatem nie występują w JSON; executor ma zatrzymać się na każdym checkpoint, a po 13 nie istnieje żadne zadanie wdrożeniowe.
- Backend: wyłącznie osobny nieprodukcyjny worktree z potwierdzonego release/commitu. Aktywny Ubuntu checkout, aktywny release i produkcyjne SQLite pozostają nietknięte; nie wolno czytać row contents ani zgadywać nazw schematu Search_Record.
- Canonical rollout: wyłącznie repo `daw115/car-auction-buddy-096c3bf9`; server-only kod trafia do `src/lib/*.server.ts`. Starszy lokalny `src/server/*.server.ts` służy tylko jako read-only reference i nie jest mieszany z rolloutem.
- Przed każdą canonical edycją sprawdzić stan working tree i wykonać surgical edit. Nie resetować, cleanować, stashować, nadpisywać ani mass-formatować istniejących niezacommitowanych realtime/rerun/transport zmian, w tym znanych lokalnych obszarów `records-panel`, scraper-log stream, index route, backend transport/tests i `src/lib/rerun-criteria.ts`.
- Nie planuje się commit, push ani merge. Zależność PBT może być dodana tylko, jeśli jej brakuje, w owning non-production repo, z dokładnie przypiętą wersją i właściwym lockfile.
- V1 nie dodaje secondary scheduler: bez `pg_cron`, `pg_net`, GitHub Actions, public tick hooks i Cloudflare scheduling.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["2.3"] },
    { "id": 5, "tasks": ["2.4"] },
    { "id": 6, "tasks": ["2.5"] },
    { "id": 7, "tasks": ["3.1"] },
    { "id": 8, "tasks": ["3.2"] },
    { "id": 9, "tasks": ["3.3"] },
    { "id": 10, "tasks": ["3.4"] },
    { "id": 11, "tasks": ["3.5"] },
    { "id": 12, "tasks": ["3.6"] },
    { "id": 13, "tasks": ["3.7"] },
    { "id": 14, "tasks": ["3.8"] },
    { "id": 15, "tasks": ["3.9"] },
    { "id": 16, "tasks": ["4.1"] },
    { "id": 17, "tasks": ["4.2"] },
    { "id": 18, "tasks": ["4.3"] },
    { "id": 19, "tasks": ["4.4"] },
    { "id": 20, "tasks": ["5.1"] },
    { "id": 21, "tasks": ["5.2"] },
    { "id": 22, "tasks": ["5.3"] },
    { "id": 23, "tasks": ["5.4"] },
    { "id": 24, "tasks": ["5.5"] },
    { "id": 25, "tasks": ["5.6"] },
    { "id": 26, "tasks": ["5.7"] },
    { "id": 27, "tasks": ["5.8"] },
    { "id": 28, "tasks": ["5.9"] },
    { "id": 29, "tasks": ["5.10"] },
    { "id": 30, "tasks": ["5.11"] },
    { "id": 31, "tasks": ["6.1"] },
    { "id": 32, "tasks": ["6.2"] },
    { "id": 33, "tasks": ["6.3"] },
    { "id": 34, "tasks": ["8.1"] },
    { "id": 35, "tasks": ["8.2"] },
    { "id": 36, "tasks": ["8.3"] },
    { "id": 37, "tasks": ["8.4"] },
    { "id": 38, "tasks": ["8.5"] },
    { "id": 39, "tasks": ["8.6"] },
    { "id": 40, "tasks": ["9.1"] },
    { "id": 41, "tasks": ["9.2"] },
    { "id": 42, "tasks": ["9.3"] },
    { "id": 43, "tasks": ["9.4"] },
    { "id": 44, "tasks": ["10.1"] },
    { "id": 45, "tasks": ["10.2"] },
    { "id": 46, "tasks": ["10.3"] },
    { "id": 47, "tasks": ["10.4"] },
    { "id": 48, "tasks": ["10.5"] },
    { "id": 49, "tasks": ["10.6"] },
    { "id": 50, "tasks": ["10.7"] },
    { "id": 51, "tasks": ["11.1"] },
    { "id": 52, "tasks": ["11.2"] },
    { "id": 53, "tasks": ["11.3"] },
    { "id": 54, "tasks": ["11.4"] },
    { "id": 55, "tasks": ["11.5"] }
  ]
}
```
