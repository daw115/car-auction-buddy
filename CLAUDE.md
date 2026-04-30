# CLAUDE.md

Przewodnik dla Claude Code (i innych asystentów AI) pracujących w tym repo.
Czytaj **w całości** przed pierwszą zmianą — pomija się tu rzeczy oczywiste z kodu, ale zawiera reguły, których złamanie psuje build / sync z Lovable.

---

## 1. O projekcie

**Car Auction Buddy** — aplikacja webowa do scrapowania, analizy i raportowania ofert pojazdów z aukcji (Copart / IAAI itp.).

Kluczowe funkcje:
- **Scraper jobs** — uruchamianie zewnętrznego scrapera przez REST API (`SCRAPER_BASE_URL`), polling statusu, anulowanie, rerun.
- **Cache wyników** — wyniki cache'owane w DB po hashu parametrów (date window, seller type, damage), żeby nie scrapować ponownie.
- **AI analysis** — analiza ofert przez Anthropic API (`ANTHROPIC_API_KEY`, model w `ANTHROPIC_MODEL`).
- **Watchlist + raporty PDF** — `@react-pdf/renderer`, generowane server-side.
- **Panel statusu** — szczegółowe komunikaty błędów dla `error/failed`, przycisk „Pobierz logi", „Uruchom ponownie".
- **Operation logs** — strukturyzowane logi w tabeli `operation_logs` (przez `src/server/logger.server.ts`).

---

## 2. Stack

- **Framework**: TanStack Start v1 (React 19 + SSR) na Vite 7
- **Runtime serwerowy**: Cloudflare Workers (`nodejs_compat`) — patrz sekcja 7
- **Routing**: file-based w `src/routes/` (flat dot convention)
- **Styling**: Tailwind CSS v4 (przez `@tailwindcss/vite`, tokeny w `src/styles.css`, format `oklch`)
- **UI**: shadcn/ui + Radix
- **Backend**: Lovable Cloud (= managed Supabase) — auth, DB, storage, edge functions
- **Package manager**: **bun** (nie npm/yarn/pnpm)
- **Hosting**: Lovable platform (preview + published), kod synchronizowany z GitHub dwukierunkowo

---

## 3. Komendy

```bash
bun install          # instalacja zależności
bun dev              # dev server z HMR (Vite + SSR)
bun run build        # production build (uruchamia się automatycznie w Lovable — NIE odpalaj ręcznie podczas pracy z Lovable)
bun run preview      # podgląd builda
bun run lint         # ESLint
bun run format       # Prettier --write
bun add <pkg>        # dodaj zależność
bun remove <pkg>     # usuń zależność
```

**Nie używaj** `npm install` / `yarn` / `pnpm` — projekt ma `bunfig.toml` i lockfile bun.

---

## 4. Struktura katalogów

```
src/
├── routes/                       # File-based routing (TanStack Start)
│   ├── __root.tsx                # ROOT layout (html/head/body shell). Nie zmieniać struktury.
│   ├── index.tsx                 # / — główny panel scrapera (formularz + status + wyniki)
│   ├── dashboard.tsx             # /dashboard
│   ├── calculator.tsx            # /calculator — kalkulator kosztów
│   ├── settings.tsx              # /settings
│   ├── watchlist.tsx             # /watchlist
│   └── api/                      # Server routes (raw HTTP / webhooks)
│       ├── health.ts             # GET /api/health
│       ├── config.ts             # GET /api/config (status env + app_config)
│       ├── records.ts
│       ├── reports/pdf.ts        # generowanie PDF
│       └── public/hooks/         # endpointy publiczne (cron, webhooki) — bez auth
│           └── cleanup-logs.ts
│
├── server/                       # Kod SERWEROWY (server functions + helpery)
│   ├── api.functions.ts          # createServerFn — scraper start/status/cancel/logs/cache
│   ├── external.functions.ts     # createServerFn — wywołania zewnętrznych API
│   ├── watchlist.functions.ts    # createServerFn — watchlist CRUD
│   ├── anthropic.server.ts       # klient Anthropic (server-only)
│   ├── logger.server.ts          # writeLog / makeLogger -> operation_logs (sanitizacja sekretów!)
│   ├── lot-report.ts             # logika raportu pojedynczego lota
│   ├── pdf-report.server.ts      # render PDF (@react-pdf/renderer)
│   ├── report.ts                 # logika raportu zbiorczego
│   └── prompts/                  # prompty AI (system-prompt.ts, lot-prompt.ts, .txt)
│
├── components/
│   ├── ui/                       # shadcn/ui — NIE edytować ręcznie chyba że dodajesz wariant
│   ├── JsonDetails.tsx
│   └── LogsPanel.tsx
│
├── hooks/use-mobile.tsx
│
├── integrations/supabase/
│   ├── client.ts                 # Klient ANON (browser + server). NIE EDYTOWAĆ — auto-generowany.
│   ├── client.server.ts          # supabaseAdmin (service-role, server-only)
│   ├── types.ts                  # NIE EDYTOWAĆ — auto-generowany ze schematu DB
│   └── auth-middleware.ts
│
├── lib/
│   ├── cost-calculator.ts        # czysta logika kalkulacji kosztów
│   ├── types.ts                  # współdzielone typy domenowe
│   └── utils.ts                  # cn() i drobne helpery
│
├── styles.css                    # Tailwind v4 + tokeny (oklch). Tu definiujesz kolory.
├── router.tsx                    # konfiguracja routera (defaultErrorComponent)
└── routeTree.gen.ts              # AUTO-GENEROWANY przez router-plugin. NIE EDYTOWAĆ.

supabase/
├── config.toml                   # project_id + per-function config. NIE zmieniaj project-level.
└── migrations/                   # SQL migracje (kolejność po nazwie pliku)

.env                              # Auto-zarządzany przez Lovable Cloud. NIE EDYTOWAĆ.
vite.config.ts                    # Używa @lovable.dev/vite-tanstack-config — NIE dodawać duplikatów pluginów
wrangler.jsonc                    # Cloudflare Workers config
```

---

## 5. Reguły, których NIE wolno łamać

### Pliki nietykalne (auto-generowane / managed)
- `src/integrations/supabase/client.ts`
- `src/integrations/supabase/types.ts`
- `src/routeTree.gen.ts`
- `.env`
- `supabase/config.toml` (sekcja project-level — `project_id` itp.)

### TanStack Start
- Routing **wyłącznie** plikami w `src/routes/` (flat dot convention: `posts.$postId.tsx`, nie foldery).
- Layout root to **zawsze** `src/routes/__root.tsx`. Nie twórz `_app/`, `app/layout.tsx`, itp.
- Importy nawigacji: `from "@tanstack/react-router"` (nie `react-router-dom`).
- Każdy route z loaderem MUSI mieć `errorComponent` + `notFoundComponent`.
- W `errorComponent` używaj `useRouter()` (import), nie `Route.useRouter()`.
- Bez trailing slash w `to=` (`/products`, nie `/products/`).
- Łańcuch `createServerFn().inputValidator().handler()` musi być ciągły — nie przerywać `});`.

### Server functions (`src/server/*.functions.ts`)
- Importuj z `@tanstack/react-start` (nie `@tanstack/start`).
- `process.env.X` czytaj **wewnątrz** `.handler()`, nie na top-level modułu.
- Helpery server-only nazywaj `*.server.ts` — Vite blokuje ich import z bundla klienta.
- Komponenty importują z `*.functions.ts`, nigdy z `*.server.ts`.

### Cloudflare Workers runtime (server functions + SSR)
**Nie używaj**: `child_process` (spawn/exec), `sharp`, `canvas`, `puppeteer`, `fs.watch`, `os.cpus()`.
**OK**: `fs`, `path`, `crypto`, `Buffer`, `stream`, `fetch`, `zlib`.
Wszystkie paczki muszą być bundlowalne — nie ustawiaj `ssr.external` w `vite.config.ts`.

### Supabase / Lovable Cloud
- **Role użytkowników**: ZAWSZE w osobnej tabeli `user_roles` + funkcja `has_role()` `SECURITY DEFINER`. **Nigdy** nie trzymaj roli w `profiles`/`users` (privilege escalation).
- **Foreign keys do `auth.users`**: NIE rób ich. Twórz `profiles` w `public` i referencjonuj tam.
- **RLS**: każda nowa tabela musi mieć włączone RLS + polityki.
- **Migracje**: zawsze przez tool migracji (w Lovable) lub plik w `supabase/migrations/` z timestampem. Nigdy `ALTER DATABASE postgres`.
- **Walidacja czasowa**: triggery, nie `CHECK (expire_at > now())` (CHECK musi być immutable).
- **Schematy zarezerwowane** (`auth`, `storage`, `realtime`, `supabase_functions`, `vault`) — nie modyfikuj.
- **Limit zapytań**: 1000 wierszy domyślnie — paginuj jeśli potrzeba więcej.
- Klient: `import { supabase } from "@/integrations/supabase/client"`. Server admin: `supabaseAdmin` z `client.server.ts`.

### Sekrety / logi
- **Nigdy** nie loguj sekretów. `src/server/logger.server.ts` ma `sanitizeDetails()` — używaj go (helpery `makeLogger(ctx)`).
- Sekrety dodawaj przez Lovable Cloud secrets (env vars w Worker). Klucze publishable/anon mogą być w kodzie.

### Design system
- **Nie** używaj klas typu `text-white`, `bg-black` bezpośrednio w komponentach.
- Używaj semantycznych tokenów z `src/styles.css` (`bg-background`, `text-foreground`, `text-primary`, itp.).
- Nowe kolory definiuj w `src/styles.css` w `oklch`.
- Wariantami komponentów steruj przez `cva` (`class-variance-authority`).

---

## 6. Konwencje

- **Komponenty**: PascalCase, jeden komponent na plik (chyba że są ściśle powiązane).
- **Pliki route**: lower-case z dot-separation (`settings.profile.tsx`).
- **Server functions**: kebab-case w nazwie pliku (`api.functions.ts`), funkcje camelCase.
- **Język UI**: polski (komunikaty, labele, toasty). Komentarze w kodzie po angielsku.
- **Komentarze**: tylko gdy wyjaśniają **dlaczego**, nie **co**. Kod ma być samoopisowy.
- **Walidacja inputu**: zawsze Zod (`.inputValidator((d) => schema.parse(d))`).
- **Daty**: `date-fns`, format ISO w DB.
- **Toasty**: `sonner` (`import { toast } from "sonner"`).
- **Ikony**: `lucide-react`.

---

## 7. Workflow z Lovable

To repo jest **dwukierunkowo zsynchronizowane** z Lovable:
- Push do GitHub → Lovable widzi zmiany w ciągu sekund.
- Edycja w Lovable → automatyczny commit do GitHub.

**Zalecenia podczas pracy lokalnej z Claude Code:**
1. `git pull` przed startem sesji (Lovable mógł coś dopisać).
2. Małe, atomowe commity z opisowymi message'ami.
3. **Nie odpalaj** `bun run build` ręcznie — Lovable robi to przy każdej zmianie. Wystarczy `bun dev` lokalnie.
4. Po większych zmianach sprawdź preview na Lovable — to ostateczna weryfikacja produkcyjnego builda na Workers.
5. Migracje SQL — twórz plik w `supabase/migrations/` z timestampem `YYYYMMDDHHMMSS_description.sql`. Zostanie zaaplikowana przy następnym deployu.

**Branch switching** w Lovable jest experymentalny (Account Settings → Labs). Domyślnie pracuj na `main`.

---

## 8. Debugging

- **Logi dev-server**: `tail -n 200 /tmp/dev-server-logs/dev-server.log` (sandbox Lovable) lub terminal lokalnie.
- **Logi Worker (production)**: w Lovable → Cloud → Edge Function Logs.
- **Logi aplikacji**: tabela `operation_logs` (zapisywane przez `makeLogger`).
- **Browser**: F12 → Console / Network.
- **Status Cloud backendu**: jeśli DB/auth zachowuje się dziwnie — sprawdź czy instancja nie jest w trakcie `RESTARTING` / `UPGRADING`.

---

## 9. Częste pułapki

| Symptom | Przyczyna | Fix |
|---|---|---|
| `Failed to resolve import` | Importujesz plik, którego nie ma | Stwórz plik najpierw, potem dodaj import |
| `window is not defined` w SSR | Klient-only kod na top-level modułu serwerowego | Przenieś do funkcji wywoływanej tylko po stronie klienta lub zmień nazwę pliku na `*.client.ts` |
| `process.env.X is undefined` w handlerze | Czytasz env na top-level modułu | Czytaj **wewnątrz** `.handler()` |
| `[unenv] X is not implemented` | Używasz Node-only API w Worker | Zamień na fetch / Web API / paczkę edge-compatible |
| Duplikat route `/` | Stworzyłeś `_app/index.tsx` obok `index.tsx` | Usuń `_app/` |
| RLS blokuje zapytanie | Brak polityki dla użytkownika | Dodaj policy z `has_role(auth.uid(), 'admin')` lub `auth.uid() = user_id` |
| Build działa lokalnie, crashuje na prod | Paczka Node-only | Zamień na edge-compatible (sekcja 5: Cloudflare Workers) |

---

## 10. Pytania do użytkownika przed dużymi zmianami

Przed refactorem architektury, zmianą stacku, dodaniem nowej zależności w core flow lub zmianą schematu DB obejmującą migrację danych — **dopytaj**, nie zgaduj.
