"""
Stawki cła i akcyzy obowiązujące dla konkretnego auta — stan prawny na sierpień 2026.

Ten moduł jest jedynym miejscem, które zna przepisy. `import_calculator.py` zostaje
czystą arytmetyką i dostaje gotowe liczby, dzięki czemu zmiana stawki nie wymaga
dotykania wzorów, a wzory dają się testować bez znajomości prawa.

CO SIĘ ZMIENIŁO I DLACZEGO TO WAŻNE

1. CŁO 10% → 0% (rozporządzenie UE 2026/1455, od 1 lipca 2026, do 31 grudnia 2029)

   Unia zniosła cła na amerykańskie towary przemysłowe. Warunkiem jest MIEJSCE MONTAŻU
   w USA, nie marka i nie miejsce zakupu — ustalamy je z pierwszego znaku VIN-u
   (`pricing/vin.py`). Z preferencji wyłączono pojazdy elektryczne: Tesla płaci pełne
   10%, mimo że zjechała z amerykańskiej taśmy.

   Skala: cło wchodzi do podstawy VAT-u, więc zerowa stawka ścina i cło, i podatek od
   niego. Na aucie za 15 000 USD to około 9 000 zł mniej w cenie pod klucz. Kwotując
   po staremu przegrywamy z każdym, kto już liczy 0%.

2. AKCYZA — doszły dwie stawki hybrydowe

   Do 2026 kod znał 3,1% (do 2000 cm³) i 18,6% (powyżej). Obowiązują cztery:

     spalinowy do 2000 cm³         3,10%
     spalinowy powyżej 2000 cm³   18,60%
     hybryda do 2000 cm³           1,55%
     hybryda 2000–3500 cm³         9,30%

   Interpretacja ogólna Ministra Finansów z 26 lutego 2026 przesądziła, że łagodne
   hybrydy (MHEV, 48 V) też korzystają z obniżonych stawek — a to jest w praktyce
   większość dużych amerykańskich SUV-ów z ostatnich roczników.

   Powyżej 3500 cm³ preferencja się kończy: taka hybryda płaci 18,6% jak spalinowa.

ZASADA ROZSTRZYGANIA WĄTPLIWOŚCI

Gdy nie wiemy — liczymy DROŻEJ. Cło bez pewnego VIN-u to 10%, nierozpoznany napęd to
stawka spalinowa, nieznana pojemność to stawka wyższa. Zawyżoną wycenę można obniżyć,
gdy dane się potwierdzą; zaniżona wraca do klienta jako dopłata po fakcie i kosztuje
nas wiarygodność, którą sprzedajemy razem z autem.

Każdy wynik niesie `assumptions` — listę zdań o tym, czego nie byliśmy pewni. Trafiają
do briefu brokera, żeby dało się je sprawdzić przed licytacją, a nie po niej.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from pricing.drivetrain import Drivetrain, DrivetrainGuess, detect_for_lot
from pricing.vin import VinOrigin, origin_for_lot

# Rozporządzenie UE 2026/1455 — okno obowiązywania preferencji.
DUTY_FREE_FROM = date(2026, 7, 1)
DUTY_FREE_UNTIL = date(2029, 12, 31)

DUTY_STANDARD = 0.10
DUTY_PREFERENTIAL = 0.0

EXCISE_ICE_SMALL = 0.031
EXCISE_ICE_LARGE = 0.186
EXCISE_HYBRID_SMALL = 0.0155
EXCISE_HYBRID_MEDIUM = 0.093
EXCISE_EV = 0.0

# Progi pojemności w litrach. Ustawa mówi w cm³ (2000 i 3500), ale silnik "2.0" ma
# realnie 1984-1998 cm³, więc próg stawiamy POWYŻEJ 2,0 l — inaczej każde 2.0 TFSI
# wpadałoby w stawkę wyższą przez błąd zaokrąglenia w opisie aukcji.
ENGINE_SMALL_MAX_L = 2.0
ENGINE_HYBRID_PREFERENCE_MAX_L = 3.5


@dataclass(frozen=True)
class Rates:
    """Stawki dla jednego auta razem z uzasadnieniem każdej z nich."""

    duty_rate: float
    excise_rate: float
    drivetrain: Drivetrain
    country_code: Optional[str]
    country_name: str
    duty_reason: str
    excise_reason: str
    assumptions: list[str] = field(default_factory=list)

    @property
    def duty_free(self) -> bool:
        return self.duty_rate == DUTY_PREFERENTIAL

    @property
    def certain(self) -> bool:
        """Czy obie stawki wynikają z danych, a nie z ostrożnego założenia."""
        return not self.assumptions

    def summary(self) -> str:
        """Jedno zdanie dla brokera — trafia do briefu, nie do klienta."""
        duty = "cło 0%" if self.duty_free else f"cło {self.duty_rate * 100:.0f}%"
        excise = f"akcyza {self.excise_rate * 100:.2f}".rstrip("0").rstrip(".") + "%"
        return f"{duty}, {excise} ({self.country_name}, {self.drivetrain.value})"


def duty_free_window_open(on: Optional[date] = None) -> bool:
    """Czy preferencja celna obowiązuje w danym dniu.

    Data jest parametrem, bo wyceny robimy też wstecz (analiza zakończonych aukcji)
    i dlatego, że preferencja wygasa — 1 stycznia 2030 kalkulator ma sam wrócić
    do 10%, bez czekania, aż ktoś zauważy.
    """
    day = on or date.today()
    return DUTY_FREE_FROM <= day <= DUTY_FREE_UNTIL


def duty_rate_for(
    vin_origin: VinOrigin,
    drivetrain: Drivetrain,
    *,
    on: Optional[date] = None,
) -> tuple[float, str]:
    """Stawka cła i powód jej zastosowania."""
    if not duty_free_window_open(on):
        return DUTY_STANDARD, "poza oknem obowiązywania preferencji UE 2026/1455"

    if drivetrain.is_electric:
        return DUTY_STANDARD, "elektryki są wyłączone ze zniesienia ceł"

    if not vin_origin.confident:
        return DUTY_STANDARD, f"kraj montażu niepotwierdzony ({vin_origin.reason})"

    if not vin_origin.assembled_in_usa:
        return DUTY_STANDARD, vin_origin.reason

    return DUTY_PREFERENTIAL, f"{vin_origin.reason} — preferencja UE 2026/1455"


def excise_rate_for(
    drivetrain: Drivetrain,
    engine_liters: Optional[float],
) -> tuple[float, str]:
    """Stawka akcyzy i powód jej zastosowania."""
    if drivetrain.is_electric:
        return EXCISE_EV, "elektryk — akcyza zerowa"

    if engine_liters is None:
        # Bez pojemności nie ma preferencji nawet dla potwierdzonej hybrydy: różnica
        # 1,55% wobec 9,3% to na aucie za 15 000 USD ponad 4 000 zł, a "hybryda"
        # w opisie nie mówi, czy pod maską jest 1.8 czy 3.5.
        return EXCISE_ICE_LARGE, "nieznana pojemność silnika — stawka wyższa"

    if drivetrain.is_hybrid:
        if engine_liters <= ENGINE_SMALL_MAX_L:
            return EXCISE_HYBRID_SMALL, "hybryda do 2000 cm³"
        if engine_liters <= ENGINE_HYBRID_PREFERENCE_MAX_L:
            return EXCISE_HYBRID_MEDIUM, "hybryda 2000–3500 cm³"
        return EXCISE_ICE_LARGE, "hybryda powyżej 3500 cm³ — bez preferencji"

    if engine_liters <= ENGINE_SMALL_MAX_L:
        return EXCISE_ICE_SMALL, "silnik spalinowy do 2000 cm³"
    return EXCISE_ICE_LARGE, "silnik spalinowy powyżej 2000 cm³"


def rates_for(
    *,
    vin_origin: VinOrigin,
    drivetrain_guess: DrivetrainGuess,
    engine_liters: Optional[float],
    on: Optional[date] = None,
    vehicle_identified: bool = True,
) -> Rates:
    """Komplet stawek dla auta razem z listą przyjętych założeń."""
    kind = drivetrain_guess.kind
    duty, duty_reason = duty_rate_for(vin_origin, kind, on=on)
    excise, excise_reason = excise_rate_for(kind, engine_liters)

    assumptions: list[str] = []
    if not vin_origin.confident and duty_free_window_open(on):
        assumptions.append(
            "Kraj montażu nieustalony — policzone z cłem 10%. "
            "Jeśli VIN zaczyna się od 1, 4 lub 5, cło wynosi 0% i cena spada."
        )
    if not drivetrain_guess.confident and engine_liters is not None and engine_liters > ENGINE_SMALL_MAX_L:
        assumptions.append(
            "Napęd nierozpoznany — policzone jak spalinowy. "
            "Jeśli to hybryda (także łagodna, 48 V), akcyza spada z 18,6% do 9,3%."
        )
    if engine_liters is None and not kind.is_electric:
        assumptions.append(
            "Pojemność silnika nieznana — przyjęta akcyza 18,6%. "
            "Przy silniku do 2,0 l stawka wynosi 3,1%."
        )

    # Jedyne założenie, które ZANIŻA cenę, więc jedyne naprawdę groźne.
    #
    # Wszystkie pozostałe niepewności prowadzą do wyższej stawki: nieznany kraj montażu
    # to cło 10%, nierozpoznany napęd to akcyza spalinowa. Tu jest odwrotnie — elektryk
    # jest WYŁĄCZONY z preferencji celnej, więc wzięcie go za spalinowy daje 0% zamiast
    # 10% i zaniża wycenę o kilkanaście tysięcy złotych. Przy pustych polach marki
    # i modelu detektor widzi samą wersję ("Long Range") i tego nie wychwyci.
    if duty == DUTY_PREFERENTIAL and not drivetrain_guess.confident and not vehicle_identified:
        assumptions.append(
            "Nie wiadomo, co to za auto — brakuje marki i modelu, a policzone jest cło 0%. "
            "Jeśli to elektryk, cło wynosi 10%: elektryki są wyłączone z preferencji. "
            "Podaj markę i model, żeby to rozstrzygnąć."
        )

    return Rates(
        duty_rate=duty,
        excise_rate=excise,
        drivetrain=kind,
        country_code=vin_origin.country_code,
        country_name=vin_origin.country_name,
        duty_reason=duty_reason,
        excise_reason=excise_reason,
        assumptions=assumptions,
    )


def rates_for_lot(lot, *, on: Optional[date] = None) -> Rates:
    """Stawki dla lota z aukcji — jedno wywołanie, wszystko wyprowadzone z danych lota."""
    from pricing.import_calculator import engine_liters_from_trim

    return rates_for(
        vin_origin=origin_for_lot(lot),
        drivetrain_guess=detect_for_lot(lot),
        engine_liters=engine_liters_from_trim(
            getattr(lot, "trim", None),
            getattr(lot, "model", None),
        ),
        on=on,
        # Bez marki i modelu detektor napędu widzi samą wersję ("Long Range") i nie ma
        # z czego rozpoznać elektryka. To jedyny przypadek, w którym warto o tym
        # ostrzegać — przy komplecie pól ostrzeżenie odpalałoby się na każdym
        # spalinowym aucie i nauczyłoby wszystkich je ignorować.
        vehicle_identified=bool(getattr(lot, "make", None) and getattr(lot, "model", None)),
    )
