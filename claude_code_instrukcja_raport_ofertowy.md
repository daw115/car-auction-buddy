# Instrukcja dla Claude Code: generowanie raportu/oferty handlowej aut z USA

## Cel

Na podstawie danych wejściowych o samochodach wygeneruj estetyczny dokument `.docx` w formie oferty handlowej. Dokument ma być przeznaczony dla klienta, więc powinien być czytelny, uporządkowany i gotowy do wysłania.

Każdy samochód musi mieć osobną stronę A4. Nie upychaj kilku aut na jednej stronie.

## Dane wejściowe

Źródłem mogą być:

- raport PDF z tabelą i opisami aut,
- istniejący dokument `.docx` z analizą,
- dane JSON/CSV z systemu,
- wynik scrapingu aukcji Copart/IAAI.

Dla każdego auta zbierz i uporządkuj co najmniej:

- marka, model, rocznik,
- źródło aukcji: Copart albo IAAI,
- lot ID,
- VIN,
- lokalizacja,
- przebieg w milach i kilometrach,
- typ tytułu: Clean, Salvage itd.,
- typ uszkodzenia,
- status poduszek,
- aktualna oferta aukcyjna,
- cena rezerwowa, jeśli istnieje,
- szacowany koszt naprawy,
- szacowany koszt transportu,
- szacowany koszt całkowity,
- score/rekomendacja z raportu,
- link aukcyjny,
- opis zalet,
- opis ryzyk,
- elementy wymagające weryfikacji.

Jeśli w źródle są duplikaty, scal je. Jedno auto = jeden lot ID/VIN = jedna karta.

## Struktura dokumentu

Dokument powinien zawierać:

1. Stronę tytułową.
2. Krótkie podsumowanie ofert.
3. Jedną stronę A4 dla każdego samochodu.

Strona tytułowa powinna zawierać:

- tytuł, np. `Oferta handlowa - Toyota Camry z USA`,
- datę/godzinę źródłowego raportu,
- liczbę unikalnych aut,
- liczbę ofert rekomendowanych, warunkowych i odrzuconych,
- krótką rekomendację handlową,
- założenia i ograniczenia,
- tabelę skrótu ofert.

Każda karta auta powinna zawierać:

- nagłówek: rocznik, marka, model, aukcja, lot, lokalizacja,
- status oferty: `POLECAMY`, `WARUNKOWO`, `OBSERWOWAĆ`, `NIE W BUDŻECIE`, `ODRZUCAMY`,
- score,
- dane pojazdu,
- kalkulację kosztów,
- opis handlowy,
- ryzyko,
- sekcję `Do weryfikacji`,
- warunek decyzji,
- link aukcyjny.

## Zasady redakcji

Pisz po polsku, językiem handlowym i konkretnym.

Nie kopiuj surowych opisów z raportu. Przeredaguj je:

- usuń krzykliwe sformułowania typu `NAJLEPSZA OPCJA`, `ODRZUĆ`, `IDEALNIE`,
- zachowaj sens i liczby,
- skróć długie akapity,
- rozdziel zalety, ryzyka i warunki decyzji,
- nie twórz nowych faktów, jeśli nie wynikają ze źródła.

Niepewne elementy oznaczaj w sekcji `Do weryfikacji`, np.:

- brak informacji o rezerwie,
- nieznany zakres szkody mechanicznej,
- konieczność potwierdzenia zdjęć aukcyjnych,
- ryzyko ukrytych uszkodzeń strukturalnych,
- opłaty aukcyjne,
- koszt transportu,
- zgodność VIN,
- status tytułu,
- odpalone poduszki i zakres napraw SRS.

## Logika rekomendacji

Przykładowe reguły:

- `POLECAMY`: koszt całkowity mieści się w budżecie, ryzyka są akceptowalne, auto ma dobry przebieg/lokalizację/tytuł.
- `WARUNKOWO`: oferta może być opłacalna, ale wymaga kluczowej weryfikacji.
- `OBSERWOWAĆ`: auto może być zapasową opcją, ale nie powinno być głównym wyborem.
- `NIE W BUDŻECIE`: koszt całkowity przekracza budżet klienta.
- `ODRZUCAMY`: zbyt wysoki koszt, zbyt duże ryzyko, zła lokalizacja, odpalone poduszki albo słaba relacja ceny do ryzyka.

Jeśli budżet klienta jest znany, pokazuj go w założeniach i oceniaj auta względem niego.

## Projekt wizualny

Użyj układu A4 pionowo.

Rekomendowany styl:

- granatowy nagłówek,
- jasne tła sekcji,
- zielony dla rekomendowanych,
- żółty dla warunkowych/ryzykownych,
- czerwony dla odrzuconych,
- czytelne karty i pola kosztowe,
- spójna typografia,
- dużo światła między sekcjami.

Jeśli raport nie zawiera realnych zdjęć pojazdów, nie udawaj, że je ma. Zamiast tego użyj neutralnego placeholdera z informacją:

`Raport źródłowy nie zawiera realnego zdjęcia aukcyjnego. Zdjęcia należy potwierdzić przed licytacją.`

## Format techniczny

Preferowany wynik:

- `.docx`,
- jedna strona tytułowa,
- jedna strona A4 na każde auto,
- brak pustych stron,
- brak tekstu wychodzącego poza elementy,
- brak nachodzenia tekstu na inne elementy,
- wszystkie ceny i linki czytelne.

Po wygenerowaniu dokumentu:

1. Wyrenderuj `.docx` do obrazów stron PNG.
2. Sprawdź liczbę stron.
3. Zweryfikuj wizualnie każdą stronę.
4. Popraw układ, jeśli tekst nachodzi na elementy albo karta auta rozbija się na więcej niż jedną stronę.
5. Dopiero wtedy zwróć finalny plik.

## Minimalny format danych po ekstrakcji

```json
[
  {
    "vehicle": "2019 Toyota Camry",
    "source": "IAAI",
    "lot": "34567890",
    "vin": "4T1BF1FK6HU234567",
    "location": "Miami, FL",
    "mileage_mi": 38000,
    "mileage_km": 61155,
    "damage": "Side",
    "title": "Clean",
    "airbags": "OK",
    "current_bid_usd": 6200,
    "seller_reserve_usd": null,
    "repair_estimate_usd": 2000,
    "transport_estimate_usd": "1400-1600",
    "total_estimate_usd": 11200,
    "score": 8.5,
    "source_recommendation": "POLECAM",
    "auction_url": "https://www.iaai.com/vehicle/34567890",
    "strengths": [
      "niski przebieg",
      "Clean title",
      "korzystna lokalizacja",
      "brak odpalonych poduszek"
    ],
    "risks": [
      "uszkodzenie boczne wymaga oceny struktury",
      "cena może wzrosnąć w licytacji"
    ],
    "verify": [
      "zdjęcia wysokiej rozdzielczości",
      "status tytułu",
      "zgodność VIN",
      "opłaty aukcyjne",
      "koszt transportu"
    ]
  }
]
```

## Prompt roboczy dla Claude Code

```text
Na podstawie dostarczonego raportu PDF/DOCX utwórz ofertę handlową aut z USA w formacie DOCX.

Wymagania:
- pisz po polsku,
- zachowaj sens i liczby ze źródła,
- scal duplikaty po VIN albo lot ID,
- przygotuj stronę tytułową z podsumowaniem,
- każde auto umieść na osobnej stronie A4,
- dodaj status oferty, score, dane auta, kalkulację kosztów, opis handlowy, ryzyko, warunek decyzji i sekcję „Do weryfikacji”,
- niepewne stwierdzenia przenieś do „Do weryfikacji”,
- nie dodawaj faktów, których nie ma w źródle,
- jeśli nie ma realnych zdjęć, użyj neutralnego placeholdera i zaznacz, że zdjęcia aukcyjne wymagają potwierdzenia,
- po wygenerowaniu wyrenderuj DOCX do PNG i sprawdź każdą stronę,
- popraw układ, jeśli są puste strony, nachodzenie tekstu, przycięcia albo auto nie mieści się na jednej stronie.

Finalnie zwróć tylko gotowy plik DOCX i krótkie podsumowanie zmian.
```
