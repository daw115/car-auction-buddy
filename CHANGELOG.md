# Historia wydań — USA Car Finder

## 1.0.0 — 19 sierpnia 2026

Pierwsze wydanie ogłoszone jako gotowe do codziennej pracy. Backend `1.0.0`,
panel `1.0.0`, obie strony odpowiadają na pytanie o wersję: backend przez
`GET /version`, panel przez `GET /api/version`.

### Dwuetapowa obsługa klienta

Klient dostaje najpierw **obrazek** z trzema ponumerowanymi autami, nie PDF —
widzi go od razu w wątku WhatsAppa, zamiast pobierać plik i otwierać w innej
aplikacji. Odpowiada samą cyfrą, a panel czyta ten numer z rozmowy i podpowiada,
co zaznaczyć. Jedno kliknięcie wysyła wtedy raport szczegółowy dla klienta
i brief dla brokera.

Sprawa klienta prowadzi przez cztery kroki (oferta wstępna, wybór, raport,
decyzja) i zapisuje, **co** dokładnie poszło — bo z rozmowy na WhatsAppie tego
nie widać.

Tekst wiadomości jest osobno od obrazka: powitanie i prośba o odpowiedź to treść
rozmowy, nie dokumentu. Idzie jako podpis zdjęcia na Telegramie, więc broker
kopiuje go jednym gestem.

### Co widzi klient

- ceny **pod drzwi** (wcześniej „pod klucz"), w złotówkach z dolarami w nawiasie,
  przebieg w kilometrach z milami w nawiasie;
- uszkodzenia po polsku — kody aukcji („RIGHT SIDE") już do niego nie docierają;
- komplet zdjęć w raporcie szczegółowym, jedno w ofercie wstępnej;
- porównanie z cenami w Polsce: minimum, maksimum i średnia.

Z dokumentów dla klienta zniknęły dane wewnętrzne: cena aukcyjna, nasz wynik
punktowy, werdykt POLECAM/RYZYKO, prowizja jako osobna pozycja, link do aukcji
i nazwa modelu językowego w stopce. Model językowy **nie dostaje** już tych pól
w prompcie — nie zdradzi tego, czego nie widział.

### Rzeczy, które psuły się po cichu

Największa grupa poprawek. Wspólny kształt: coś się nie udawało, system szedł
dalej, a wynik był uboższy bez żadnego sygnału.

- **Werdykt pochodził od modelu, nie ze scoringu.** Ocena była nadpisywana
  deterministycznie, ale etykieta zostawała od modelu — a to ona decyduje, co
  trafia do oferty. Auto ocenione na 5,2 mogło pójść do klienta jako POLECAM.
- **Auta znikały z wyników**, gdy model ich nie opisał — pętla szła po
  odpowiedziach modelu, nie po lotach.
- **Krok 1 sprawy nie zapisywał się nigdy**, bo nikt nie wołał endpointu; cała
  ścieżka „numer klienta → raport" była z panelu nieosiągalna.
- **Trzy auta z Manheimu dostawały jeden klucz** (`lot_id` to tam nazwa kanału
  aukcji), więc „1", „2" i „3" prowadziły do tego samego samochodu.
- **Raporty nie powstawały**, gdy model oddał zepsuty JSON — 34 razy w logu.
  Teraz: ponowienie, a gdy i to zawiedzie, deterministyczny szablon.
- **Powracający klient był niewidzialny** — zgłoszenie doklejało się do leada
  zamkniętego jako „stracony" albo „wygrany", a te są odfiltrowane ze skrzynki.
- Oferta gubiła auta bez ceny, panel zamieniał awarię backendu w „rekordu nie
  ma", parser Coparta połykał całą ekstrakcję gołym `except: pass`.

### Widoczność pracy

Panel pokazuje **log scrapera** w trakcie wyszukiwania — fazy zmieniają się co
kilkadziesiąt sekund i między nimi ekran milczał. Szum dziennika dostępu jest
odsiewany po stronie serwera.

### Kalkulator i prawo

Kalkulator w panelu miał cło wpisane na sztywno 10%. Od 1 lipca 2026 auto
złożone w USA wchodzi na 0%, co przy egzemplarzu za 15 tys. dolarów daje
**9 311 zł różnicy** w wycenie. Stawki bierze teraz z backendu, z jedynego
modułu, który zna przepisy.

### Serwer

Autologowanie Windowsa działa (konto bez hasła — przez rejestr, nie `netplwiz`),
a WSL2 nie gaśnie już z bezczynności: od włączenia komputera do działającego
panelu mijają około dwie minuty i nikt nie musi niczego klikać.

---

**Zasada, która nie zmieniła się ani razu:** system niczego nie wysyła klientowi
sam. Generuje treść, a wysyła człowiek.
