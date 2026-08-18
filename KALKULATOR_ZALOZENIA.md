# Założenia Kalkulatora Opłacalności - AutoScout US

## Cel Kalkulatora

Kalkulator liczy **cenę pod drzwi w Polsce** dla auta z aukcji amerykańskich (Copart, IAAI, Manheim). Wynikiem jest kwota, którą zapłaci klient: koszt sprowadzenia plus prowizja brokera (`pricing/import_calculator.client_price_pln`). Kalkulator NIE liczy wartości odsprzedaży, zysku ani ROI — służy do wyceny oferty dla klienta i do wyznaczenia sufitu licytacji z jego budżetu (`scoring/budget.max_bid_for_budget`), nie do oceny inwestycji.

## Dane Wejściowe

### 1. Cena Zakupu
- **Cena aukcyjna** (Winning Bid) - USD
- **Opłata aukcyjna** (`AUCTION_FEE_RATE`) - **8% kwoty licytacji**, jedna stawka dla wszystkich platform:
  - brak progów i brak rozróżnienia Copart / IAAI / Manheim
  - liczona zawsze jako `bid_usd × 0.08`, wchodzi do sumy kosztów USA

### 2. Koszty Naprawy

Koszt naprawy **nie wchodzi** do ceny pod drzwi. `report/cost_calculator.calculate_full_cost` zwraca `repair_usd` / `repair_pln` jako pozycję **obok** sumy — szacunek naprawy nie jest kosztem, który ktokolwiek zafakturuje, a wliczony po cichu rozjeżdżałby raport z ofertą.

Model AI ma zakaz szacowania napraw (`ai/analyzer.SYSTEM_PROMPT`): pola `estimated_repair_usd` i `estimated_total_cost_usd` zostają na 0/null. Formularz kalkulatora nie ma pola na naprawę ani na jej ręczną korektę.

### 3. Koszty po stronie USA i frachtu

- **Transport z placu aukcyjnego (towing)** - z tabeli `window.TOWING_LOCATIONS`
  (`api/static/calculator-data.js`), per lokalizacja aukcji; gdy znamy tylko stan,
  bierzemy medianę stanu, a bez stanu - 1 000 USD
- **Załadunek** (`DEFAULT_LOADING_USD`): 560 USD
- **Fracht morski** (`DEFAULT_FREIGHT_USD`): 1 050 USD
- **Transport po odprawie (DE → PL)**, liczony w złotówkach:
  - osoba prywatna (`TRANSPORT_PRIVATE_PLN`): 2 500 PLN
  - firma (`TRANSPORT_COMPANY_PLN`): 2 100 PLN

Auto jedzie przez odprawę w Niemczech, nie do portu w Polsce. Kalkulator nie zna
wariantów kontener 20ft / 40ft / RoRo i nie ma domyślnej kwoty transportu 2 000 USD.

### 4. Cła i Podatki (Import do Polski)

#### Cło importowe — stawka NIE jest stała (od 1 lipca 2026)

Rozporządzenie UE 2026/1455 zniosło cła na amerykańskie towary przemysłowe. Stawka
zależy więc od konkretnego auta i wybiera ją `pricing/tariff.py`, a nie stała modułu:

- **0%** — auto zmontowane w USA, niebędące elektrykiem. Preferencja obowiązuje
  od 1 lipca 2026 do 31 grudnia 2029 (`DUTY_FREE_FROM`, `DUTY_FREE_UNTIL`).
- **10%** (`DUTY_STANDARD`, dawniej `CUSTOMS_DUTY_RATE`) — wszystko pozostałe:
  auta zmontowane poza USA, elektryki (wyłączone z preferencji) i każdy przypadek,
  w którym kraju montażu nie da się ustalić.

Decyduje **miejsce montażu, nie marka**. Ustalamy je z pierwszego znaku VIN-u
(`pricing/vin.py`): 1, 4, 5 → USA; 2 → Kanada; 3 → Meksyk; J → Japonia; W → Niemcy.
BMW ze Spartanburga ma 0%, Audi Q5 z Puebli kupione na tej samej aukcji ma 10%.
Copart maskuje sześć ostatnich znaków VIN-u, ale pierwszy jest zawsze widoczny,
więc kwalifikację znamy przed otwarciem szczegółów aukcji.

Podstawa naliczenia nie zmieniła się:
- **Osoba prywatna**: podstawa = 40% sumy kosztów USA w PLN + 550 USD × kurs
  (`PRIVATE_CUSTOMS_BASE_RATE`, `FIXED_EXCISE_BASE_USD`)
- **Firma**: podstawą jest cała suma kosztów USA w PLN

Cło wchodzi do podstawy VAT-u, więc zerowa stawka ścina i cło, i podatek od niego —
na aucie za 15 000 USD to około 9 000 zł różnicy w cenie pod drzwi.

#### VAT:
- **Osoba prywatna**: VAT niemiecki **21%** (`DE_VAT_RATE`) od (podstawa odprawy + cło) —
  odprawa idzie przez Niemcy, więc w tym wariancie VAT-u polskiego nie ma
- **Firma**: VAT polski **23%** (`PL_VAT_RATE`) od całości netto (suma USA + opłaty DE
  + akcyza), a nie od „wartości celnej + cło"

#### Akcyza — cztery stawki, nie dwie (stan na sierpień 2026)

Wybiera je `pricing/tariff.excise_rate_for()` na podstawie napędu i pojemności:

| napęd | pojemność | stawka | stała |
|---|---|---|---|
| spalinowy | do 2 000 cm³ | **3,1%** | `EXCISE_ICE_SMALL` |
| spalinowy | powyżej 2 000 cm³ | **18,6%** | `EXCISE_ICE_LARGE` |
| hybryda | do 2 000 cm³ | **1,55%** | `EXCISE_HYBRID_SMALL` |
| hybryda | 2 000–3 500 cm³ | **9,3%** | `EXCISE_HYBRID_MEDIUM` |
| hybryda | powyżej 3 500 cm³ | **18,6%** — bez preferencji | `EXCISE_ICE_LARGE` |
| elektryczny | — | **0%** | `EXCISE_EV` |

Interpretacja ogólna Ministra Finansów z 26 lutego 2026 objęła obniżonymi stawkami
także **łagodne hybrydy (MHEV, instalacja 48 V)**. To jest największa pojedyncza
różnica w tym kalkulatorze: typowy amerykański SUV z V6 i instalacją 48 V płaci
9,3% zamiast 18,6%, czyli przy locie za 15 000 USD około 5 000 zł mniej.

Uwaga na próg 3 500 cm³. Duże jednostki z 48 V — Ram 1500 eTorque 3.6, Hemi 5.7 —
hybrydami w rozumieniu przepisu są, ale pojemnością wychodzą ponad próg i preferencji
nie mają. Policzenie im 9,3% zaniża cenę klienta o kilka tysięcy złotych.

Napęd rozpoznajemy z opisu wersji (`pricing/drivetrain.py`), a nie z homologacji.
Dlatego hybrydę uznajemy wyłącznie przy jednoznacznym słowie w danych; wszystko
niepewne idzie po stawce spalinowej. Nieznana pojemność → 18,6%, bo pomyłka w drugą
stronę zaniża cenę klienta o ok. 5 000 zł przy locie za 10 000 USD.

Nie ma składnika €3,1 za cm³ — stawka jest wyłącznie procentowa. Akcyza nie jest
opcjonalna, liczy się zawsze; różni się tylko podstawa:
- **Osoba prywatna**: 50% wartości przed akcyzą × stawka
- **Firma**: (kwota licytacji + 550 USD) × kurs × stawka

### 5. Koszty Dodatkowe

- **Koszty dodatkowe** (`DEFAULT_ADDITIONAL_COSTS_USD`): **300 USD**, jedna pozycja ryczałtowa
  wchodząca do sumy kosztów USA
- **Serwis + ubezpieczenie**: 2% sumy USA (`SERVICE_INSURANCE_RATE`) plus połowa tej kwoty
  na obsługę szkody — razem 3%. Pozycja **informacyjna**, pokazywana w panelu, ale
  NIE doliczana ani do sumy prywatnej, ani do firmowej.

Homologacji, rejestracji i badania technicznego kalkulator **nie liczy** — nie ma ich
w arkuszu, z którego został przepisany, i nie da się ich dopisać „na oko".

## Formuła Kalkulacji

### Cena Pod Klucz (Client Price)

```
Suma USA (USD) =
  kwota licytacji
  + prowizja aukcyjna 8%
  + towing (tabela / mediana stanu)
  + załadunek (560)
  + fracht (1050)
  + koszty dodatkowe (300)

Suma USA (PLN) = Suma USA (USD) × kurs USD/PLN (z NBP + narzut)

stawka cła    = 0% dla auta zmontowanego w USA (poza elektrykami), inaczej 10%
stawka akcyzy = 1,55% / 3,1% / 9,3% / 18,6% / 0% — zależnie od napędu i pojemności

OSOBA PRYWATNA:
  podstawa odprawy  = 40% × Suma USA (PLN) + 550 USD × kurs
  cło               = stawka cła × podstawa odprawy
  VAT DE            = 21% × (podstawa odprawy + cło)
  opłaty DE         = 3000 (odprawa) + cło + VAT DE + 2500 (transport DE→PL)
  przed akcyzą      = Suma USA (PLN) + opłaty DE
  akcyza            = 50% × przed akcyzą × stawka akcyzy
  private_total_pln = przed akcyzą + akcyza

FIRMA:
  cło               = stawka cła × Suma USA (PLN)
  opłaty DE         = 3000 + cło
  akcyza            = (licytacja + 550 USD) × kurs × stawka akcyzy
  netto             = Suma USA (PLN) + opłaty DE + akcyza
  company_gross_pln = netto × 1,23 + 2100 (transport DE→PL)

CENA DLA KLIENTA = private_total_pln (albo company_gross_pln)
                 + prowizja brokera brutto
```

Prowizja brokera: basic 1 800 PLN + 2% licytacji (netto), premium 3 600 PLN + 4%
licytacji (netto), obie ×1,23. Definicja ceny końcowej siedzi w jednym miejscu —
`pricing/import_calculator.client_price_pln` — i korzystają z niej sufit budżetu,
mail ofertowy, wiadomość WhatsApp i raport per lot.

### Podstawa Odprawy (Customs Base)

```
Osoba prywatna:
  podstawa = 40% × Suma USA (PLN) + 550 USD × kurs

Firma:
  podstawa = Suma USA (PLN)
```

Ubezpieczenie nie wchodzi do podstawy. Kalkulator liczy osobno pozycję informacyjną
„serwis + ubezpieczenie": 2% sumy USA plus połowa tej kwoty na obsługę szkody — razem 3%.
Ta pozycja NIE jest doliczana ani do sumy prywatnej, ani do firmowej.





## Progi Decyzyjne

### Rekomendacje (`scoring/unified.py`)

Ocena lota to liczba 0-10 liczona deterministycznie POZA modelem. Dopuszczalne wartości
rekomendacji są dokładnie cztery:

- **POLECAM**: ocena ≥ 7,5 (`RECOMMEND_THRESHOLD`)
- **RYZYKO**: ocena ≥ 5,0 i < 7,5 (`RISK_THRESHOLD`)
- **ODRZUĆ**: ocena < 5,0 albo twardy dyskwalifikator (wtedy ocena = 0,0)
- **PONAD BUDŻET** (`OVER_BUDGET`): cena przekracza sufit wyliczony z budżetu klienta —
  nadpisuje rekomendację, ale NIE zmienia oceny

Wagi składowe oceny (renormalizowane, gdy brakuje danych): cena vs rynek 0,25,
stan techniczny 0,20, tytuł 0,15, przebieg 0,15, logistyka 0,10, wiarygodność 0,10,
dopasowanie do klienta 0,05.

Nie ma progów ROI ani rekomendacji Strong Buy / Buy / Hold / Avoid / Strong Avoid.

### Twarde dyskwalifikatory (`scoring.unified.disqualify`)

Poniższe powody nie obniżają punktacji — przekreślają lot: ocena = **0,0**,
rekomendacja **ODRZUĆ**:

- zalanie lub pożar (flood / water damage / fire / burn w opisie szkód albo w tytule)
- uszkodzenie konstrukcji: flaga `hasFrameDamage`, słowo frame/structural w opisie albo
  vision `frame_damage_check.frame_damaged` z `confidence ≥ 0.5` (i bez `images_inaccessible`)
- tytuł salvage, gdy klient wymaga Clean (`require_clean_title`)
- czerwone światło (sprzedaż as-is), gdy apetyt na ryzyko = `none`

Brak kluczy, wysoki przebieg i odpalone poduszki NIE są dyskwalifikatorami — wchodzą
do składowych oceny. Przekroczenie budżetu też nie jest dyskwalifikatorem: daje osobny
werdykt **PONAD BUDŻET**, a ocena liczy się normalnie.

## Parametry Konfigurowalne

Użytkownik może dostosować (pola formularza w `api/static/index.html`):

1. **Kwota licytacji (USD)**
2. **Stan i lokalizacja aukcji** — podstawiają towing z tabeli
3. **Towing (USD)** — nadpisanie wartości z tabeli
4. **Koszty dodatkowe (USD)** — domyślnie 300
5. **Załadunki (USD)** — domyślnie 560
6. **Fracht (USD)** — domyślnie 1 050
7. **Kurs USD/PLN** — pobierany z **API NBP** (tabela A) przez `pricing/fx.py`,
   z narzutem `FX_MARKUP_PCT` (domyślnie 2%), bo bank sprzedaje drożej niż kurs
   środkowy, a między ofertą a zamknięciem aukcji mija kilka dni. Kurs trzymany jest
   w pamięci do końca dnia roboczego; przy niedostępności NBP schodzimy na ostatni
   zapisany, a dopiero potem na `DEFAULT_USD_RATE` z `.env`.
   `FX_RATE_OVERRIDE` przybija kurs na sztywno — do testów i wtedy, gdy broker kupił
   dolary po znanym kursie. Stała 4,0 była wpisana na sztywno do sierpnia 2026
   i zawyżała każdą wycenę o około 7%.
8. **Akcyza** — wybór stawki (1,55% / 3,1% / 9,3% / 18,6% / 0%)
9. **Dokładka do prowizji (PLN)** — wpływa wyłącznie na rozliczenie pracownika

Nie ma pól na koszt naprawy, wartość odsprzedaży ani marżę zysku.

## Przykład Kalkulacji

### Dane wejściowe:
- Pojazd: 2020 Toyota Camry LE
- Cena aukcyjna: $8,000
- Opłata aukcyjna (Copart): $400
- Uszkodzenia: Front bumper, hood (AI estimate: $1,200)
- Transport: $2,000
- Wartość sprzedaży PL: 80,000 PLN (~$20,000)

### Kalkulacja:
## Przykład Kalkulacji

### Dane wejściowe:
- Pojazd: 2020 Toyota Camry LE, Floryda
- Kwota licytacji: $8,000
- Towing (mediana stanu FL): $980
- Akcyza: 18,6% (silnik powyżej 2,0 l)
- Kurs: 4,00 PLN/USD

### Kalkulacja:
```
Prowizja aukcyjna 8%                             =    $640
Suma USA = 8000 + 640 + 980 + 560 + 1050 + 300   = $11 530  →  46 120 PLN

OSOBA PRYWATNA:
  podstawa odprawy = 0,4 × 46 120 + 550 × 4      = 20 648 PLN
  cło 10%                                        =  2 065 PLN
  VAT DE 21%                                     =  4 770 PLN
  opłaty DE (3000 + cło + VAT + 2500 transport)  = 12 334 PLN
  wartość przed akcyzą                           = 58 454 PLN
  akcyza 18,6% od połowy                         =  5 436 PLN
  koszt sprowadzenia (private_total_pln)         = 63 891 PLN
  prowizja brokera basic brutto                  =  3 001 PLN
  CENA POD KLUCZ DLA KLIENTA                     = 66 892 PLN

FIRMA:
  koszt sprowadzenia (company_gross_pln)         = 76 015 PLN
  + prowizja basic brutto                        = 79 016 PLN
```

W drugą stronę: budżet 60 000 PLN pod drzwi (osoba prywatna, Floryda) daje sufit
licytacji ok. **7 534 USD** — tyle wyznacza `scoring/budget.max_bid_for_budget`
bisekcją, per stan USA.

## Integracja z AI

Ocena lota (0-10) jest liczona deterministycznie w `scoring/unified.py`, POZA modelem,
i doklejana do lota jako `raw_data["unified_score"]`. Model dostaje ją gotową razem
z rozbiciem na składowe i pisze wyłącznie uzasadnienie po polsku — jego `score`
i `recommendation` są nadpisywane wynikiem scoringu
(`ai/analyzer._results_from_analysis_data`).

Dostawcą modelu jest domyślnie **Claude Code w trybie headless** (`ai/claude_code.py`),
uwierzytelniany sesją zalogowanej subskrypcji (OAuth), a nie kluczem API.

Model nie zwraca pól `damage_score`, `repair_cost_min/max`, `risk_flags` ani
`investment_analysis`. Kontrakt `AIAnalysis` to: `score`, `recommendation`, `red_flags`,
`client_description_pl`, `ai_notes` oraz dwa pola kosztowe, które mają zostać na 0.

Ostateczna rekomendacja = scoring deterministyczny; kalkulator odpowiada wyłącznie
za kwoty.

## Wyświetlanie Wyników

### KPI na górze panelu:
- Suma USA (USD)
- Osoba prywatna z akcyzą (PLN)
- Firma brutto z akcyzą (PLN)

### Cztery tabele pozycji:
- **Koszty USA**: kwota licytacji, prowizja aukcyjna 8%, towing, koszty dodatkowe,
  załadunki, fracht, suma, serwis + ubezpieczenie 2% + 1%
- **Osoba prywatna**: baza odprawy DE, cło 10%, VAT DE 21%, opłaty DE + transport PL,
  wartość przed akcyzą, akcyza, razem
- **Firma**: cło 10%, opłaty DE, akcyza, netto, brutto + transport PL
- **Prowizje**: 1800 + 2% (netto/brutto), 3600 + 4% (netto/brutto), rozliczenie
  pracownika w dwóch wariantach

Nie ma wykresu kołowego, „timeline do zysku" ani porównania z podobnymi ofertami.

### Widok szczegółowy (rozwijany):
- Breakdown kosztów (pie chart):
  - Cena zakupu
  - Opłaty aukcyjne
  - Transport
  - Cła i podatki
  - Naprawy
  - Inne
- Timeline do zysku (szacowany czas sprzedaży: 30-90 dni)
- Porównanie z podobnymi ofertami

## Aktualizacje i Źródła Danych

### Wartości wpisane na stałe w kodzie
(`pricing/import_calculator.py` i `api/static/calculator.js` — zmiana wymaga edycji **obu**):
- Kurs USD/PLN: stała 4,0, nadpisywalna ręcznie w formularzu. Brak integracji z API NBP.
- Koszty dodatkowe 300 USD, załadunek 560 USD, fracht 1 050 USD
- Opłata aukcyjna 8%, cło 10%, VAT DE 21%, VAT PL 23%, odprawa DE 3 000 PLN,
  transport DE→PL 2 500 / 2 100 PLN
- Akcyza 3,1% / 18,6% / 0% (EV)

### Dane generowane:
- Tabela towing per lokalizacja aukcji: `api/static/calculator-data.js`
  (`window.TOWING_LOCATIONS`)

### Ceny rynkowe:
- Ceny referencyjne rynku PL pobiera `scraper/otomoto.py` (Otomoto.pl, cache 7 dni)
  na potrzeby raportów, NIE kalkulatora. AutoScout24 nie jest nigdzie używany.

## Ograniczenia i Zastrzeżenia

⚠️ Kalkulator podaje **szacunki**, nie gwarancje:
- Kurs 4,0 PLN/USD jest założeniem, nie kursem dnia — przy locie za 15 000 USD każde
  0,10 PLN różnicy to ok. 1 500 PLN
- Towing jest medianą stanu, gdy nie znamy dokładnej lokalizacji aukcji
- Przy nieznanej pojemności silnika bierzemy wyższą stawkę akcyzy (18,6%)
- Kwota nie zawiera naprawy, rejestracji, homologacji ani badania technicznego —
  arkusz ich nie liczy i nie da się ich dopisać „na oko"

**Zalecenie**: klientowi zawsze podawaj kwotę z `client_price_pln` (sprowadzenie +
prowizja), nigdy samego `private_total_pln` / `company_gross_pln` — pominięcie prowizji
zaniża ofertę o 2 800-4 200 zł.
