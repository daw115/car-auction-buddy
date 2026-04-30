## Zakres rozwoju USA Car Scout (wszystko darmowe, bez własnego scrapera)

Skupiamy się na 4 modułach funkcjonalnych zgodnie z wyborem. Wszystko działa w obrębie Lovable Cloud — bez zewnętrznego hostingu, bez płatnych API.

---

### Moduł 1 — Eksport PDF + wysyłka maili

**Co użytkownik dostaje:**
- W każdym widoku raportu (broker / klient TOP3+2) nowy przycisk **"Pobierz PDF"** generujący prawdziwy PDF (nie tylko HTML).
- Przycisk **"Wyślij do klienta"** otwierający modal: wybór klienta z bazy → preview tematu i treści → wysyłka. Mail przychodzi z Twojego brandowanego adresu (np. `oferty@usacarscout.com`).
- W rekordach (`records`) zapisywany status wysyłki: kiedy, na jaki adres, czy doszło, czy klient otworzył.

**Pod spodem:**
- PDF generowany server-side przez `@react-pdf/renderer` w nowym server function `renderPdf` (Worker-compatible, działa bez Chromium).
- Nowy template `src/server/pdf/lot-report.tsx` mapujący strukturę z `lot-report.ts` na komponenty PDF (Page/View/Text/Image) — zachowuje brandowany layout.
- Maile przez **Lovable Emails** (wbudowane, zero konfiguracji, darmowe). Wymagana konfiguracja domeny nadawczej → tu pojawi się dialog `<lov-open-email-setup>`.
- Nowa tabela `email_sends` (record_id, client_id, recipient, sent_at, status, message_id) + log w `operation_logs`.
- Template React Email `client-offer.tsx` z embedded HTML raportu klienta + linkiem do PDF (PDF jako Storage URL, bo email attachments nie są wspierane).
- Nowy bucket Supabase Storage `reports/` (publiczny, signed URLs 7-dniowe) na PDF-y.

---

### Moduł 2 — VIN decoder (NHTSA) + kalkulator total cost

**Co użytkownik dostaje:**
- Na karcie pojedynczego lota (i w widoku ręcznego wprowadzania) nowe pole VIN z przyciskiem **"Dekoduj VIN"** → auto-uzupełnienie marki, modelu, rocznika, silnika, skrzyni, body type, fuel type, country of origin. Plus lista recall'i NHTSA.
- Nowa zakładka **Kalkulator** w lewym panelu (obok Klienci/Rekordy) — narzędzie standalone:
  - Input: cena auta (USD), stan USA, masa, pojemność silnika, paliwo
  - Output: rozbicie kosztów (transport per stan, cło 10%, akcyza 3.1%/18.6%, VAT 23%, opłaty portowe, marża brokera %, łącznie PLN/EUR)
  - Zapisywane presety per klient.
- W analizie AI każdy lot dostaje wyliczony **total cost PL** (nie tylko `estimated_total_cost_usd` z AI, ale deterministyczny kalkulator).

**Pod spodem:**
- Nowy server function `decodeVin` → `https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json` (darmowe, bez klucza, bez limitów).
- Recall check: `https://api.nhtsa.gov/recalls/recallsByVehicle?make=X&model=Y&modelYear=Z`.
- Nowy plik `src/lib/cost-calculator.ts` z czystymi funkcjami (transport per stan ze stałych, akcyza wg pojemności silnika, VAT, kurs USD→PLN→EUR z `https://api.frankfurter.app/latest?from=USD` — darmowe).
- Nowa tabela `cost_presets` (id, client_id, broker_margin_pct, transport_override, exchange_rate_buffer_pct, updated_at).
- Komponent `<CostBreakdown lot={...} />` używany w widoku raportu i kalkulatorze.

---

### Moduł 3 — Watchlist + alerty + porównywarka

**Co użytkownik dostaje:**
- Na każdym locie w analizie przycisk **"Dodaj do watchlist"** (gwiazdka).
- Nowa zakładka **Watchlist** — lista śledzonych lotów (per klient lub globalnie) z aktualnym scoringiem AI, czasem do końca aukcji, ostatnią zmianą bidu.
- Cron co X godzin (konfigurowalne 2/6/12/24h w settings) ponownie wywołuje AI analizę dla każdego lota z watchlisty. Jeśli `score` wzrósł o ≥1.0 lub bid spadł — wysyła alert mailowy do brokera.
- Tryb **Porównaj** — checkbox przy każdym locie, max 3 zaznaczone → przycisk "Porównaj" otwiera widok side-by-side: tabela z wszystkimi parametrami + AI verdict + total cost + zdjęcie obok zdjęcia.

**Pod spodem:**
- Nowa tabela `watchlist` (id, client_id, lot_snapshot jsonb, current_score, last_bid_usd, last_checked_at, alert_threshold, created_at, removed_at).
- Nowa tabela `watchlist_history` (watchlist_id, checked_at, score, bid_usd, ai_summary) — do wykresu trendu.
- pg_cron + pg_net wywołuje endpoint `/api/public/hooks/refresh-watchlist` co 6h (default), endpoint iteruje aktywne wpisy, wywołuje istniejący `runAi` na pojedynczych lotach, porównuje, zapisuje history, wysyła mail jeśli próg przekroczony.
- Mail-alert jako transactional template `watchlist-alert.tsx`.
- Komponent `src/components/CompareView.tsx` + nowy route `/compare?ids=lot1,lot2,lot3`.
- **Ograniczenie**: bez własnego scrapera nie mamy świeżych danych z aukcji — alert opiera się na PONOWNEJ analizie AI tego samego snapshotu (zmienia się tylko jeśli zmienisz prompt/model). Realny "auto-refresh bid" wymaga scrapera. **Sugeruję alternatywę**: alert uruchamia się gdy ręcznie wkleisz nowy snapshot tego samego lot_id — system wykryje zmianę i powiadomi.

---

### Moduł 4 — Dashboard analityczny

**Co użytkownik dostaje:**
- Nowa zakładka **Dashboard** (`/dashboard`) — pierwszy widok po wejściu w aplikację (zamiast pustego panelu):
  - KPI cards: liczba analiz (7d/30d/all), liczba klientów, liczba zapisanych rekordów, średni AI score, średni szacowany koszt importu.
  - Wykres liniowy: liczba analiz w czasie (ostatnie 30 dni).
  - Wykres słupkowy: TOP 10 marek po liczbie analiz.
  - Wykres kołowy: rozkład rekomendacji AI (POLECAM/RYZYKO/ODRZUĆ).
  - Tabela: TOP 10 najczęstszych red flagów + ile razy wystąpiły.
  - Per-klient: sortowalna lista klientów z liczbą analiz, średnim score, ostatnią aktywnością.

**Pod spodem:**
- Server function `getDashboardStats` (filtry: timeframe, client_id) — robi agregacje SQL na `records` + `analysis` jsonb.
- Komponent `src/routes/dashboard.tsx` używający `recharts` (już dostępny w shadcn).
- Materialized view `dashboard_stats_mv` z refresh co godzinę (pg_cron) — żeby nie liczyć wszystkiego live przy każdym wejściu.
- Reorganizacja routera: `/` → przekierowanie na `/dashboard`, panel operacyjny przenosimy na `/workspace`.

---

### Migracje DB (jedna do zatwierdzenia)

```text
NEW TABLES:
- email_sends (record_id, client_id, recipient, status, message_id, sent_at, opened_at)
- cost_presets (id, client_id, broker_margin_pct, transport_overrides jsonb, ...)
- watchlist (id, client_id, lot_snapshot jsonb, current_score, last_bid_usd, last_checked_at, alert_threshold)
- watchlist_history (watchlist_id, checked_at, score, bid_usd, ai_summary)

NEW STORAGE BUCKET:
- reports (public, signed URLs)

NEW MATERIALIZED VIEW:
- dashboard_stats_mv (refresh co 1h)

NEW CRON JOBS:
- refresh-watchlist (co 6h, konfigurowalne w app_config)
- refresh-dashboard-stats (co 1h)
```

RLS: aplikacja jest single-operator (bez auth) — wszystkie tabele dostają politykę `public read/write` jak istniejące. Storage bucket `reports` publiczny (signed URL → bezpieczne).

---

### Kolejność wdrożenia (4 osobne kroki, każdy weryfikowalny)

1. **Moduł 1** (PDF + mail) — najwięcej setupu (domena email), największa wartość biznesowa. Wymaga dialogu konfiguracji domeny nadawczej.
2. **Moduł 2** (VIN + kalkulator) — całkowicie izolowany, zero zależności, szybka iteracja.
3. **Moduł 4** (Dashboard) — wymaga danych z modułów 1+2, naturalne miejsce na aggregację.
4. **Moduł 3** (Watchlist) — najbardziej złożony (cron, alerty), z zastrzeżeniem o ograniczeniu refresh bidu.

Po każdym kroku możesz przetestować zanim przejdę do następnego.

---

### Czego ŚWIADOMIE nie robimy

- ❌ Własnego scrapera Copart/IAAI (na Workerach niewykonalne — brak Playwright/Chromium, agresywne anti-bot)
- ❌ Firecrawl (Twój wybór "pomiń scraping")
- ❌ Płatnych API (wszystko free tier: NHTSA bez klucza, Frankfurter bez klucza, Lovable AI w cenie planu, Lovable Emails w cenie planu)
- ❌ Multi-user auth (zachowujemy single-operator zgodnie z `.lovable/plan.md`)

### Pierwsze pytanie po zatwierdzeniu

Zanim wystartuję z Modułem 1, zapytam Cię o domenę nadawczą email (np. `notify.usacarscout.com`) i otworzę dialog konfiguracji DNS. Bez tego mail nie wyjdzie.