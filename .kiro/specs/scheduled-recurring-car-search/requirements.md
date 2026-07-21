# Requirements Document

## Introduction

Operatorzy `car-auction-buddy` dziś muszą ręcznie klikać „🔎 Wyszukaj” każdy raz, gdy chcą sprawdzić
nowe oferty dla tego samego auta (te samo kryteria: marka/model/rocznik/budżet/przebieg/paliwo/typy
uszkodzeń/źródła). Ta funkcja pozwala skonfigurować **zaplanowane wyszukiwanie cykliczne** — te same
kryteria co w zwykłym wyszukiwaniu, wykonywane automatycznie w regularnych odstępach czasu (np.
codziennie, co 6h), bez interakcji użytkownika, z wynikami widocznymi jako rekordy w historii.

W repozytorium istnieje już zbliżony mechanizm: `src/functions/queue.functions.ts` +
`src/server/scraper-queue.server.ts` (`createQueueWatch` / `listQueueWatches` / `deleteQueueWatch`),
z polami `interval_hours`, `next_run_at`, `runs_count`, `label`, `status`. Jest on jednak dziś
przeznaczony do innego celu biznesowego — **retry przy braku wyników** (`docs/app-overview.md`:
„kolejka ponownych sprawdzeń (gdy brak wyników) z powiadomieniem na Telegram”) — i komunikuje się
bezpośrednio z `SCRAPER_BASE_URL/api/queue`, **z pominięciem** ujednoliconego transportu
(`src/server/backend-transport.server.ts`) używanego przez `backendSearch`/`backendSearchBatch`.
Zgodnie z decyzją podjętą przy zbieraniu wymagań, ta funkcja **rozszerza** istniejący mechanizm
kolejki (zamiast budować równoległy, niezależny system) i **przełącza jego transport** na
ujednolicony selektor Ubuntu/legacy, dodając niezależną od wyników semantykę „szukaj cyklicznie” obok
istniejącej semantyki „powtarzaj aż znajdziesz coś”.

`docs/ubuntu-api-contract.md` oznacza `/watchlist` i `/queue` jako `blocked-by-backend-discovery` —
nie ma potwierdzenia, że backend Ubuntu FastAPI oferuje odpowiednik tego, co dziś robi legacy
`SCRAPER_BASE_URL/api/queue`. To jest otwarta niewiadoma backendowa i jest opisana w sekcji
„Decyzje i niewiadomości do potwierdzenia” poniżej — wymagania w tym dokumencie definiują zachowanie
GUI (Lovable BFF) niezależnie od tego, która opcja zostanie wybrana, oraz definiują zachowanie
degradacji, gdy zdolność wykonawcza (execution engine) nie jest jeszcze dostępna.

## Glossary

- **GUI**: Aplikacja Lovable/TanStack Start (`car-auction-buddy`) — frontend + server functions
  (`src/functions/*.functions.ts`) działające jako BFF (Backend-For-Frontend) w Cloudflare Workers.
- **Site_User**: Zalogowany operator GUI, zidentyfikowany przez `siteSessionMiddleware`
  (`session.sub`, jedna z wartości `SITE_USERS`). Wszystkie operacje na Scheduled_Search wymagają
  aktywnej sesji Site_User.
- **Backend**: Zewnętrzny serwis FastAPI wykonujący faktyczne wyszukiwanie ofert (Copart/IAAI/Manheim)
  i analizę AI — adresowany wyłącznie przez Backend_Transport, nigdy bezpośrednio z klienta.
- **Backend_Transport**: Ujednolicony, server-only selektor transportu (`src/server/backend-transport.server.ts`)
  wybierający między Backend Ubuntu (za Cloudflare Access) i legacy Backend (`API_BASE_URL`), fail-closed
  przy częściowej konfiguracji, bez runtime fallbacku między transportami.
- **Search_Criteria**: Zestaw kryteriów wyszukiwania — `make`, `model`, `year_from`, `year_to`,
  `budget_usd`, `max_odometer_mi`, `fuel_type`, `excluded_damage_types`, `max_results`, `sources` —
  zgodny z `ClientCriteria` (`src/lib/types.ts`) i `criteriaSchema` (`src/lib/criteria-schema.ts`).
- **Scheduled_Search**: Zapisana konfiguracja cyklicznego wyszukiwania — Search_Criteria + częstotliwość
  (`interval_hours`) + stan (`enabled`/`disabled`) + metadane wykonań (`next_run_at`, `last_run_at`,
  `runs_count`, `last_result_count`) + właściciel (Site_User, który utworzył wpis).
- **Scheduled_Search_Manager**: Warstwa GUI (server functions + walidacja) odpowiedzialna za tworzenie,
  edycję, włączanie/wyłączanie, usuwanie i listowanie Scheduled_Search, zawsze przez Backend_Transport.
- **Schedule_Execution**: Pojedyncze wykonanie Scheduled_Search — wywołanie wyszukiwania z zapisanymi
  Search_Criteria, którego wynik jest widoczny jako rekord w historii (Search_Record).
- **Search_Record**: Istniejący rekord wyszukiwania w Backend (`/api/records/{id}`, `BackendRecord`),
  zawierający wyniki, status i artefakty raportów jednego wykonania wyszukiwania.
- **Legacy_Retry_Queue**: Istniejący mechanizm `queue.functions.ts` / `scraper-queue.server.ts`,
  którego bieżąca semantyka to powtarzanie wyszukiwania **do momentu znalezienia pierwszego wyniku**
  (nie: „zawsze co X godzin niezależnie od wyniku”), z powiadomieniem Telegram po sukcesie.
- **Notification_Channel**: Opcjonalny kanał powiadomień o nowych wynikach Schedule_Execution (np.
  istniejąca integracja Telegram).
- **Max_Active_Schedules**: Skonfigurowany górny limit liczby jednocześnie aktywnych (`enabled`)
  Scheduled_Search przypadających na jednego Site_User.

## Requirements

### Requirement 1: Tworzenie zaplanowanego wyszukiwania

**User Story:** Jako operator, chcę zapisać kryteria wyszukiwania konkretnego auta jako zaplanowane
wyszukiwanie cykliczne, żeby nie musieć ręcznie klikać „Szukaj” za każdym razem.

#### Acceptance Criteria

1. WHEN Site_User przesyła żądanie utworzenia Scheduled_Search z Search_Criteria spełniającymi
   `criteriaSchema` i częstotliwością w zakresie 1–168 godzin (Wymaganie 5.1), THE
   Scheduled_Search_Manager SHALL zapisać nowy Scheduled_Search ze stanem `enabled` i przypisanym
   właścicielem równym temu Site_User.
2. IF żądanie utworzenia Scheduled_Search zawiera Search_Criteria niespełniające `criteriaSchema`
   (np. brak `make`, `sources` poza dozwolonym zbiorem), THEN THE Scheduled_Search_Manager SHALL
   odrzucić żądanie i zwrócić błąd walidacji wskazujący nieprawidłowe pole.
3. WHEN Scheduled_Search zostaje utworzony, THE Scheduled_Search_Manager SHALL ustawić `next_run_at`
   równe chwili utworzenia plus `interval_hours` godzin podanej częstotliwości.
4. IF Site_User osiągnął już Max_Active_Schedules aktywnych Scheduled_Search, THEN THE
   Scheduled_Search_Manager SHALL odrzucić żądanie utworzenia nowego `enabled` Scheduled_Search i
   zwrócić błąd wskazujący przekroczony limit.
5. IF żądanie utworzenia Scheduled_Search narusza jednocześnie `criteriaSchema` lub zakres
   częstotliwości (Wymaganie 5.2) ORAZ limit Max_Active_Schedules, THEN THE Scheduled_Search_Manager
   SHALL zwrócić błąd walidacji danych wejściowych (kryterium 2 / Wymaganie 5.2) bez sprawdzania
   limitu Max_Active_Schedules, tak że błąd walidacji ma pierwszeństwo przed błędem limitu.

### Requirement 2: Edycja zaplanowanego wyszukiwania

**User Story:** Jako operator, chcę zmienić kryteria lub częstotliwość istniejącego zaplanowanego
wyszukiwania, żeby dostosować je bez usuwania i tworzenia od nowa.

#### Acceptance Criteria

1. WHEN Site_User przesyła żądanie edycji istniejącego Scheduled_Search z Search_Criteria
   spełniającymi `criteriaSchema` i/lub częstotliwością w zakresie 1–168 godzin (Wymaganie 5.1), THE
   Scheduled_Search_Manager SHALL zapisać zaktualizowane Search_Criteria i/lub częstotliwość dla tego
   Scheduled_Search.
2. IF żądanie edycji odnosi się do Scheduled_Search, który nie istnieje, THEN THE
   Scheduled_Search_Manager SHALL zwrócić błąd „nie znaleziono” bez modyfikacji żadnych danych.
3. IF żądanie edycji istniejącego Scheduled_Search zawiera Search_Criteria niespełniające
   `criteriaSchema` lub częstotliwość poza zakresem 1–168 godzin, THEN THE Scheduled_Search_Manager
   SHALL odrzucić żądanie, zwrócić błąd walidacji wskazujący nieprawidłowe pole i nie zmodyfikować
   żadnych danych tego Scheduled_Search.
4. WHEN częstotliwość Scheduled_Search zostaje zmieniona podczas edycji, THE Scheduled_Search_Manager
   SHALL przeliczyć `next_run_at` równe chwili edycji plus nowa liczba godzin częstotliwości,
   niezależnie od tego, czy Scheduled_Search jest w stanie `enabled` czy `disabled`.
5. THE Scheduled_Search_Manager SHALL zapewnić, że dla każdej udanej edycji Scheduled_Search
   późniejsze odczytanie tego Scheduled_Search zwraca Search_Criteria i częstotliwość równe
   wartościom przesłanym w tym żądaniu edycji.

### Requirement 3: Usuwanie zaplanowanego wyszukiwania

**User Story:** Jako operator, chcę usunąć zaplanowane wyszukiwanie, którego już nie potrzebuję, żeby
przestało się wykonywać.

#### Acceptance Criteria

1. WHEN Site_User przesyła żądanie usunięcia istniejącego Scheduled_Search, THE
   Scheduled_Search_Manager SHALL usunąć ten Scheduled_Search i zaprzestać planowania jego przyszłych
   Schedule_Execution, tak że po zakończeniu tej operacji dla tego Scheduled_Search nie zostanie
   wygenerowany żaden nowy `next_run_at`.
2. IF żądanie usunięcia odnosi się do Scheduled_Search, który już nie istnieje, THEN THE
   Scheduled_Search_Manager SHALL zwrócić potwierdzenie usunięcia bez błędu (operacja idempotentna).
3. WHEN Scheduled_Search zostaje usunięty, THE Scheduled_Search_Manager SHALL zachować już utworzone
   Search_Record z jego wcześniejszych Schedule_Execution i pozostawić je dostępne do przeglądania w
   historii wyszukiwań tak samo, jak przed usunięciem.
4. IF w chwili usunięcia Scheduled_Search istniało Schedule_Execution już rozpoczęte (wyszukiwanie
   zostało zainicjowane przed usunięciem), THEN THE Backend SHALL dokończyć to Schedule_Execution i
   utworzyć odpowiadający Search_Record, niezależnie od tego, że powiązany Scheduled_Search już nie
   istnieje.

### Requirement 4: Włączanie i wyłączanie zaplanowanego wyszukiwania

**User Story:** Jako operator, chcę tymczasowo wstrzymać zaplanowane wyszukiwanie bez usuwania jego
konfiguracji, żeby móc je łatwo włączyć ponownie później.

#### Acceptance Criteria

1. WHEN Site_User przełącza istniejący Scheduled_Search ze stanu `enabled` na `disabled`, THE
   Scheduled_Search_Manager SHALL zachować jego Search_Criteria i częstotliwość oraz zatrzymać dalsze
   Schedule_Execution.
2. IF Site_User przełącza istniejący Scheduled_Search ze stanu `disabled` na `enabled` i właściciel
   tego Scheduled_Search ma wtedy mniej niż Max_Active_Schedules aktywnych `enabled` Scheduled_Search,
   THEN THE Scheduled_Search_Manager SHALL wznowić Schedule_Execution i przeliczyć `next_run_at`
   równe chwili wznowienia plus liczba godzin skonfigurowanej częstotliwości.
3. WHEN Site_User przełącza Scheduled_Search do stanu, w którym już się znajduje (`enabled` →
   `enabled` lub `disabled` → `disabled`), THE Scheduled_Search_Manager SHALL pozostawić bez zmian
   stan, Search_Criteria, częstotliwość i `next_run_at` tego Scheduled_Search.
4. WHILE właściciel danego Scheduled_Search ma aktywne (`enabled`) Scheduled_Search w liczbie równej
   Max_Active_Schedules, THE Scheduled_Search_Manager SHALL odrzucić próbę włączenia dodatkowego
   `disabled` Scheduled_Search tego właściciela i zwrócić błąd wskazujący przekroczony limit.
5. IF żądanie przełączenia stanu odnosi się do Scheduled_Search, który nie istnieje, THEN THE
   Scheduled_Search_Manager SHALL zwrócić błąd „nie znaleziono” bez modyfikacji żadnych danych.

### Requirement 5: Konfiguracja częstotliwości wykonania

**User Story:** Jako operator, chcę wybrać jak często zaplanowane wyszukiwanie ma się wykonywać (np.
codziennie albo co X godzin), żeby dopasować częstotliwość do priorytetu poszukiwanego auta.

#### Acceptance Criteria

1. THE Scheduled_Search_Manager SHALL przyjmować jako poprawną częstotliwość wyłącznie liczbę
   całkowitą godzin z zakresu od 1 do 168 włącznie (od 1h do 7 dni), zgodnie z istniejącym
   ograniczeniem `interval_hours` w `createQueueWatchInputSchema`.
2. IF żądanie utworzenia lub edycji Scheduled_Search zawiera częstotliwość, która nie jest liczbą
   całkowitą godzin, wykracza poza zakres 1–168 godzin, jest brakująca lub ma nieprawidłowy typ
   danych, THEN THE Scheduled_Search_Manager SHALL odrzucić żądanie, zwrócić błąd walidacji
   częstotliwości i nie zapisać ani nie zmodyfikować żadnych danych Scheduled_Search.
3. WHEN Site_User wybiera w interfejsie predefiniowaną opcję „codziennie”, THE GUI SHALL przekazać
   do Scheduled_Search_Manager częstotliwość równą dokładnie 24 godzinom.
4. THE GUI SHALL umożliwiać wybór predefiniowanej opcji „codziennie” niezależnie od aktualnie
   skonfigurowanego zakresu dopuszczalnej częstotliwości, pozostawiając walidację tego zakresu
   wyłącznie Scheduled_Search_Manager zgodnie z Wymaganiem 5.2.

### Requirement 6: Lista zaplanowanych wyszukiwań

**User Story:** Jako operator, chcę widzieć listę wszystkich zaplanowanych wyszukiwań z ich stanem i
najbliższym terminem wykonania, żeby mieć przegląd tego, co jest monitorowane.

#### Acceptance Criteria

1. WHEN Site_User otwiera widok zaplanowanych wyszukiwań, THE Scheduled_Search_Manager SHALL zwrócić
   listę wszystkich Scheduled_Search widocznych dla wszystkich Site_User, posortowaną rosnąco po
   `next_run_at`, każdy z Search_Criteria, stanem (`enabled`/`disabled`), `next_run_at`, `last_run_at`,
   `runs_count` i `last_result_count`.
2. WHEN lista Scheduled_Search zwrócona Site_User jest niepusta, THE GUI SHALL wyświetlać przy każdym
   Scheduled_Search identyfikator Site_User, który go utworzył, w tej samej, nieskróconej i
   niezanonimizowanej postaci, w jakiej jest on wyświetlany dla Search_Record i historii audytu.
3. WHEN pobranie listy Scheduled_Search powiodło się i lista jest pusta, THE GUI SHALL zastąpić
   obszar listy stanem pustym zawierającym instrukcję utworzenia nowego zaplanowanego wyszukiwania,
   bez wyświetlania pustej tabeli lub pustej listy elementów.
4. IF pobranie listy Scheduled_Search nie powiodło się (np. z powodu niedostępności
   Backend_Transport), THEN THE GUI SHALL wyświetlić widoczny stan błędu z możliwością ponowienia
   żądania, wyraźnie odróżniony od stanu pustego opisanego w Wymaganiu 6.3.

### Requirement 7: Wykonanie zaplanowanego wyszukiwania i powiązanie z wynikami

**User Story:** Jako operator, chcę, żeby każde automatyczne wykonanie zaplanowanego wyszukiwania
tworzyło rekord wyników dostępny w historii, żeby móc przeglądać znalezione oferty tak jak po ręcznym
wyszukiwaniu.

#### Acceptance Criteria

1. WHEN nadchodzi zaplanowany termin Schedule_Execution dla `enabled` Scheduled_Search, THE
   Backend SHALL wykonać wyszukiwanie z zapisanymi Search_Criteria tego Scheduled_Search przez
   Backend_Transport.
2. WHEN Schedule_Execution zakończy się powodzeniem, THE Scheduled_Search_Manager SHALL zaktualizować
   dla powiązanego Scheduled_Search wartości `last_run_at` (chwila zakończenia), `runs_count`
   (inkrementowane o 1), `last_result_count` (liczba znalezionych ofert, zero lub więcej) oraz
   przeliczyć `next_run_at` równe chwili zakończenia plus liczba godzin skonfigurowanej częstotliwości.
3. WHEN Site_User otwiera widok danego Scheduled_Search, THE GUI SHALL umożliwiać przejście do listy
   Search_Record utworzonych wyłącznie przez Schedule_Execution tego Scheduled_Search.
4. WHEN Schedule_Execution zakończy się powodzeniem, THE Backend SHALL utworzyć dokładnie jeden
   Search_Record niezależnie od tego, czy liczba znalezionych ofert jest równa zero czy większa od
   zera — w odróżnieniu od Legacy_Retry_Queue, która oczekuje na pierwszy niepusty wynik przed
   zakończeniem cyklu ponawiania.
5. IF Schedule_Execution zakończy się niepowodzeniem (np. z powodu niedostępności Backend_Transport,
   zgodnie z Wymaganiem 9.2), THEN THE Scheduled_Search_Manager SHALL zaktualizować dla powiązanego
   Scheduled_Search wartości `last_run_at` (chwila niepowodzenia) i `next_run_at` (chwila
   niepowodzenia plus liczba godzin skonfigurowanej częstotliwości), bez inkrementowania `runs_count`
   i bez tworzenia Search_Record.

### Requirement 8: Limit liczby aktywnych zaplanowanych wyszukiwań

**User Story:** Jako administrator systemu, chcę ograniczyć liczbę aktywnych zaplanowanych wyszukiwań
na użytkownika, żeby uniknąć nadmiernego obciążenia Backend przez sumę wszystkich cykli.

#### Acceptance Criteria

1. THE Scheduled_Search_Manager SHALL stosować Max_Active_Schedules jako górny limit liczby
   jednocześnie `enabled` Scheduled_Search dla jednego Site_User, liczony w chwili każdego żądania
   utworzenia lub włączenia tak, aby suma aktywnych Scheduled_Search tego Site_User nigdy nie
   przekroczyła tego limitu, nawet przy równoczesnych żądaniach (zgodnie z Wymaganiami 1.4 i 4.4).
2. WHERE wartość Max_Active_Schedules nie jest jawnie skonfigurowana, THE Scheduled_Search_Manager
   SHALL zastosować wartość domyślną równą 20 aktywnych Scheduled_Search na Site_User.
3. THE Scheduled_Search_Manager SHALL wymagać, aby skonfigurowana wartość Max_Active_Schedules była
   liczbą całkowitą większą lub równą 1.
4. IF Site_User przekracza Max_Active_Schedules przy próbie utworzenia lub włączenia Scheduled_Search
   (zgodnie z Wymaganiami 1.4 i 4.4), THEN THE GUI SHALL wyświetlić komunikat wskazujący aktualną
   liczbę aktywnych Scheduled_Search tego Site_User i skonfigurowany limit.
5. IF administrator zmniejsza skonfigurowaną wartość Max_Active_Schedules poniżej liczby aktualnie
   `enabled` Scheduled_Search danego Site_User, THEN THE Scheduled_Search_Manager SHALL pozostawić te
   już aktywne Scheduled_Search bez zmian, blokując jedynie nowe żądania utworzenia lub włączenia
   dodatkowych Scheduled_Search tego Site_User do momentu, gdy liczba jego aktywnych Scheduled_Search
   spadnie poniżej nowego limitu.

### Requirement 9: Zachowanie przy niedostępności backendu

**User Story:** Jako operator, chcę wiedzieć, że zarządzanie zaplanowanymi wyszukiwaniami jasno
sygnalizuje problem, gdy backend jest nieskonfigurowany lub niedostępny, żeby nie sądzić, że
wyszukiwanie działa, gdy w rzeczywistości nic się nie wykonuje.

#### Acceptance Criteria

1. IF Backend_Transport zgłasza częściową konfigurację (fail-closed) w chwili tworzenia, edycji,
   usuwania, włączania, wyłączania lub listowania Scheduled_Search, THEN THE Scheduled_Search_Manager
   SHALL odrzucić operację i zwrócić błąd konfiguracji bez zapisania częściowego stanu.
2. IF zaplanowany termin Schedule_Execution nadchodzi, a Backend_Transport jest nieskonfigurowany lub
   niedostępny, THEN THE Scheduled_Search_Manager SHALL zaktualizować powiązany Scheduled_Search
   zgodnie z Wymaganiem 7.5 (jako nieudane wykonanie), bez oznaczania tego Scheduled_Search jako
   usuniętego lub `disabled`.
3. WHEN Site_User przegląda listę Scheduled_Search, a pobranie tej listy powiodło się i ostatnie
   Schedule_Execution danego Scheduled_Search zakończyło się niepowodzeniem z powodu niedostępności
   Backend, THE GUI SHALL wyświetlić przy tym Scheduled_Search wskaźnik błędu ostatniego wykonania
   wizualnie odróżniony od zwykłego wskaźnika stanu `enabled`/`disabled`, widoczny do momentu, gdy
   kolejne Schedule_Execution tego Scheduled_Search zakończy się powodzeniem.
4. THE Scheduled_Search_Manager SHALL wykonywać zarządzanie Scheduled_Search wyłącznie przez
   Backend_Transport, bez samodzielnego wyboru między Backend Ubuntu i legacy Backend oraz bez
   runtime fallbacku między nimi, zgodnie z regułami `backend-transport.server.ts`.
5. IF żądanie listowania Scheduled_Search zostaje odrzucone z powodu fail-closed Backend_Transport
   (Wymaganie 9.1), THEN THE GUI SHALL wyświetlić stan błędu opisany w Wymaganiu 6.4, odróżniony od
   wskaźnika błędu pojedynczego wykonania opisanego w Wymaganiu 9.3.

### Requirement 10: Powiadomienia o wynikach zaplanowanego wyszukiwania (opcjonalne)

**User Story:** Jako operator, chcę opcjonalnie otrzymać powiadomienie, gdy zaplanowane wyszukiwanie
znajdzie nowe oferty, żeby nie musieć samodzielnie sprawdzać listy rekordów.

#### Acceptance Criteria

1. WHERE Site_User włączył powiadomienia dla danego Scheduled_Search, WHEN Schedule_Execution tego
   Scheduled_Search zakończy się powodzeniem i znajdzie co najmniej jedną ofertę spełniającą
   Search_Criteria, THE Backend SHALL wysłać przez Notification_Channel dokładnie jedno powiadomienie
   obejmujące wszystkie oferty znalezione w tym Schedule_Execution, niezależnie od tego, czy część z
   nich była już zgłoszona w poprzednich Schedule_Execution.
2. WHERE Site_User nie włączył powiadomień dla danego Scheduled_Search, THE Backend SHALL nie wysyłać
   żadnego powiadomienia o wynikach tego Scheduled_Search, niezależnie od liczby znalezionych ofert.
3. IF wysyłka powiadomienia przez Notification_Channel nie powiedzie się, THEN THE Backend SHALL
   zarejestrować niepowodzenie wysyłki bez oznaczania samego Schedule_Execution jako nieudanego.
4. IF pierwsza próba wysyłki powiadomienia przez Notification_Channel nie powiedzie się, THEN THE
   Backend SHALL nie podejmować więcej niż jednej dodatkowej próby wysyłki tego powiadomienia dla
   danego Schedule_Execution.
5. WHERE Site_User tworzy nowy Scheduled_Search bez jawnego określenia ustawienia powiadomień, THE
   Scheduled_Search_Manager SHALL ustawić powiadomienia dla tego Scheduled_Search jako wyłączone.

### Requirement 11: Autoryzacja i ochrona sekretów

**User Story:** Jako administrator bezpieczeństwa, chcę, żeby zarządzanie zaplanowanymi wyszukiwaniami
podlegało tej samej autoryzacji sesyjnej co pozostałe funkcje GUI i nigdy nie ujawniało sekretów
backendu, żeby nie wprowadzać nowej powierzchni ataku.

#### Acceptance Criteria

1. THE Scheduled_Search_Manager SHALL wymagać aktywnej sesji Site_User (przez `siteSessionMiddleware`)
   dla każdej operacji tworzenia, edycji, usuwania, włączania, wyłączania i listowania Scheduled_Search.
2. IF żądanie dotyczące Scheduled_Search nie zawiera sesji rozpoznanej przez `siteSessionMiddleware`
   jako należącej do jednej z wartości `SITE_USERS`, THEN THE Scheduled_Search_Manager SHALL odrzucić
   żądanie z błędem autoryzacji przed walidacją danych wejściowych i przed jakimkolwiek dostępem do
   Backend, nie zapisując żadnych danych Scheduled_Search.
3. THE Scheduled_Search_Manager SHALL zwracać do klienta — zarówno w odpowiedziach powodzenia, jak i
   błędu, dla każdej operacji wymienionej w Wymaganiu 11.1 — wyłącznie zsanityzowane dane i komunikaty,
   nigdy token bearer Backend, nagłówki Cloudflare Access ani surową odpowiedź Backend.

## Decyzje i niewiadomości do potwierdzenia (backend / infrastruktura)

Poniższe punkty **nie są** rozstrzygnięte przez wymagania powyżej — wymagają decyzji technicznej
przed lub w trakcie fazy projektowej (design), ponieważ zależą od zdolności backendu, którą GUI nie
kontroluje:

1. **Silnik wykonawczy (execution engine) Schedule_Execution.** Wymaganie 7.1 mówi, że „Backend
   wykonuje” zaplanowane wyszukiwanie, ale nie jest ustalone, _co fizycznie odmierza czas_ i
   inicjuje wykonanie. Opcje do rozstrzygnięcia w design:
   - (a) Backend (Ubuntu FastAPI albo legacy scraper) posiada własny wewnętrzny worker/cron, tak jak
     dziś robi to Legacy_Retry_Queue przez `/api/queue` — GUI tylko zapisuje konfigurację.
   - (b) Zegar żyje w Lovable Cloud (Supabase) — wykorzystując już obecne, ale niewykorzystane
     rozszerzenia `pg_cron` + `pg_net` (`supabase/migrations/20260430142325_...sql`) do okresowego
     wywołania publicznego webhooka GUI (wzorem `POST /api/public/hooks/cleanup-logs`), który
     odpytuje due Scheduled_Search i woła `backendSearch` w ich imieniu.
   - (c) Zewnętrzny cron trigger (np. GitHub Actions / zewnętrzny scheduler) uderzający w publiczny,
     autoryzowany bearer-tokenem webhook GUI, analogicznie do `cleanup-logs.ts`.
2. **Zgodność Backend Ubuntu z `/api/queue`.** `docs/ubuntu-api-contract.md` oznacza `/queue` jako
   `blocked-by-backend-discovery` — nieznane, czy Ubuntu FastAPI implementuje odpowiednik legacy
   `/api/queue`. Rozszerzenie transportu na Backend_Transport (Wymaganie 9.4) zakłada zgodny kontrakt
   na obu transportach; potwierdzenie wymaga rozmowy z zespołem backendu i aktualizacji
   `docs/ubuntu-api-contract.md`.
3. **Koegzystencja z Legacy_Retry_Queue.** Nie ustalono, czy istniejące wpisy Legacy_Retry_Queue mają
   zostać zmigrowane do nowego modelu Scheduled_Search, czy pozostać jako odrębna, równoległa
   semantyka „powtarzaj do pierwszego wyniku”. Wymaganie 7.4 zakłada rozdzielenie semantyki, ale nie
   definiuje ścieżki migracji istniejących danych.
4. **Trwałość konfiguracji Scheduled_Search.** Nie ustalono, czy Scheduled_Search jest przechowywany
   po stronie Backend (tak jak dziś watch queue) czy w Supabase (Lovable Cloud) z samym wywołaniem
   `backendSearch` po stronie GUI przy każdym tick-u zegara. Wybór wpływa na to, czy Wymaganie 9.2
   („Backend oznacza Schedule_Execution jako nieudane”) dotyczy Backend czy Scheduled_Search_Manager.
5. **Kanał powiadomień.** Wymaganie 10 zakłada użycie istniejącej integracji Telegram
   (`docs/app-overview.md`: „Telegram notify ← gdy worker znajdzie loty”), ale nie potwierdzono, czy
   ten kanał jest dostępny per-Site_User, czy globalny dla całej instalacji.
6. **Wartość Max_Active_Schedules.** Wymaganie 8.2 proponuje domyślną wartość 20 na Site_User jako
   rozsądny punkt startowy — do potwierdzenia lub zmiany przez właściciela produktu przed
   implementacją.
