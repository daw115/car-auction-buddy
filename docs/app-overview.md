# Car Auction Buddy — Szkic aplikacji

Dokument poglądowy: co robi aplikacja, jak jest zbudowana, gdzie szukać kodu.
Data: 2026-06-26.

---

## 1. Cel aplikacji

Webowy asystent do **wyszukiwania, analizy i monitorowania** aukcji
samochodowych (Copart / IAAI). Łączy:

- scraper (zewnętrzne REST API) z cache wyników,
- analizę AI (Anthropic / Gemini) ofert pod kątem opłacalności,
- watchlist + raporty PDF,
- kolejkę ponownych sprawdzeń (gdy brak wyników) z powiadomieniem na Telegram,
- panel logów, audytu i statusu joba.

UI po polsku. Auth: bramka hasłem (PasswordGate) + per-user hasło.

---

## 2. Stack

| Warstwa     | Technologia                                        |
| ----------- | -------------------------------------------------- |
| Framework   | TanStack Start v1 (React 19 + SSR) na Vite 7       |
| Runtime srv | Cloudflare Workers (`nodejs_compat`)               |
| Routing     | File-based (`src/routes/`, flat dot convention)    |
| UI          | shadcn/ui + Radix + Tailwind v4 (`oklch` tokeny)   |
| Backend     | Lovable Cloud (Supabase managed) — DB / auth / fns |
| AI          | Anthropic + Gemini (server only)                   |
| PDF         | `@react-pdf/renderer` (server)                     |
| Pkg manager | bun                                                |

---

## 3. Mapa routes (frontend)

| URL           | Plik                        | Rola                                          |
| ------------- | --------------------------- | --------------------------------------------- |
| `/`           | `src/routes/index.tsx`      | Główny panel: formularz wyszukiwania + status |
| `/dashboard`  | `src/routes/dashboard.tsx`  | Przegląd aktywnych jobów                      |
| `/jobs`       | `src/routes/jobs.tsx`       | Lista joby + progres                          |
| `/records`    | `src/routes/records.tsx`    | Rekordy z backendu (split-pane)               |
| `/watchlist`  | `src/routes/watchlist.tsx`  | Watchlist użytkownika                         |
| `/calculator` | `src/routes/calculator.tsx` | Kalkulator kosztów importu                    |
| `/database`   | `src/routes/database.tsx`   | Widok zapisanych danych                       |
| `/settings`   | `src/routes/settings.tsx`   | Ustawienia użytkownika                        |
| `/dev/logs`   | `src/routes/dev.logs.tsx`   | Stream logów (dev)                            |

Root layout: [`src/routes/__root.tsx`](../src/routes/__root.tsx) — sidebar +
topbar + `<Outlet/>`.

---

## 4. Routes API (raw HTTP / webhooks)

Lokalizacja: `src/routes/api/`

| Endpoint                              | Plik                               | Opis                           |
| ------------------------------------- | ---------------------------------- | ------------------------------ |
| `GET  /api/health`                    | `api/health.ts`                    | Healthcheck                    |
| `GET  /api/version`                   | `api/version.ts`                   | Wersja builda                  |
| `GET  /api/config`                    | `api/config.ts`                    | Status env + app_config        |
| `GET  /api/records`                   | `api/records.ts`                   | Rekordy z DB                   |
| `POST /api/reports/pdf`               | `api/reports/pdf.ts`               | Generowanie PDF                |
| `GET  /api/scraper-logs.stream`       | `api/scraper-logs.stream.ts`       | SSE log stream                 |
| `POST /api/dev/auth`                  | `api/dev/auth.ts`                  | Dev login                      |
| `POST /api/public/hooks/cleanup-logs` | `api/public/hooks/cleanup-logs.ts` | Cron cleanup (public, no auth) |

---

## 5. Server functions (RPC)

Lokalizacja: `src/functions/*.functions.ts` — wywoływane z klienta przez
typed RPC (`createServerFn` z `@tanstack/react-start`).

| Plik                                                                          | Co tam jest                                                                |
| ----------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| [`api.functions.ts`](../src/functions/api.functions.ts)                       | Scraper: start / status / cancel / logs / cache + `POST /api/search` proxy |
| [`queue.functions.ts`](../src/functions/queue.functions.ts)                   | Kolejka „re-check": `addToQueue`, `listQueue`, `removeFromQueue`           |
| [`watchlist.functions.ts`](../src/functions/watchlist.functions.ts)           | Watchlist CRUD                                                             |
| [`external.functions.ts`](../src/functions/external.functions.ts)             | Wywołania zewnętrznych API                                                 |
| [`site-auth.functions.ts`](../src/functions/site-auth.functions.ts)           | Bramka hasłem + per-user hasło                                             |
| [`dev-middleware.functions.ts`](../src/functions/dev-middleware.functions.ts) | Dev tooling                                                                |

Server-only helpery (nie importowane z klienta) — `src/server/`:
`logger.server.ts`, `anthropic.server.ts`, `gemini.server.ts`,
`pdf-report.server.ts`, `report.ts`, `lot-report.ts`,
`prompts/` (system + lot prompty), `ai-retry.server.ts`, `ai.server.ts`,
`log-stream.server.ts`, `http-log.server.ts`, `dev-auth.server.ts`,
`validate-artifacts-meta.ts`.

---

## 6. Panele UI (komponenty)

Lokalizacja: `src/components/panels/`

| Plik                                            | Funkcja                                          |
| ----------------------------------------------- | ------------------------------------------------ |
| `criteria-form.tsx`                             | Formularz kryteriów wyszukiwania                 |
| `scraper-toolbar.tsx`                           | Toolbar (start / cancel / rerun)                 |
| `progress-panels.tsx`                           | Progres scrapowania                              |
| `jobs-panel.tsx`                                | Lista aktywnych jobów                            |
| `batch-jobs-panel.tsx` + `batch-job-card.tsx`   | Joby zbiorcze                                    |
| `listings-table.tsx`                            | Tabela wyników (oferty)                          |
| `records-panel.tsx`                             | Widok rekordów                                   |
| `analysis-results.tsx`                          | Wyniki analizy AI                                |
| `ai-actions-bar.tsx`                            | Akcje AI (analiza, raport)                       |
| `scraper-reports-section.tsx`                   | Raporty scrapera                                 |
| `connection-status-panel.tsx`                   | Status połączenia z backendem                    |
| `session-header.tsx`                            | Header sesji (user, status)                      |
| `clients-aside.tsx` + `client-message-card.tsx` | Panel klientów                                   |
| `no-results-queue-dialog.tsx`                   | Dialog „Dodać do kolejki ponownego sprawdzania?" |
| `form-helpers.tsx`                              | Helpery formularzy                               |

Inne kluczowe komponenty (`src/components/`):
`PasswordGate.tsx`, `app-sidebar.tsx`, `app-topbar.tsx`, `page-header.tsx`,
`active-job-pill.tsx`, `LogsPanel.tsx`, `LiveJobLogs.tsx`,
`ResumeJobBanner.tsx`, `BidfaxBadge.tsx`, `JsonDetails.tsx`,
`ChunkErrorOverlay.tsx`, `theme-provider.tsx`, `theme-toggle.tsx`.

---

## 7. Przepływ użytkownika (happy path)

```text
PasswordGate ──► /  (criteria-form)
                 │
                 ▼
          POST /api/search ── (scraper start)
                 │
        ┌────────┴────────┐
        │                 │
   no_results=true    wyniki
        │                 │
   NoResultsDialog    listings-table
        │                 │
   POST /api/queue    analysis-results (AI)
        │                 │
   worker (cron)     watchlist / PDF
        │
   Telegram notify ← gdy worker znajdzie loty
```

---

## 8. Backend / DB

- **Supabase managed** przez Lovable Cloud.
- Klient browser: `@/integrations/supabase/client` (anon, RLS).
- Klient admin (server only): `@/integrations/supabase/client.server`
  (`supabaseAdmin`, service role, BYPASS RLS).
- Auth-middleware do server functions: `@/integrations/supabase/auth-middleware`.
- Migracje SQL: `supabase/migrations/` (timestamped).
- Role: ZAWSZE w osobnej tabeli `user_roles` + funkcja `has_role()`
  `SECURITY DEFINER`. Nigdy w `profiles`.

Tabele kluczowe (z kodu): `operation_logs`, `watchlist_items`, `records`,
`site_users` (PasswordGate), `queue_watches` (re-check queue).

---

## 9. Konfiguracja / env

- `.env` zarządzany przez Lovable — **nie edytować ani nie commitować sekretów**.
- Sekrety produkcyjne dodawać przez Lovable Cloud → secrets.
- Gemini AI Studio używa server-only `GEMINI_API_KEY`; opcjonalny `GEMINI_MODEL`
  domyślnie wskazuje `gemini-3.5-flash`.
- `AI_PROVIDER=gemini` wymusza Gemini, `AI_PROVIDER=anthropic` wymusza Anthropic,
  a brak wartości uruchamia automatyczne wykrywanie dostępnych kluczy. Ustawienie
  `app_config.ai_analysis_mode` ma wyższy priorytet niż zmienna środowiskowa.
- Klucz Gemini jest wysyłany wyłącznie przez backend w nagłówku
  `x-goog-api-key`; nie może trafić do URL, logów ani kodu klienta.
- Pozostałe kluczowe zmienne: `SCRAPER_BASE_URL`, `ANTHROPIC_API_KEY`,
  `ANTHROPIC_MODEL`, `SITE_MASTER_PASSWORD`, Telegram bot token.

---

## 10. Quick links — najważniejsze pliki

- Root layout: [`src/routes/__root.tsx`](../src/routes/__root.tsx)
- Główny panel: [`src/routes/index.tsx`](../src/routes/index.tsx)
- Sidebar: [`src/components/app-sidebar.tsx`](../src/components/app-sidebar.tsx)
- Topbar: [`src/components/app-topbar.tsx`](../src/components/app-topbar.tsx)
- Bramka hasłem: [`src/components/PasswordGate.tsx`](../src/components/PasswordGate.tsx)
- Scraper API: [`src/functions/api.functions.ts`](../src/functions/api.functions.ts)
- Kolejka re-check: [`src/functions/queue.functions.ts`](../src/functions/queue.functions.ts)
- Dialog no-results: [`src/components/panels/no-results-queue-dialog.tsx`](../src/components/panels/no-results-queue-dialog.tsx)
- Logger: [`src/server/logger.server.ts`](../src/server/logger.server.ts)
- Design tokeny: [`src/styles.css`](../src/styles.css)
- Reguły projektu: [`CLAUDE.md`](../CLAUDE.md)
- Plan refactoru: [`.lovable/plan.md`](../.lovable/plan.md)

---

## 11. Komendy

```bash
bun install
bun dev
bun run lint
bun run format
```

Nie odpalaj `bun run build` ręcznie — Lovable robi to automatycznie.
