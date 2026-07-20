# Ubuntu API Contract

Kontrakt między **Lovable BFF** (server functions + server routes) a **backendem FastAPI** działającym na Ubuntu/WSL2 pod `127.0.0.1:8000`, wystawionym publicznie przez **Cloudflare Access Tunnel**.

Lovable nie ma bezpośredniego dostępu do środowiska Ubuntu, więc żaden endpoint w tym dokumencie **nie jest oznaczony jako `verified-existing`** dopóki nie zostanie potwierdzony po stronie backendu. Domyślne statusy poniżej mają wymusić proces discovery.

## Statusy

| Status                         | Znaczenie                                                                                                             |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `verified-existing`            | Endpoint istnieje na Ubuntu, jego schema została potwierdzona przez zespół backendu. **Wymaga ludzkiej weryfikacji.** |
| `required-unverified`          | Endpoint jest wymagany przez GUI, prawdopodobnie istnieje, ale schema nie została potwierdzona.                       |
| `missing`                      | Wiadomo, że endpoint nie istnieje i musi zostać dodany na Ubuntu.                                                     |
| `blocked-by-backend-discovery` | Nie wiadomo, jak backend obecnie realizuje tę funkcję. Wymaga rozmowy z zespołem Ubuntu.                              |

## Wspólne konwencje

- **Bazowy URL**: wyłącznie `UBUNTU_API_BASE_URL` (server-only). Wymuszany HTTPS, bez credentials w URL, bez query/hash.
- **Nagłówki wysyłane z BFF na każdym żądaniu**:
  - `Authorization: Bearer <UBUNTU_API_BEARER_TOKEN>`
  - `CF-Access-Client-Id: <CF_ACCESS_CLIENT_ID>`
  - `CF-Access-Client-Secret: <CF_ACCESS_CLIENT_SECRET>`
  - `Accept: application/json`
  - `X-Request-Id: <uuid v4>` — do korelacji logów z Ubuntu.
- **Timeout**: domyślnie 15 s, health/probe 4 s.
- **Retry**: wyłącznie `GET`/`HEAD` przy błędach sieci, 502, 503, 504 — maksymalnie 1 retry, backoff ~250 ms.
- **Rozmiar odpowiedzi**: limit 10 MiB (Content-Length + streamed bytes).
- **Format błędu (proponowany dla Ubuntu)**:
  ```json
  { "error": { "code": "string", "message": "string", "request_id": "uuid" } }
  ```
  BFF **nie** zwraca body upstreamu klientowi — mapuje na sanitized error.

## Wymagane endpointy

### Auth (PasswordGate)

| Metoda   | Ścieżka                           | Cel                                                              | Idempotencja         | Uprawnienie              | Timeout | Status                         |
| -------- | --------------------------------- | ---------------------------------------------------------------- | -------------------- | ------------------------ | ------- | ------------------------------ |
| `POST`   | `/auth/login`                     | Zamiana `{ username, password }` na sesję.                       | Nie                  | Publiczny (rate-limited) | 8 s     | `blocked-by-backend-discovery` |
| `POST`   | `/auth/logout`                    | Unieważnienie bieżącej sesji.                                    | Tak                  | Sesja                    | 5 s     | `blocked-by-backend-discovery` |
| `GET`    | `/auth/session`                   | Aktualnie zalogowany użytkownik (`{ authenticated, username }`). | Tak                  | Sesja                    | 5 s     | `blocked-by-backend-discovery` |
| `POST`   | `/auth/users/{username}/password` | Reset hasła użytkownika (wymaga master password).                | Nie                  | Master                   | 8 s     | `blocked-by-backend-discovery` |
| `DELETE` | `/auth/users/{username}`          | Usunięcie profilu (wymaga master password).                      | Tak (2nd call = 404) | Master                   | 5 s     | `blocked-by-backend-discovery` |
| `GET`    | `/auth/users/{username}/exists`   | Czy dla użytkownika ustawione jest hasło.                        | Tak                  | Publiczny                | 3 s     | `blocked-by-backend-discovery` |

> **Uwaga**: obecnie hasła użytkowników GUI trzymane są w tabeli Supabase `site_user_passwords`. Migracja tych endpointów będzie wymagała, aby Ubuntu przejął rolę authoritative source. Bez powyższych endpointów PasswordGate **nie może** działać na Ubuntu.

### Health i konfiguracja

| Metoda | Ścieżka    | Cel                                                                                  | Idempotencja | Uprawnienie              | Timeout | Status                |
| ------ | ---------- | ------------------------------------------------------------------------------------ | ------------ | ------------------------ | ------- | --------------------- |
| `GET`  | `/health`  | Liveness/readiness FastAPI. Zwraca `{ status: "ok" \| "degraded", checks?: {...} }`. | Tak          | Publiczny (za CF Access) | 4 s     | `required-unverified` |
| `GET`  | `/config`  | Publicznie widoczna konfiguracja aplikacji (nie sekrety).                            | Tak          | Sesja                    | 5 s     | `required-unverified` |
| `GET`  | `/version` | `{ commit, buildTime, version }` do dev.logs.                                        | Tak          | Sesja                    | 3 s     | `required-unverified` |

### Records, cache i klienci

Wszystkie ścieżki `/api/records/*`, `/api/llm-cache/*`, `/api/html-cache/*`, `/api/model-normalizations/*`, `/api/feedback/*`, `/api/parse-client-message`, `/api/db/overview` oraz `/api/capabilities` zostały wykryte wyłącznie w kodzie proxy (`src/functions/backend.functions.ts`). Do czasu potwierdzenia przez zespół Ubuntu pozostają `required-unverified`.

| Metoda   | Ścieżka                                                | Cel                                            | Idempotencja           | Uprawnienie | Timeout | Status                         |
| -------- | ------------------------------------------------------ | ---------------------------------------------- | ---------------------- | ----------- | ------- | ------------------------------ |
| `GET`    | `/api/records`                                         | Lista rekordów wyszukiwań (paginacja, filtry). | Tak                    | Sesja       | 30 s    | `required-unverified`          |
| `GET`    | `/api/records/{id}`                                    | Szczegóły rekordu.                             | Tak                    | Sesja       | 30 s    | `required-unverified`          |
| `DELETE` | `/api/records/{id}`                                    | Usunięcie rekordu i artefaktów.                | Tak (200/204/404 OK)   | Sesja       | 30 s    | `required-unverified`          |
| `POST`   | `/api/records/{id}/regenerate-bundles?engine=…`        | Regeneracja raportów.                          | Nie                    | Sesja       | 60 s    | `required-unverified`          |
| `GET`    | `/api/records/{id}/feedback`                           | Lista feedbacku rekordu.                       | Tak                    | Sesja       | 30 s    | `required-unverified`          |
| `POST`   | `/api/records/{id}/feedback`                           | Zapis feedbacku dla lota.                      | Nie                    | Sesja       | 30 s    | `required-unverified`          |
| `DELETE` | `/api/records/{id}/feedback/{lot_id}?source=copart\|iaai` | Usunięcie feedbacku (idempotentne).         | Tak (200/204/404 OK)   | Sesja       | 30 s    | `required-unverified`          |
| `POST`   | `/api/feedback/analyze`                                | Meta-analiza feedbacku.                        | Nie                    | Sesja       | 60 s    | `required-unverified`          |
| `GET`    | `/api/llm-cache/list`                                  | Lista wpisów cache LLM.                        | Tak                    | Sesja       | 30 s    | `required-unverified`          |
| `DELETE` | `/api/llm-cache`                                       | Wyczyszczenie cache LLM.                       | Tak                    | Sesja       | 30 s    | `required-unverified`          |
| `DELETE` | `/api/llm-cache/entry/{key}`                           | Usunięcie wpisu cache LLM.                     | Tak (200/204/404 OK)   | Sesja       | 30 s    | `required-unverified`          |
| `GET`    | `/api/html-cache`                                      | Lista snapshotów HTML.                         | Tak                    | Sesja       | 30 s    | `required-unverified`          |
| `GET`    | `/api/html-cache/{source}/{filename}`                  | Podgląd pojedynczego snapshotu HTML.           | Tak                    | Sesja       | 30 s    | `required-unverified`          |
| `GET`    | `/api/model-normalizations`                            | Lista normalizacji modeli aut.                 | Tak                    | Sesja       | 30 s    | `required-unverified`          |
| `DELETE` | `/api/model-normalizations/{id}`                       | Usunięcie normalizacji.                        | Tak (200/204/404 OK)   | Sesja       | 30 s    | `required-unverified`          |
| `POST`   | `/api/parse-client-message`                            | LLM zamienia wiadomość klienta na criteria.    | Nie                    | Sesja       | 60 s    | `required-unverified`          |
| `GET`    | `/api/db/overview`                                     | Podgląd stanu bazy backendu.                   | Tak                    | Sesja       | 30 s    | `required-unverified`          |
| `GET`    | `/api/capabilities`                                    | Dostępność źródeł aukcyjnych (copart/iaai/manheim). | Tak               | Sesja       | 30 s    | `required-unverified`          |
| `GET`    | `/clients`                                             | Lista klientów.                                | Tak                    | Sesja       | 5 s     | `blocked-by-backend-discovery` |
| `POST`   | `/clients`                                             | Utworzenie klienta.                            | Nie                    | Sesja       | 8 s     | `blocked-by-backend-discovery` |

### Jobs (scraper)

| Metoda | Ścieżka                     | Cel                                                              | Idempotencja | Uprawnienie | Timeout | Status                |
| ------ | --------------------------- | ---------------------------------------------------------------- | ------------ | ----------- | ------- | --------------------- |
| `POST` | `/api/search`               | Start pojedynczego wyszukiwania.                                 | Nie          | Sesja       | 20 s    | `required-unverified` |
| `POST` | `/api/search/batch`         | Start batcha (limit 20).                                         | Nie          | Sesja       | 20 s    | `required-unverified` |
| `GET`  | `/api/jobs/{job_id}`        | Status joba (`queued/running/done/error/cancelled/interrupted`). | Tak          | Sesja       | 5 s     | `required-unverified` |
| `POST` | `/api/jobs/{job_id}/cancel` | Anulowanie joba.                                                 | Tak          | Sesja       | 5 s     | `required-unverified` |
| `GET`  | `/api/jobs/{job_id}/logs`   | Pobranie logów joba.                                             | Tak          | Sesja       | 10 s    | `required-unverified` |

### Raporty

| Metoda | Ścieżka                                    | Cel                                | Idempotencja | Uprawnienie | Timeout | Status                         |
| ------ | ------------------------------------------ | ---------------------------------- | ------------ | ----------- | ------- | ------------------------------ |
| `GET`  | `/reports/{record_id}/broker_bundle`       | URL/artefakt raportu broker.       | Tak          | Sesja       | 10 s    | `required-unverified`          |
| `GET`  | `/reports/{record_id}/client_bundle`       | URL/artefakt raportu klient.       | Tak          | Sesja       | 10 s    | `required-unverified`          |
| `GET`  | `/reports/{record_id}/client_short_bundle` | Skrócony raport klient.            | Tak          | Sesja       | 10 s    | `required-unverified`          |
| `POST` | `/reports/pdf`                             | Generacja PDF po stronie backendu. | Nie          | Sesja       | 30 s    | `blocked-by-backend-discovery` |

### Ustawienia

| Metoda | Ścieżka                          | Cel                                            | Idempotencja | Uprawnienie | Timeout | Status                |
| ------ | -------------------------------- | ---------------------------------------------- | ------------ | ----------- | ------- | --------------------- |
| `GET`  | `/api/settings/default-criteria` | Domyślne kryteria wyszukiwania.                | Tak          | Sesja       | 5 s     | `required-unverified` |
| `PUT`  | `/api/settings/default-criteria` | Zapis domyślnych kryteriów (whole-object put). | Tak          | Sesja       | 5 s     | `required-unverified` |
| `GET`  | `/api/settings/ai-providers`     | Konfiguracja AI (provider/model).              | Tak          | Sesja       | 5 s     | `required-unverified` |
| `PUT`  | `/api/settings/ai-providers`     | Zapis konfiguracji AI.                         | Tak          | Sesja       | 5 s     | `required-unverified` |
| `GET`  | `/api/settings/pipeline-filters` | Filtry systemowe (seller type, body).          | Tak          | Sesja       | 5 s     | `required-unverified` |
| `PUT`  | `/api/settings/pipeline-filters` | Zapis filtrów systemowych.                     | Tak          | Sesja       | 5 s     | `required-unverified` |

### Watchlist / Watch queue

| Metoda   | Ścieżka           | Cel                           | Idempotencja | Uprawnienie | Timeout | Status                         |
| -------- | ----------------- | ----------------------------- | ------------ | ----------- | ------- | ------------------------------ |
| `GET`    | `/watchlist`      | Lista watchlist-y.            | Tak          | Sesja       | 5 s     | `blocked-by-backend-discovery` |
| `POST`   | `/watchlist`      | Dodanie pozycji.              | Nie          | Sesja       | 5 s     | `blocked-by-backend-discovery` |
| `DELETE` | `/watchlist/{id}` | Usunięcie pozycji.            | Tak          | Sesja       | 5 s     | `blocked-by-backend-discovery` |
| `GET`    | `/queue`          | Lista watch queue.            | Tak          | Sesja       | 5 s     | `blocked-by-backend-discovery` |
| `POST`   | `/queue`          | Dodanie zapytania do kolejki. | Nie          | Sesja       | 5 s     | `blocked-by-backend-discovery` |
| `DELETE` | `/queue/{id}`     | Usunięcie z kolejki.          | Tak          | Sesja       | 5 s     | `blocked-by-backend-discovery` |

### Audit / logi operacyjne

| Metoda | Ścieżka             | Cel                                             | Idempotencja | Uprawnienie | Timeout | Status                         |
| ------ | ------------------- | ----------------------------------------------- | ------------ | ----------- | ------- | ------------------------------ |
| `GET`  | `/audit/search`     | Historia audytu wyszukiwań.                     | Tak          | Sesja       | 10 s    | `blocked-by-backend-discovery` |
| `GET`  | `/audit/operations` | Logi operacyjne (odpowiednik `operation_logs`). | Tak          | Sesja       | 10 s    | `blocked-by-backend-discovery` |

### Diagnostyka

| Metoda | Ścieżka        | Cel                                                        | Idempotencja | Uprawnienie | Timeout | Status                         |
| ------ | -------------- | ---------------------------------------------------------- | ------------ | ----------- | ------- | ------------------------------ |
| `GET`  | `/diagnostics` | Wynik lokalnej diagnostyki backendu (SQLite, scraper, AI). | Tak          | Sesja       | 8 s     | `blocked-by-backend-discovery` |

## Zasady schematów

- **Request/response schemas nie są zdefiniowane** w tym dokumencie, dopóki zespół Ubuntu nie potwierdzi ich w OpenAPI/JSON Schema. Wszystkie oznaczenia „required-unverified" i „blocked-by-backend-discovery" wymagają discovery przed wdrożeniem.
- **Nie wymyślaj schematów po stronie GUI**. Klient BFF przekazuje request `body` transparentnie po walidacji Zod-em na wejściu server function i traktuje odpowiedź jako `unknown` do czasu, aż schema zostanie potwierdzona (`validate` w `ubuntuApiRequest`).
- **Idempotencja**: metody `GET`/`HEAD`/`DELETE` muszą pozostać idempotentne. Powtórzone `DELETE` może zwrócić `200`, `204` **lub** `404` — istotne jest, aby efekt uboczny wystąpił dokładnie raz. Nie zakładaj konkretnego kodu odpowiedzi po drugim wywołaniu.

## Rate limiting

- Ubuntu powinno implementować per-user rate limit dla `/auth/login` (analogicznie do obecnego 5 prób / 15 min).
- BFF **nie** implementuje własnego rate limitu dla wywołań gateway — polega na rate limicie backendu.

## Wybór transportu (etap 2)

- Wszystkie server functions korzystają z `src/server/backend-transport.server.ts`, które kieruje żądania na Ubuntu lub legacy w zależności od stanu zmiennych środowiskowych:
  - **Ubuntu**: `UBUNTU_API_BASE_URL`, `UBUNTU_API_BEARER_TOKEN`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` — wszystkie cztery ustawione i URL waliduje się jako `https://`, bez credentials/query/hash.
  - **Legacy**: żadna z czterech zmiennych Ubuntu nie jest ustawiona; używane są `API_BASE_URL` + `API_BEARER_TOKEN`.
  - **Fail closed**: dowolna częściowa konfiguracja Ubuntu ⇒ żaden request nie zostaje wysłany i **nie ma** fallbacku do legacy.
- Po wybraniu transportu Ubuntu **nie ma runtime fallbacku** do legacy przy timeout / 401 / 403 / 429 / 5xx / błędzie sieci. Fallback nigdy nie powtórzy mutacji na drugim backendzie.
- Retry jest zamknięty w `ubuntu-api.server.ts` (`GET`/`HEAD`, jeden retry, tylko network / 502 / 503 / 504).

## Rejestr braków

Endpointy oznaczone `missing` lub `blocked-by-backend-discovery` blokują konkretne ekrany GUI — patrz `docs/migration-status.md`.
