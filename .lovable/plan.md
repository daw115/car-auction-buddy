## Cel

Wywołanie Anthropic w `callAnthropic()` jest obecnie zwykłym `fetch()` bez timeoutu. Cloudflare Worker / proxy zamyka połączenie po ~100 s i klient widzi `Anthropic HTTP 524`. Chcemy przerwać request po naszej stronie wcześniej (~110 s — z marginesem względem limitu CF) i zwrócić zrozumiały komunikat zamiast surowego 524.

## Zakres

Zmieniony **tylko jeden plik**: `src/server/anthropic.server.ts`.

Bez zmian w:
- kontrakcie funkcji `callAnthropic` (te same argumenty i typ zwracany),
- `src/server/api.functions.ts`, `src/server/lot-report.ts`, `src/server/report.ts`,
- modelu, `max_tokens`, nagłówkach, prompt cachingu.

## Co dokładnie się zmienia

W bloku wykonującym `fetch` w `callAnthropic`:

1. Tworzony jest `AbortController` i `setTimeout(() => ctrl.abort(), 110_000)`.
2. `fetch` dostaje `signal: ctrl.signal`.
3. `try / catch / finally`:
   - `catch` rozpoznaje `AbortError` i rzuca: `Anthropic timeout po 110s — model nie zdążył odpowiedzieć. Spróbuj ponownie lub zmniejsz prompt/max_tokens.`
   - inne błędy sieciowe są re-throw bez zmian (zachowujemy obecne zachowanie),
   - `finally` zawsze robi `clearTimeout(timer)` (brak wycieku timera po sukcesie).
4. Pozostała obsługa odpowiedzi (`!res.ok` → `Anthropic HTTP ${status}: ...`, parsowanie JSON, mapowanie na `AnthropicResult`) bez zmian.

## Dlaczego 110 s

- Limit CF dla pojedynczego sub-requestu daje błąd 524 około 100 s.
- 110 s zostawia margines, żeby:
  - nasz `AbortError` zadziałał *zanim* CF wstrzyknie HTML 524,
  - logi w `operation_logs` (`ai_analysis · anthropic_call`) pokazały sensowną przyczynę (`Anthropic timeout po 110s ...`) zamiast `Anthropic HTTP 524: error code: 524`.

## Co świadomie pomijamy w tej zmianie

Aby zminimalizować ryzyko regresji, w tym kroku **nie** ruszamy:
- streamingu (`stream: true`) — wymaga osobnej logiki SSE i zmiany kontraktu,
- automatycznego retry / backoff dla 5xx,
- domyślnego `max_tokens` (zostaje 8192),
- domyślnego modelu.

Jeśli po wdrożeniu timeouty będą się powtarzać przy długich generacjach, kolejnym krokiem będzie streaming + obniżenie domyślnego `max_tokens`. To zostawiamy do osobnego release’u.

## Weryfikacja po wdrożeniu

1. Wywołanie analizy ofert z dużym promptem — gdy Anthropic odpowiada szybko, zachowanie bez zmian (sukces, ten sam `AnthropicResult`).
2. Gdy Anthropic „wisi” > 110 s: w UI / `operation_logs` pojawia się `error · ai_analysis · anthropic_call` z komunikatem `Anthropic timeout po 110s ...`, a nie `HTTP 524`.
3. Brak wycieków timerów (sprawdzane przez `finally { clearTimeout(timer) }`).

## Pliki

- **Edycja:** `src/server/anthropic.server.ts` (linie obejmujące `fetch(...)` i obsługę `!res.ok`).
- Brak nowych plików, brak nowych zależności, brak migracji DB, brak zmian w sekretach.
