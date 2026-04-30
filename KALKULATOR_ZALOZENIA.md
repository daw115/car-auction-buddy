# Założenia Kalkulatora Opłacalności - AutoScout US

## Cel Kalkulatora

Kalkulator służy do szybkiej oceny opłacalności zakupu pojazdu z aukcji amerykańskich (Copart, IAAI, Amerpol) i importu do Polski. Pomaga importerom podjąć decyzję zakupową w czasie rzeczywistym podczas aukcji.

## Dane Wejściowe

### 1. Cena Zakupu
- **Cena aukcyjna** (Winning Bid) - USD
- **Opłata aukcyjna** (Buyer's Fee) - USD, zależna od platformy:
  - Copart: $50-$600 (skala progresywna)
  - IAAI: $300-$500 (zależna od ceny pojazdu)
  - Amerpol: 10% ceny młotkowej

### 2. Koszty Naprawy
- **Szacunek AI** (z analizy Gemini) - USD
  - Minimum repair cost
  - Maximum repair cost
  - Średnia: (min + max) / 2
- **Ręczna korekta** - możliwość nadpisania przez użytkownika

### 3. Transport USA → Polska
- **Transport wewnętrzny USA** (do portu):
  - Wschodnie wybrzeże: $200-400
  - Zachodnie wybrzeże: $400-800
  - Środkowy zachód: $300-600
- **Fracht morski** (port USA → port PL):
  - Kontener 20ft (1 auto): $1,500-2,000
  - Kontener 40ft (2-3 auta): $2,500-3,500 (podzielone)
  - RoRo (roll-on/roll-off): $800-1,200
- **Transport w Polsce** (port → magazyn):
  - $150-300

**Domyślna wartość**: $2,000 (średnia dla pojedynczego auta)

### 4. Cła i Podatki (Import do Polski)

#### Cło importowe:
- **Samochody osobowe**: 10% wartości celnej
- **Wartość celna** = cena zakupu + transport + ubezpieczenie

#### VAT:
- **23%** od (wartość celna + cło)
- Możliwość odliczenia dla firm z VAT-UE

#### Akcyza (dla aut >2000 cm³):
- Silniki benzynowe >2000 cm³: 18.6% wartości + €3.1/cm³ powyżej 2000
- Silniki diesla >2000 cm³: 18.6% wartości + €3.1/cm³ powyżej 2000
- Auta elektryczne: 0%

**Uproszczenie kalkulatora**: 
- Cło: 10% wartości celnej
- VAT: 23% (wartość celna + cło)
- Akcyza: opcjonalnie dla aut >2000 cm³

### 5. Koszty Dodatkowe

- **Ubezpieczenie transportu**: 1-2% wartości pojazdu
- **Opłaty portowe**: $100-200
- **Homologacja w Polsce**: 500-1,500 PLN
- **Rejestracja**: 500-1,000 PLN
- **Badanie techniczne**: 200-500 PLN

**Domyślna wartość**: $500 (suma kosztów dodatkowych)

## Formuła Kalkulacji

### Całkowity Koszt Inwestycji (Total Investment)

```
Total Investment = 
  Cena aukcyjna
  + Opłata aukcyjna
  + Koszty naprawy (średnia z AI)
  + Transport USA → PL
  + Cło (10% wartości celnej)
  + VAT (23% z cła)
  + Akcyza (jeśli >2000 cm³)
  + Koszty dodatkowe
```

### Wartość Celna (Customs Value)

```
Customs Value = 
  Cena aukcyjna
  + Opłata aukcyjna
  + Transport USA → PL
  + Ubezpieczenie (1.5% wartości)
```

### Szacowana Wartość Sprzedaży w Polsce

**Źródła danych**:
- Otomoto.pl - średnie ceny dla danego modelu/rocznika
- AutoScout24.pl - porównanie z rynkiem europejskim
- Manualny input użytkownika

**Korekty wartości**:
- Salvage title: -20% do -40%
- Prawostronne kierownice: -25% do -35%
- Brak historii serwisowej: -10%
- Uszkodzenia strukturalne (frame damage): -30% do -50%
- Flood/fire damage: -40% do -60%

**Domyślna wartość**: Estimated Retail Value z aukcji × 1.2 (przelicznik USA → PL)

### Zysk Netto (Net Profit)

```
Net Profit = 
  Szacowana wartość sprzedaży PL
  - Total Investment
```

### ROI (Return on Investment)

```
ROI % = (Net Profit / Total Investment) × 100
```

## Progi Decyzyjne

### Rekomendacje zakupu:

- **Strong Buy**: ROI > 40%, Net Profit > $5,000
- **Buy**: ROI > 25%, Net Profit > $3,000
- **Hold**: ROI 15-25%, Net Profit $1,500-3,000
- **Avoid**: ROI < 15%, Net Profit < $1,500
- **Strong Avoid**: ROI < 0% (strata)

### Red Flags (automatyczne obniżenie rekomendacji):

- Frame damage → max "Hold"
- Flood damage → max "Avoid"
- Fire damage → max "Avoid"
- Salvage title + high mileage (>150k miles) → max "Hold"
- Missing keys + No start/run → max "Avoid"
- Airbags deployed + structural damage → max "Hold"

## Parametry Konfigurowalne

Użytkownik może dostosować:

1. **Kurs USD/PLN** - aktualizowany automatycznie z API NBP
2. **Koszt transportu** - zależny od lokalizacji aukcji
3. **Koszty naprawy** - nadpisanie szacunku AI
4. **Szacowana wartość sprzedaży** - własna ocena rynku
5. **Marża zysku** - minimalna akceptowalna marża

## Przykład Kalkulacji

### Dane wejściowe:
- Pojazd: 2020 Toyota Camry LE
- Cena aukcyjna: $8,000
- Opłata aukcyjna (Copart): $400
- Uszkodzenia: Front bumper, hood (AI estimate: $1,200)
- Transport: $2,000
- Wartość sprzedaży PL: 80,000 PLN (~$20,000)

### Kalkulacja:
```
Wartość celna = $8,000 + $400 + $2,000 + $150 (ubezp.) = $10,550
Cło (10%) = $1,055
VAT (23% z $11,605) = $2,669
Koszty naprawy = $1,200
Koszty dodatkowe = $500

Total Investment = $8,000 + $400 + $1,200 + $2,000 + $1,055 + $2,669 + $500
                 = $15,824

Net Profit = $20,000 - $15,824 = $4,176
ROI = ($4,176 / $15,824) × 100 = 26.4%

Rekomendacja: BUY (ROI > 25%, zysk > $3,000)
```

## Integracja z AI

Kalkulator wykorzystuje wyniki analizy Gemini:
- `damage_score` → wpływ na wartość sprzedaży
- `repair_cost_min/max` → koszty naprawy
- `risk_flags` → obniżenie rekomendacji
- `investment_analysis.recommendation` → wstępna sugestia

Ostateczna decyzja = AI recommendation + kalkulator finansowy

## Wyświetlanie Wyników

### Widok podstawowy:
- Total Investment (USD + PLN)
- Estimated Resale Value (PLN)
- Net Profit (PLN)
- ROI (%)
- Recommendation (Strong Buy → Strong Avoid)

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

### Automatyczne aktualizacje:
- Kurs USD/PLN: API NBP (codziennie)
- Ceny transportu: co kwartał (dane od spedytorów)
- Stawki celne: co rok (Taryfa Celna UE)

### Manualne źródła:
- Ceny rynkowe PL: Otomoto.pl, AutoScout24.pl
- Koszty naprawy: bazy danych części (RockAuto, CarParts)
- Opłaty aukcyjne: oficjalne cenniki Copart/IAAI

## Ograniczenia i Zastrzeżenia

⚠️ Kalkulator podaje **szacunki**, nie gwarancje:
- Rzeczywiste koszty naprawy mogą być wyższe (ukryte uszkodzenia)
- Wartość sprzedaży zależy od stanu rynku i popytu
- Czas sprzedaży może być dłuższy niż zakładany
- Koszty transportu mogą wzrosnąć (ceny paliw, kursy walut)
- Nie uwzględnia kosztów magazynowania i finansowania

**Zalecenie**: Zawsze dodaj 10-15% bufora bezpieczeństwa do Total Investment.
