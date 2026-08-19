# CLAUDE.md

Przewodnik dla Claude Code (i innych asystentów AI) pracujących w tym repo.
Czytaj **w całości** przed pierwszą zmianą — pomija się tu rzeczy oczywiste z kodu, ale zawiera reguły, których złamanie psuje build albo wdrożenie na serwer.

---

## 1. O projekcie

**Car Auction Buddy** — aplikacja webowa do scrapowania, analizy i raportowania ofert pojazdów z aukcji (Copart / IAAI itp.).

Kluczowe funkcje:

- **Scraper jobs** — uruchamianie zewnętrznego scrapera przez REST API (`SCRAPER_BASE_URL`), polling statusu, anulowanie, rerun.
- **Cache wyników** — wyniki cache'owane w DB po hashu parametrów (date window, seller type, damage), żeby nie scrapować ponownie.
- **AI analysis** — panel sam nie woła modelu: analizę, oceny i raporty robi backend FastAPI (`ai/analyzer.py`, `report/`), a panel je wyłącznie pokazuje. `ANTHROPIC_API_KEY` w tym repo dotyczy pojedynczych, pobocznych wywołań z `anthropic.server.ts`; ścieżka produkcyjna backendu chodzi na subskrypcji Claude Code, nie na kluczu API.
- **Watchlist + raporty PDF** — `@react-pdf/renderer`, generowane server-side.
- **Panel statusu** — szczegółowe komunikaty błędów dla `error/failed`, przycisk „Pobierz logi", „Uruchom ponownie".
- **Operation logs** — strukturyzowane logi w tabeli `operation_logs` (przez `src/server/logger.server.ts`).

---

## 2. Stack

- **Framework**: TanStack Start v1 (React 19 + SSR) na Vite 7
- **Runtime serwerowy**: Node 22 (Nitro `node-server`) pod systemd na własnym Ubuntu — patrz sekcja 7
- **Routing**: file-based w `src/routes/` (flat dot convention)
- **Styling**: Tailwind CSS v4 (przez `@tailwindcss/vite`, tokeny w `src/styles.css`, format `oklch`)
- **UI**: shadcn/ui + Radix
- **Backend**: FastAPI na tym samym Ubuntu (`API_BASE_URL`) + Postgres/PostgREST w dockerze (`usacar-db`)
- **Package manager**: **bun** (nie npm/yarn/pnpm)
- **Hosting**: własny serwer, wdrożenie skryptem `usacar-deploy-dashboard.sh` (sekcja 7)

---

## 3. Komendy

```bash
bun install          # instalacja zależności
bun dev              # dev server z HMR (Vite + SSR)
bun run build        # production build — bramka przed wdrożeniem, odpalaj sam
bun run preview      # podgląd builda
bun run lint         # ESLint
bun run format       # Prettier --write
bun add <pkg>        # dodaj zależność
bun remove <pkg>     # usuń zależność
```

**Nie używaj** `npm install` / `yarn` / `pnpm` — projekt ma `bunfig.toml` i lockfile bun.

---

## 4. Struktura katalogów

Stan na 19 sierpnia 2026, sprawdzony z drzewem. Poprzednia wersja tej sekcji
opisywała układ sprzed przenosin i myliła w rzeczy podstawowej: server functions
mieszkają w `src/functions/`, a `src/server/` trzyma helpery server-only.

```
src/
├── routes/                       # File-based routing (TanStack Start, flat dot convention)
│   ├── __root.tsx                # ROOT layout (html/head/body shell). Nie zmieniać struktury.
│   ├── index.tsx                 # / — panel scrapera: formularz, postęp, log, wyniki
│   ├── leady.tsx                 # skrzynka sprzedażowa
│   ├── klient.$leadId.tsx        # karta klienta: rozmowa, kandydaci, sprawa
│   ├── calculator.tsx            # kalkulator importu (stawki cła bierze z backendu)
│   ├── sprawdz-vin.tsx           # PUBLICZNA strona checkera VIN
│   ├── settings*.tsx             # ustawienia, w tym powiadomienia Telegrama
│   └── api/                      # Server routes (raw HTTP)
│       ├── version.ts            # GET /api/version — wersja, commit, czas builda
│       ├── health.ts, config.ts, diagnostics.ts
│       ├── dev/                  # auth i strumień logów dla trybu deweloperskiego
│       └── public/               # BEZ logowania: lead.ts, vin-check.ts, hooks/
│
├── functions/                    # SERVER FUNCTIONS (createServerFn) — TU, nie w server/
│   ├── backend.functions.ts      # proxy do FastAPI: joby, rekordy, logi scrapera
│   ├── sales.functions.ts        # leady, kandydaci, sprawa, raporty na Telegram
│   ├── intake.functions.ts       # przyjęcie zgłoszenia z formularza
│   ├── clients.functions.ts, ai-providers.functions.ts, external.functions.ts
│   ├── default-criteria.functions.ts, pipeline-filters.functions.ts
│   ├── site-auth.functions.ts + site-session-middleware.functions.ts   # bramka hasła
│   └── dev-logging-middleware.functions.ts
│
├── server/                       # Helpery SERVER-ONLY (Vite blokuje import z klienta)
│   ├── site-session.server.ts    # podpisany token sesji panelu
│   ├── logger.server.ts          # writeLog / makeLogger → operation_logs (sanitizacja!)
│   ├── log-stream.server.ts, dev-auth.server.ts, dev-logger.server.ts
│   └── external-apis.server.ts
│
├── queries/                      # współdzielone klucze i opcje react-query
├── components/
│   ├── panels/                   # karty ekranów: kandydaci, sprawa, log scrapera, joby…
│   └── ui/                       # shadcn/ui — NIE edytować ręcznie
├── lib/
│   ├── backend-transport.server.ts  # jedyna droga do FastAPI (token, timeouty)
│   ├── cost-calculator.ts        # kalkulacja kosztów; STAWKI PRAWNE z backendu
│   └── types.ts, utils.ts, auction-sources.ts…
├── integrations/supabase/        # klient + typy (auto-generowane, nie edytować)
├── styles.css                    # Tailwind v4 + tokeny (oklch)
└── routeTree.gen.ts              # AUTO-GENEROWANY. NIE EDYTOWAĆ.
```

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

### Server functions (`src/functions/*.functions.ts`)

- Importuj z `@tanstack/react-start` (nie `@tanstack/start`).
- `process.env.X` czytaj **wewnątrz** `.handler()`, nie na top-level modułu.
- Helpery server-only nazywaj `*.server.ts` — Vite blokuje ich import z bundla klienta.
- Komponenty importują z `*.functions.ts`, nigdy z `*.server.ts`.

### Runtime serwerowy (server functions + SSR)

Zwykły Node 22 na Ubuntu — ograniczeń edge już nie ma. Zostaje jedno: build musi
zbundlować wszystko, co server functions importują, więc **nie ustawiaj `ssr.external`**
w `vite.config.ts`. Paczki natywne (`sharp`, `canvas`) i tak dokładaj z rozmysłem —
każdą trzeba zbudować na serwerze przy wdrożeniu.

### Supabase (Postgres w dockerze na serwerze)

- **Role użytkowników**: ZAWSZE w osobnej tabeli `user_roles` + funkcja `has_role()` `SECURITY DEFINER`. **Nigdy** nie trzymaj roli w `profiles`/`users` (privilege escalation).
- **Foreign keys do `auth.users`**: NIE rób ich. Twórz `profiles` w `public` i referencjonuj tam.
- **RLS**: każda nowa tabela musi mieć włączone RLS + polityki.
- **Migracje**: plik w `supabase/migrations/` z timestampem, aplikowany ręcznie (`docker exec -it usacar-db-postgres-1 psql -U postgres`). Nie ma automatu. Nigdy `ALTER DATABASE postgres`.
- **Walidacja czasowa**: triggery, nie `CHECK (expire_at > now())` (CHECK musi być immutable).
- **Schematy zarezerwowane** (`auth`, `storage`, `realtime`, `supabase_functions`, `vault`) — nie modyfikuj.
- **Limit zapytań**: 1000 wierszy domyślnie — paginuj jeśli potrzeba więcej.
- Klient: `import { supabase } from "@/integrations/supabase/client"`. Server admin: `supabaseAdmin` z `client.server.ts`.

### Sekrety / logi

- **Nigdy** nie loguj sekretów. `src/server/logger.server.ts` ma `sanitizeDetails()` — używaj go (helpery `makeLogger(ctx)`).
- Sekrety wpisuje się w `/etc/usacar/dashboard.env` na serwerze, po zmianie `sudo systemctl restart usacar-dashboard`. Klucze publishable/anon mogą być w kodzie — ale **nie wolno na nich opierać autoryzacji**.

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

### Konwencja commitów (Conventional Commits)

**Format wiadomości:**

```
<type>(<scope>): <krótki opis w trybie rozkazującym, max 72 znaki>

[opcjonalny body — DLACZEGO, nie CO; zawijaj na 72 znakach]

[opcjonalny footer: Refs #123, BREAKING CHANGE: ...]
```

**Dozwolone `type`:**

- `feat` — nowa funkcjonalność
- `fix` — naprawa buga
- `refactor` — zmiana kodu bez zmiany zachowania
- `perf` — poprawa wydajności
- `style` — formatowanie, brak zmian logiki
- `docs` — dokumentacja (README, CLAUDE.md, komentarze)
- `test` — testy
- `chore` — zależności, configi, narzędzia
- `db` — migracje SQL / zmiany schematu

**Typowe `scope`:** `scraper`, `cache`, `ai`, `pdf`, `watchlist`, `auth`, `ui`, `api`, `db`, `deps`, `config`.

**Przykłady:**

```
feat(scraper): add cancel button to status panel
fix(cache): include damage filter in cache key hash
db(watchlist): add user_id index on watchlist_items
docs(claude): document commit convention
chore(deps): bump @tanstack/react-start to 1.168
```

### Po każdej zmianie — commit + push

Claude Code MUSI po zakończeniu zadania (gdy build/typecheck przechodzi):

1. `git add -A`
2. `git commit -m "<type>(<scope>): <opis>"` zgodnie z formatem wyżej
3. `git push origin main`

**Zasady:**

- Jeden logiczny zestaw zmian = jeden commit. Nie kumuluj kilku featurów w jednym commicie.
- Jeśli zadanie obejmuje migrację SQL + kod aplikacji — dwa commity (`db(...)` najpierw, potem `feat(...)`).
- Nigdy nie commituj `node_modules/`, `.env`, `dist/`, `.lovable/` (są w `.gitignore`).
- Przed pushem: `git pull --rebase` (w repo bywa druga równoległa sesja).
- Jeśli `git push` odrzucony (non-fast-forward) → `git pull --rebase` → rozwiąż konflikty → push ponownie.
- Nie używaj `git push --force` na `main`.

**Przed każdym commitem** uruchom checklistę: [`.claude/commands/preflight-checks.md`](.claude/commands/preflight-checks.md) (`/preflight-checks`).
Gotowy template commita: [`.claude/commands/commit-and-push.md`](.claude/commands/commit-and-push.md) (`/commit-and-push`).

---

## 7. Wdrażanie (własny serwer)

Lovable nie buduje już ani nie hostuje tej aplikacji i nie ma synchronizacji
z ich platformą. Nic nie dzieje się samo po pushu — wdrożenie jest jawnym krokiem.

```bash
# na serwerze
usacar-deploy-dashboard.sh feat/selfhost
```

Skrypt pobiera ref, instaluje zależności, przepuszcza bramki
(`check-server-imports`, `tsc --noEmit`, build), **dopiero potem** tworzy
`/opt/usacar-dashboard/releases/<sha>-<ts>`, atomowo przestawia symlink `current`,
restartuje usługę i sprawdza `/api/version`. Przy nieudanym health-checku wraca
na poprzedni release.

**Zalecenia przy pracy lokalnej:**

1. `bun dev` do pracy. `bun run build` warto puścić przed wdrożeniem — nikt nie
   zbuduje za Ciebie.
2. Małe, atomowe commity zgodne z sekcją 6.
3. Migracje SQL: plik w `supabase/migrations/` z timestampem, ale **aplikowane
   ręcznie** przez `psql` na `127.0.0.1:5433` — nie ma automatu. Szczegóły
   w `deploy/selfhost/README.md`.
4. Zmiany środowiska: `/etc/usacar/dashboard.env` (`0600 root:root`), po edycji
   `sudo systemctl restart usacar-dashboard`.

---

## 8. Debugging

- **Logi dev-server**: terminal, w którym stoi `bun dev`.
- **Logi produkcyjne**: `journalctl -u usacar-dashboard -f` na serwerze, albo panel `/dev/logs`.
- **Logi aplikacji**: tabela `operation_logs` (zapisywane przez `makeLogger`).
- **Browser**: F12 → Console / Network.
- **Status Cloud backendu**: jeśli DB/auth zachowuje się dziwnie — sprawdź czy instancja nie jest w trakcie `RESTARTING` / `UPGRADING`.

---

## 9. Częste pułapki

| Symptom                                  | Przyczyna                                       | Fix                                                                                             |
| ---------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `Failed to resolve import`               | Importujesz plik, którego nie ma                | Stwórz plik najpierw, potem dodaj import                                                        |
| `window is not defined` w SSR            | Klient-only kod na top-level modułu serwerowego | Przenieś do funkcji wywoływanej tylko po stronie klienta lub zmień nazwę pliku na `*.client.ts` |
| `process.env.X is undefined` w handlerze | Czytasz env na top-level modułu                 | Czytaj **wewnątrz** `.handler()`                                                                |
| `[unenv] X is not implemented`           | Używasz Node-only API w Worker                  | Zamień na fetch / Web API / paczkę edge-compatible                                              |
| Duplikat route `/`                       | Stworzyłeś `_app/index.tsx` obok `index.tsx`    | Usuń `_app/`                                                                                    |
| RLS blokuje zapytanie                    | Brak polityki dla użytkownika                   | Dodaj policy z `has_role(auth.uid(), 'admin')` lub `auth.uid() = user_id`                       |
| Build działa lokalnie, crashuje na prod  | Paczka natywna, niezbudowana na serwerze        | Sprawdź `journalctl -u usacar-dashboard`; deploy sam cofa się na poprzedni release              |

---

## 10. Pytania do użytkownika przed dużymi zmianami

Przed refactorem architektury, zmianą stacku, dodaniem nowej zależności w core flow lub zmianą schematu DB obejmującą migrację danych — **dopytaj**, nie zgaduj.
