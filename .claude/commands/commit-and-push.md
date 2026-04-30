# /commit-and-push

Slash-command dla Claude Code. Wywołanie: `/commit-and-push` (opcjonalnie z krótką notką, np. `/commit-and-push poprawiłem cache key`).

---

## Cel

Po zakończeniu zadania: zsynchronizować z `origin/main`, stworzyć commit zgodny z konwencją z `CLAUDE.md` (sekcja 6 → "Konwencja commitów") i wypchnąć na `main`.

## Krok po kroku

1. **Sprawdź stan repo:**
   ```bash
   git status --short
   git diff --stat
   ```
   Jeśli brak zmian — zatrzymaj się i poinformuj użytkownika.

2. **Zsynchronizuj z remote** (Lovable mógł dopisać commit):
   ```bash
   git fetch origin
   git pull --rebase origin main
   ```
   Jeśli konflikt — rozwiąż go (preferuj zachowanie obu zmian, dopytaj jeśli niejednoznaczne), a następnie `git rebase --continue`.

3. **Wybierz `type` i `scope`** na podstawie zmienionych plików:

   | Zmienione pliki | Sugerowany type/scope |
   |---|---|
   | `supabase/migrations/*.sql` | `db(<obszar>)` |
   | `src/routes/*.tsx`, `src/components/**` | `feat(ui)` lub `fix(ui)` |
   | `src/server/*.functions.ts` | `feat(api)` / `fix(api)` |
   | `src/server/anthropic.server.ts`, `src/server/prompts/**` | `feat(ai)` / `fix(ai)` |
   | `src/server/pdf-report.server.ts`, `src/routes/api/reports/**` | `feat(pdf)` / `fix(pdf)` |
   | `package.json`, `bun.lockb` | `chore(deps)` |
   | `vite.config.ts`, `tsconfig.json`, `wrangler.jsonc` | `chore(config)` |
   | `CLAUDE.md`, `README.md` | `docs(claude)` / `docs(readme)` |

4. **Sformułuj wiadomość commita** (tryb rozkazujący, max 72 znaki w pierwszej linii):
   ```
   <type>(<scope>): <opis>

   <opcjonalne body wyjaśniające DLACZEGO>
   ```

5. **Commit + push:**
   ```bash
   git add -A
   git commit -m "<type>(<scope>): <opis>"
   git push origin main
   ```

6. **Jeśli push odrzucony** (`non-fast-forward`):
   ```bash
   git pull --rebase origin main
   git push origin main
   ```
   **Nigdy** `git push --force` na `main`.

7. **Po sukcesie** — krótko potwierdź użytkownikowi: hash commita + jednolinijkowy opis.

## Czego NIE robić

- Nie commituj jeśli build/typecheck nie przechodzi — najpierw napraw.
- Nie kumuluj kilku niepowiązanych zmian w jednym commicie. Rozdziel: najpierw `db(...)`, potem `feat(...)`, potem `docs(...)`.
- Nie commituj `.env`, `node_modules/`, `dist/`, `.lovable/`.
- Nie używaj generycznych wiadomości (`update`, `wip`, `fix stuff`).
- Nie pushuj na inne branche niż `main` chyba że użytkownik wyraźnie poprosi.

## Przykłady dobrych wiadomości

```
feat(scraper): add cancel button to status panel
fix(cache): include damage filter in cache key hash
db(watchlist): add user_id index on watchlist_items
refactor(api): extract scraper polling into separate function
docs(claude): document commit convention and push workflow
chore(deps): bump @tanstack/react-start to 1.168
```
