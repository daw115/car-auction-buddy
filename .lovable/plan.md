# Plan: Klienci, sprawy i cykliczne monitorowanie

## Cel

Dziś każde wyszukiwanie żyje samodzielnie w tabeli `records` (backend Ubuntu) i luźno w `watch_queue`. Brakuje warstwy „klient → sprawa → wyszukiwania". Chcemy:

1. **CRM-lite**: dodawać i zarządzać klientami (imię, kontakt, notatki).
2. **Sprawy (cases)**: klient może mieć wiele spraw (np. „szukamy Tesli Model 3", „auto rodzinne do 15k"), każda sprawa spina N wyszukiwań/rekordów.
3. **Cykliczny monitoring**: każda sprawa może mieć włączone auto-odświeżanie (co X godzin) — jeśli pojawi się nowy lot w wynikach → powiadomienie + zapis diffu.
4. **Ownership operatorów**: sprawa pokazuje którzy operatorzy (Dawid/Pawel) coś w niej robili (agregat z `searched_by`), z filtrem „moje sprawy".

## Zakres UI

Nowe route'y w istniejącym shellu (sidebar dostaje pozycję **Klienci** [Users]):

| Route | Zawartość |
|---|---|
| `/clients` | Lista klientów: search, sort, badge z liczbą aktywnych spraw i ostatnią aktywnością. CTA „Dodaj klienta". |
| `/clients/$clientId` | Karta klienta: dane kontaktowe, notatki, lista spraw, timeline aktywności. |
| `/clients/$clientId/cases/$caseId` | Widok sprawy: kryteria wyszukiwania (dziedziczone/edytowalne), lista przypiętych wyszukiwań, podgląd nowych lotów od ostatniego uruchomienia, sekcja „Cykliczne odświeżanie" (włącz/wyłącz + częstotliwość), sekcja „Operatorzy" (kto szukał). |
| `/` (Szukaj) | Nowe pole „Sprawa" (opcjonalny select: klient → sprawa). Po submit wyszukiwanie ląduje przypięte do sprawy. |
| `/records` | Filtr `client_id` / `case_id` + kolumna „Sprawa" z linkiem. |

`app-sidebar.tsx` dostaje wpis **Klienci** między „Watchlist" a „Raporty".

## Model danych (Supabase, migracja SQL)

Nowe tabele w `public`:

```sql
-- klienci
create table public.clients_v2 (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  email text,
  phone text,
  notes text,
  created_by text,          -- SITE_USER (Dawid/Pawel)
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- sprawy
create table public.client_cases (
  id uuid primary key default gen_random_uuid(),
  client_id uuid references public.clients_v2(id) on delete cascade,
  title text not null,
  description text,
  default_criteria jsonb,                 -- prefill dla formularza + auto-refresh
  status text default 'open',             -- open | paused | closed
  auto_refresh_enabled boolean default false,
  auto_refresh_interval_hours int default 24,
  last_auto_run_at timestamptz,
  next_auto_run_at timestamptz,
  created_by text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- powiązanie sprawy z rekordem/wyszukiwaniem (record_id = ID z backendu Ubuntu)
create table public.case_searches (
  id uuid primary key default gen_random_uuid(),
  case_id uuid references public.client_cases(id) on delete cascade,
  record_id text not null,                -- id rekordu z Ubuntu /api/records
  searched_by text,                       -- SITE_USER
  new_lot_ids text[] default '{}',        -- loty nowe względem poprzedniego runu (diff)
  created_at timestamptz default now(),
  unique(case_id, record_id)
);

-- indeksy + GRANT + RLS (site_session-based, tak jak dziś w innych tabelach)
```

Migracja dołoży też `GRANT ... TO service_role` (dostęp przez `supabaseAdmin` za `siteSessionGuard`, spójne z istniejącymi endpointami `/api/records`, `/api/config`).

Istniejąca tabela `clients` (5 kolumn) zostaje nietknięta w tej turze — nowy model idzie obok pod nazwą `clients_v2`, żeby uniknąć ryzyka. Migrację danych zaplanujemy osobno.

## Backend (server functions)

Nowy plik `src/functions/clients.functions.ts` (opakowuje `supabaseAdmin` + `siteSessionMiddleware`):

- `listClients`, `getClient(id)`, `createClient`, `updateClient`, `deleteClient`
- `listCases(clientId)`, `getCase(id)`, `createCase`, `updateCase`, `closeCase`
- `attachSearchToCase({ caseId, recordId })` — używane po zakończeniu joba
- `listCaseSearches(caseId)` — łączy `case_searches` + wywołuje `backendGetRecord` per record_id
- `getCaseOperators(caseId)` — agreguje distinct `searched_by` z `case_searches`
- `toggleCaseAutoRefresh({ caseId, enabled, intervalHours })`
- `runCaseAutoRefreshNow(caseId)` — uruchamia scrape z `default_criteria`, porównuje wynik z ostatnim, zapisuje `new_lot_ids`

Rozszerzenie istniejących flow:

- `POST /api/search` (istnieje jako proxy) — dokładamy opcjonalny `case_id` w payloadzie; po sukcesie wołamy `attachSearchToCase`.
- `queue.functions.ts` (istniejący watch queue) zostaje jako niższa warstwa; auto-refresh sprawy jest jej nadbudową (jedna sprawa = jeden watch skorelowany z `case_id`).

## Cykliczny scheduler

`pg_cron` w Supabase (znany wzorzec z `cleanup-logs`):

```sql
select cron.schedule(
  'cases-auto-refresh',
  '*/15 * * * *',
  $$ select net.http_post(
       url:='https://project--edf9b460-b0a8-4a4d-baf9-8b64e6cbcb5c.lovable.app/api/public/hooks/cases-refresh',
       headers:='{"Content-Type":"application/json","apikey":"<anon>"}'::jsonb,
       body:='{}'::jsonb
     ); $$
);
```

Nowy public hook `src/routes/api/public/hooks/cases-refresh.ts`:

- Wyciąga sprawy gdzie `auto_refresh_enabled = true AND next_auto_run_at <= now()`.
- Dla każdej: uruchamia `backendSearch(default_criteria)` (fire-and-forget lub z krótkim pollingiem), zapisuje nowy `record_id` w `case_searches`, liczy diff nowych lot_id vs poprzedni run, ustawia `last_auto_run_at` i `next_auto_run_at = now() + interval_hours`.
- Bez PII w response, weryfikacja `apikey`.

Powiadomienia w UI: badge „🆕 N nowych" na karcie sprawy + panel „Ostatni auto-run" z listą nowych lotów (klik → RecordDetailView).

## Ownership operatorów

- `searched_by` już leci do backendu (istnieje) — teraz kopiujemy je również do `case_searches.searched_by` przy attach.
- Na widoku sprawy sekcja „Operatorzy" pokazuje avatary/inicjały (Dawid, Pawel) z liczbą wyszukiwań i datą ostatniej aktywności.
- Na `/clients` filtr „Tylko moje" = `getCurrentSiteUser()` w `client_cases.created_by` OR distinct z `case_searches.searched_by`.
- W `/records` dodajemy kolumnę „Sprawa" oraz łańcuch: klient → sprawa → operator.

## Kolejność wdrożenia (do zrobienia po zaakceptowaniu planu)

1. **Migracja SQL** (`clients_v2`, `client_cases`, `case_searches`, GRANT, RLS, indeksy) — jeden plik migracji.
2. **Server functions** `clients.functions.ts` + rozszerzenie `POST /api/search` o `case_id`.
3. **UI**: `/clients` (lista + dialog dodawania), `/clients/$clientId` (detal + sprawy), `/clients/$clientId/cases/$caseId` (widok sprawy).
4. Integracja z formularzem wyszukiwania (`src/routes/index.tsx`): select „Sprawa" + prefill `default_criteria`.
5. Panel „Operatorzy" i badge nowych lotów na karcie sprawy.
6. **Cykliczny hook** `api/public/hooks/cases-refresh.ts` + `pg_cron` (SQL przez `supabase--insert`, nie migracja — zawiera URL i klucz).
7. Wpis **Klienci** w `app-sidebar.tsx`, kolumna „Sprawa" w `/records`.
8. Testy: unit dla helperów diff-owych (`computeNewLotIds`), integracyjny dla `attachSearchToCase`.

## Poza zakresem tej tury

- Migracja danych ze starej tabeli `clients` do `clients_v2`.
- Powiadomienia e-mail/push (na razie tylko in-app badge).
- Uprawnienia per operator (kto może edytować cudze sprawy) — wszyscy zalogowani widzą wszystko, tak jak dziś dla rekordów.
- Zmiana kontraktu backendu Ubuntu — cała warstwa klient/sprawa jest w Supabase, backend nadal dostaje tylko `criteria` + `searched_by` + opcjonalnie `case_id` w metadanych.

## Pytania otwarte

- Czy sprawa powinna mieć **jeden zestaw kryteriów** (auto-refresh używa jednego) czy **wiele wariantów** (np. 3 różne max_budgets)? Domyślnie idę w wariant „jeden `default_criteria`" — ręczne uruchomienia mogą użyć innych.
- Częstotliwość auto-refresh: `24h` jako default, min `6h`, max `168h` (tydzień). OK?
