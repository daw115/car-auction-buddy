# /preflight-checks

Slash-command dla Claude Code. Wywołanie: `/preflight-checks` (przed `/commit-and-push`).

Checklista weryfikacji zmian przed commitem. **Wszystkie kroki muszą przejść** — jeśli któryś czerwony, NIE commituj, napraw najpierw.

---

## 0. Kontekst architektury (przeczytaj raz)

- **Backend aplikacji** = TanStack Start server functions (`src/server/*.functions.ts`) na Cloudflare Workers + Lovable Cloud (Postgres).
- **FastAPI** = zewnętrzny scraper pod `SCRAPER_BASE_URL` — **nie jest częścią tego repo**. Sprawdzamy tylko, czy nasz kod poprawnie się z nim integruje (env + ping + happy path).

---

## 1. Lint + typecheck + format

```bash
bun run lint
bunx tsc --noEmit
bun run format -- --check
```

- Zero błędów ESLint i TypeScript.
- Jeśli format nie przechodzi: `bun run format` (bez `--check`) i ponowne sprawdzenie.

❌ STOP jeśli którakolwiek komenda zwraca błąd.

---

## 2. Dev server startuje czysto

```bash
bun dev
```

Obserwuj log przez ~10s (lokalnie terminal, w sandboxie: `tail -n 100 /tmp/dev-server-logs/dev-server.log`):
- ✅ `VITE ... ready in ...ms`
- ✅ Brak `error`, `Failed to resolve import`, `[plugin:vite:...] Error`
- ✅ Brak ostrzeżeń o duplikatach route `/`

❌ STOP jeśli widzisz crash lub failed import.

---

## 3. Kontrola zmiennych środowiskowych

Endpoint `/api/config` zwraca status wymaganych env.

```bash
curl -s http://localhost:3000/api/config | jq
```

Sprawdź w odpowiedzi pole `env`:
- ✅ `ANTHROPIC_API_KEY: true`
- ✅ `ANTHROPIC_MODEL` ustawiony (lub fallback `claude-sonnet-4-6`)
- ✅ `SCRAPER_BASE_URL: true`
- ✅ `SCRAPER_API_TOKEN: true`

❌ Jeśli któraś `false` — **nie commituj**, ustaw przez Lovable Cloud → Secrets (lokalnie: w `.env`, ale **nie commituj `.env`**).

Dodatkowo: sprawdź że żaden nowy sekret nie wyciekł do bundla klienta:
```bash
rg -n "ANTHROPIC_API_KEY|SCRAPER_API_TOKEN|SUPABASE_SERVICE_ROLE" src/components src/routes src/hooks src/lib
```
Powinno zwrócić **0 wyników**. Sekrety są wyłącznie w `src/server/**` i `src/integrations/supabase/client.server.ts`.

---

## 4. Healthcheck endpointów aplikacji

```bash
curl -fsS http://localhost:3000/api/health
curl -fsS http://localhost:3000/api/config | jq '.config.id'
curl -fsS -X GET http://localhost:3000/api/records | jq 'length'
```

- ✅ Każde żądanie zwraca HTTP 200 (curl `-f` zfailuje na 4xx/5xx).
- ✅ `/api/config` zwraca obiekt `config` z `id: 1`.
- ✅ `/api/records` zwraca tablicę (może być pusta).

Jeśli zmieniałeś **server functions** (`src/server/*.functions.ts`) — wywołaj je z DevTools / `curl` przez wygenerowany endpoint TanStack Start (`/_serverFn/...`) lub przetestuj klikiem w UI.

---

## 5. Healthcheck zewnętrznego scrapera (FastAPI)

Tylko jeśli zmieniałeś integrację scrapera (`api.functions.ts`, cache, polling, anuluj/rerun).

```bash
# Ping FastAPI (wartości env weź z Lovable Cloud → Secrets)
curl -fsS -H "Authorization: Bearer $SCRAPER_API_TOKEN" "$SCRAPER_BASE_URL/health"
```

- ✅ HTTP 200 + JSON ze statusem `ok`/`healthy`.
- ❌ Jeśli 401/403 — token nieprawidłowy. 5xx — scraper down (poinformuj użytkownika, ale to nie blokuje commita zmian w naszym kodzie, jeśli sama integracja jest poprawna).

**Mini happy-path** (opcjonalnie, gdy zmieniałeś flow startu jobu):
1. Z UI → uruchom wyszukiwanie z minimalnymi parametrami.
2. Sprawdź w `operation_logs` (Lovable Cloud → DB) że pojawił się wpis `operation = 'scrape'`, `level = 'info'`, krok `start`.
3. Job dochodzi do `done` lub `cached` (jeśli cache hit).

---

## 6. Generowanie raportów PDF

Tylko jeśli zmieniałeś `src/server/pdf-report.server.ts`, `src/server/lot-report.ts`, `src/server/report.ts` lub `src/routes/api/reports/pdf.ts`.

```bash
# Zastąp <recordId> realnym ID z tabeli records
curl -fsS "http://localhost:3000/api/reports/pdf?recordId=<recordId>" -o /tmp/report.pdf
file /tmp/report.pdf      # oczekiwane: "PDF document, version 1.x"
ls -lh /tmp/report.pdf    # rozmiar > 1 KB (pusty PDF to znak błędu)
```

- ✅ HTTP 200, plik to prawidłowy PDF.
- ✅ Otwórz w viewerze i sprawdź: nagłówek, dane lota, brak nakładających się elementów, polskie znaki renderują się poprawnie.

---

## 7. Migracje SQL (jeśli dotyczy)

Jeśli dodałeś plik w `supabase/migrations/`:
- ✅ Nazwa: `YYYYMMDDHHMMSS_description.sql` (timestamp w UTC).
- ✅ Każda nowa tabela ma `ENABLE ROW LEVEL SECURITY` + co najmniej jedną politykę.
- ✅ Brak FK do `auth.users` (używaj `profiles`).
- ✅ Brak `CHECK` z funkcjami niedeterministycznymi (`now()`, `current_timestamp`) — używaj triggerów.
- ✅ Brak modyfikacji schematów `auth/storage/realtime/supabase_functions/vault`.
- ✅ Brak `ALTER DATABASE postgres`.
- ✅ Po deployu (Lovable Cloud) — `src/integrations/supabase/types.ts` zaktualizowany automatycznie. Sprawdź że nowe tabele/kolumny w nim są.

---

## 8. Bundle / runtime safety

- ✅ Żadna nowa paczka Node-only (`sharp`, `canvas`, `puppeteer`, `child_process`-zależna). Sprawdź:
  ```bash
  git diff --stat package.json
  ```
- ✅ Żadnego importu `*.server.ts` z plików w `src/components/`, `src/routes/` (poza `src/routes/api/**`), `src/hooks/`:
  ```bash
  rg -n "from.*\.server[\"']" src/components src/hooks src/lib
  rg -n "from.*\.server[\"']" src/routes --glob '!src/routes/api/**'
  ```
  Oczekiwane: 0 wyników.
- ✅ `process.env.X` tylko wewnątrz `.handler()` lub w `*.server.ts`:
  ```bash
  rg -n "process\.env\." src/components src/hooks src/lib src/routes --glob '!src/routes/api/**'
  ```
  Oczekiwane: 0 wyników (poza `import.meta.env.VITE_*` jeśli się trafi).

---

## 9. Sanity-check w przeglądarce

Otwórz preview (lokalnie `http://localhost:3000`, w Lovable: preview URL):
- ✅ Strona główna `/` ładuje się bez błędów w Console (F12).
- ✅ Trasa którą zmieniłeś działa (klik, formularz, submit).
- ✅ Zero błędów 4xx/5xx w zakładce Network dla głównego flow.
- ✅ Brak ostrzeżeń React typu `Each child in a list should have a unique "key"`, `Hydration mismatch`, itp.

---

## 10. Podsumowanie przed commitem

- [ ] Lint + typecheck + format ✅
- [ ] Dev server startuje bez błędów ✅
- [ ] `/api/config` pokazuje wszystkie wymagane env ✅
- [ ] Sekrety nie wyciekają do klienta ✅
- [ ] Endpointy `/api/health`, `/api/config`, `/api/records` zwracają 200 ✅
- [ ] (jeśli dotyczy) Scraper FastAPI odpowiada na `/health` ✅
- [ ] (jeśli dotyczy) PDF generuje się poprawnie ✅
- [ ] (jeśli dotyczy) Migracje SQL zgodne z regułami ✅
- [ ] Brak Node-only paczek / wycieków server kodu do klienta ✅
- [ ] Sanity-check w przeglądarce zielony ✅

Wszystko ✅ → wywołaj `/commit-and-push`.
Cokolwiek ❌ → napraw, NIE commituj.
