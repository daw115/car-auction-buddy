## Cel

Obecny `/` mieści wszystko (formularz wyszukiwania, status job-a, wyniki, watchlist-skróty, panel rekordów backendu, audyt, raporty, ustawienia) — ponad 3900 linii w jednym pliku, bez wyraźnej hierarchii. Po zmianie użytkownik wchodzi w konkretną sekcję z sidebara, każdy ekran robi jedną rzecz, a wygląd dostaje świeższą warstwę wizualną przy zachowaniu obecnej palety (operator-blue/cream).

## Nowy układ aplikacji

```text
┌─────────────────────────────────────────────────────────┐
│ Sidebar (collapsible=icon)        Topbar: breadcrumb,   │
│  • Szukaj          [Search]       active job pill,      │
│  • Aktywne joby    [Activity]     theme, user, settings │
│  • Wyniki / Rekordy[Database]    ─────────────────────  │
│  • Watchlist       [Bookmark]                           │
│  • Raporty         [FileText]     <Outlet />            │
│  • Audyt           [ShieldCheck]                        │
│  • Logi (dev)      [Terminal]                           │
│  • Kalkulator      [Calculator]                         │
│  • Ustawienia      [Settings]                           │
└─────────────────────────────────────────────────────────┘
```

`ResumeJobBanner` i `ActiveJobsPanel` migrują do topbara jako kompaktowy „pill" + drawer — przestają zajmować miejsce na każdym ekranie.

## Route'y po podziale

| Route | Zawartość (wyciągane z `Panel()` w `src/routes/index.tsx`) |
|---|---|
| `/` (Szukaj) | Tylko formularz wyszukiwania + „Parse client message" + ostatni status uruchomionego job-a. Krótkie podsumowanie wyników → CTA „Zobacz w rekordach". |
| `/jobs` | `ActiveJobsPanel`, `BatchJobCard`, `LiveJobLogs`, `ScraperProgress`, `AnalysisProgress`. |
| `/records` | `BackendRecordsPanel` + `RecordDetailView` w split-pane (lista po lewej, detal po prawej). Dziś już istnieje `database.tsx` — zamieniamy go w pełnoprawny widok rekordów. |
| `/reports` | `ScraperReportsSection` + `ReportUrlsPanel` (broker_bundle, client_bundle itp.) jako galeria kart per job. |
| `/audit` | `SearchAuditPanel` z filtrami. |
| `/watchlist` | Istnieje, zostaje. |
| `/calculator`, `/settings`, `/dev/logs` | Istnieją, dostają tylko nowy chrome. |

`PasswordGate` zostaje bez zmian funkcjonalnie — tylko delikatny refresh wizualny (mniejsza diagnostyka schowana pod `<details>`).

## Odświeżenie wizualne

- **Layout shell**: `SidebarProvider` + `AppSidebar` w `__root.tsx`, `SidebarTrigger` w topbarze (zawsze widoczny, sidebar `collapsible="icon"`).
- **Typografia**: nagłówki sekcji `text-2xl font-semibold tracking-tight`, opisy `text-sm text-muted-foreground`. Spójna struktura każdej strony: `PageHeader` (tytuł + opis + akcje po prawej) → content w `Card`.
- **Tokeny** (`src/styles.css`, oklch): dorzucam `--surface-elevated`, `--surface-muted`, subtelny `--shadow-card`, akcent statusu (`--success`, `--warning`) — bez zmiany istniejących `--primary/--background`.
- **Karty**: zaokrąglenie `rounded-xl`, cieniem `shadow-sm`, hover `shadow-md` na klikalnych. Lista rekordów: zebra + status badge po lewej.
- **CTA hierarchy**: jeden primary button per sekcja (np. „Uruchom wyszukiwanie"), reszta `variant="outline"` / `"ghost"`. Dziś wszystkie przyciski wyglądają tak samo.
- **Status pill w topbarze**: gdy job działa — pulsujący kolor + nazwa + link „Pokaż" do `/jobs`.

## Szczegóły techniczne

- Nowe pliki:
  - `src/components/app-sidebar.tsx` — `Sidebar` wg wzoru z knowledge file, `Link` + `useRouterState` dla active state.
  - `src/components/app-topbar.tsx` — breadcrumb (z `useRouterState`), `ActiveJobPill`, `ThemeToggle`, menu profilu.
  - `src/components/page-header.tsx` — reużywalny header (`title`, `description`, `actions`).
  - `src/components/active-job-pill.tsx` — wyciągnięte z `ActiveJobsPanel`, używa już istniejącego `listActiveScraperJobs`.
  - `src/routes/jobs.tsx`, `src/routes/records.tsx` (zamiana `database.tsx`), `src/routes/reports.tsx`, `src/routes/audit.tsx`.
- Refactor `src/routes/index.tsx`:
  - `Panel()` zostaje tylko z formularzem i krótkim podsumowaniem ostatniego job-a.
  - Wyekstrahowane komponenty (`BackendRecordsPanel`, `RecordDetailView`, `ScraperReportsSection`, `SearchAuditPanel`, `ActiveJobsPanel`, `BatchJobCard`) przenoszę do `src/components/panels/` i importuję w nowych route'ach. Zachowuję sygnatury propsów, żeby nie ruszać logiki.
- `__root.tsx`:
  - Wrap `Outlet` w `SidebarProvider` → `<div className="flex min-h-screen w-full">` → `<AppSidebar />` + kolumna `<AppTopbar />` + `<main className="flex-1 p-6">{children}</main>`.
  - `PasswordGate` zostaje na zewnątrz shell-a (jak dziś), żeby nie renderować sidebara dla niezalogowanych.
- Stan globalny job-a: lekki context `ActiveJobContext` (zasilany istniejącym pollingiem) wystawiany przez topbar — żeby przejście między route'ami nie gubiło info o trwającym scrape.
- Bez zmian backendowych: żadne `server functions`, schema DB, ani kontrakt API nie są dotykane. To wyłącznie reorganizacja front-endu + nowe tokeny CSS.
- Trasy są typowane — `routeTree.gen.ts` przegeneruje się sam.

## Czego NIE zmieniam

- Logiki scrapera, AI, raportów, cache'u, watchlisty.
- Kontraktu `POST /api/search` ani `pollScraperJob`.
- `PasswordGate` (poza drobnym refreshem wizualnym i ukryciem diagnostyki za `<details>`).
- Istniejących route'ów `calculator`, `settings`, `watchlist`, `dev.logs` — tylko nowy chrome wokół nich.

## Kolejność wdrożenia

1. Tokeny CSS + `PageHeader` + sidebar/topbar shell w `__root.tsx`.
2. Wydzielenie paneli z `index.tsx` do `src/components/panels/` (bez zmian zachowania).
3. Nowe route'y `jobs`, `records`, `reports`, `audit` — każdy montuje swój panel + `PageHeader`.
4. Slim-down `Panel()` w `index.tsx` do formularza + krótkiego podsumowania.
5. `ActiveJobPill` w topbarze + `ActiveJobContext`.
6. QA wizualne na obecnym viewport (857×593) i desktop 1440.
