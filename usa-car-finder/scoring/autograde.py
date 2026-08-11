"""
Ocena stanu w skali AutoGrade 0–5 — ta sama, którą Manheim drukuje na aukcji.

PO CO TO JEST

Manheim podaje gotowy grade. Copart i IAAI nie podają żadnego — mają tylko opis szkody
("Front End", "Hail", "Water/Flood") i kilka flag. Bez wspólnej skali nie da się
odpowiedzieć na jedyne pytanie, które ma znaczenie przy wyborze: czy lot z Copartu za
28 000 USD jest w lepszym stanie niż ten z Manheimu za 34 000. Ten moduł liczy dla nich
grade w skali Manheimu, żeby obie liczby znaczyły to samo.

SKĄD METODYKA

Z dokumentu „AutoGrade™ Service — How It Works" (NAAA / AutoIMS). AutoGrade to skala
opracowana przez Manheim (patent US 8,230,362) na bazie NAAA Condition Grade Scale.
Bierzemy z niej to, co jest opublikowane: podział pozycji uszkodzeń na trzy poziomy
redukcji, regułę opon i listę rzeczy, które w ocenie NIE biorą udziału.

Sam algorytm ważenia jest opatentowany i nieopublikowany. Nasze wagi są więc
rekonstrukcją, nie kopią: kalibrujemy je tak, żeby auto bez uszkodzeń dawało 5,0,
a znane przypadki z aukcji trafiały w swój grade. Gdy lot ma grade od Manheimu,
używamy JEGO — nasz służy wtedy tylko do porównania i wyłapania rozjazdu.

CZEGO NIE WOLNO TU WPISAĆ

Dokument wymienia wprost, co nie wpływa na grade: przebieg, rocznik, marka, model,
wersja, kolor, opcje, MSRP, announcements, szacowany koszt naprawy i akcja naprawcza.
To nie jest przeoczenie autorów, tylko sedno pomysłu — grade opisuje STAN, a wartość
powstaje dopiero z połączenia grade'u z rocznikiem, przebiegiem i notowaniem MMR.

Ta sama zasada obowiązuje u nas: decyzję zakupową liczy `scoring/unified.py`, gdzie
cena, przebieg i logistyka mają własne składowe. Wpuszczenie ich tutaj zrobiłoby
z grade'u drugą ocenę zakupową, nieporównywalną z liczbą Manheimu — czyli zabiłoby
jedyny powód, dla którego ten moduł istnieje.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

MAX_GRADE = 5.0
MIN_GRADE = 0.0


class Tier(str, Enum):
    """Trzy poziomy redukcji grade'u — dokładnie te z dokumentu AutoGrade."""

    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"


class Severity(str, Enum):
    """Nasilenie pojedynczej pozycji.

    Skala odpowiada tej, którą Manheim pokazuje w Condition Details: szary (brak),
    żółty, pomarańczowy, czerwony (severe).
    """

    NONE = "none"
    LIGHT = "light"
    MODERATE = "moderate"
    SEVERE = "severe"


# Mnożnik nasilenia. Dokument mówi, że „Damage Size / Severity / Number of Occurrences
# per damage line item may have a graduated impact on total grade" — nie podaje wartości,
# więc to jest nasza kalibracja.
_SEVERITY_FACTOR: dict[Severity, float] = {
    Severity.NONE: 0.0,
    Severity.LIGHT: 0.6,
    Severity.MODERATE: 1.0,
    Severity.SEVERE: 1.6,
}

# Bazowa redukcja za pierwsze wystąpienie pozycji z danego poziomu.
_TIER_DEDUCTION: dict[Tier, float] = {
    Tier.MAJOR: 1.30,
    Tier.MODERATE: 0.45,
    Tier.MINOR: 0.15,
}

# Kolejne wystąpienia tej samej pozycji liczą się słabiej. Bez tego dziesięć rys
# parkingowych dawało grade 0, a NAAA wpisuje „parking lot dings, small scratches"
# wprost w definicję grade'u 3 — czyli auta średniego, nie wraku.
_REPEAT_DECAY = 0.55

# Twarde sufity. Niektóre pozycje nie są redukcją punktową, tylko zmieniają klasę auta:
# nie da się mieć auta „clean" z uszkodzoną konstrukcją, choćby reszta była bez zarzutu.
STRUCTURAL_CAP = 2.0
FIRE_FLOOD_CAP = 1.0
NON_DRIVABLE_CAP = 2.5
NO_KEYS_CAP = 3.5

# Próg opon z dokumentu: tread liczy się dopiero od 3/32 w dół i TYLKO wtedy, gdy dla
# tej opony nie ma osobnej pozycji o wymianie — żeby nie liczyć jednej szkody dwa razy.
TIRE_REPLACEMENT_32NDS = 3
TIRE_WEAR_MIN_32NDS = 4
TIRE_WEAR_MAX_32NDS = 7


@dataclass(frozen=True)
class DamageItem:
    """Jedna pozycja z raportu stanu."""

    label: str
    tier: Tier
    severity: Severity = Severity.MODERATE
    count: int = 1
    structural: bool = False
    fire_flood: bool = False
    non_drivable: bool = False
    no_keys: bool = False

    def deduction(self) -> float:
        """Ile punktów zabiera ta pozycja, z uwzględnieniem powtórzeń."""
        base = _TIER_DEDUCTION[self.tier] * _SEVERITY_FACTOR[self.severity]
        total = 0.0
        for occurrence in range(max(1, self.count)):
            total += base * (_REPEAT_DECAY**occurrence)
        return total


@dataclass
class AutoGrade:
    """Wynik oceny stanu razem z tym, co go obniżyło."""

    grade: float
    items: list[DamageItem] = field(default_factory=list)
    caps_applied: list[str] = field(default_factory=list)
    source: str = "obliczony"
    notes: list[str] = field(default_factory=list)
    #: Pasmo, w którym realnie leży grade, gdy nie mamy pozycjowanego raportu stanu.
    #: None znaczy, że ocena stoi na pełnych danych i pasma nie ma.
    band: Optional[tuple[float, float]] = None

    @property
    def certain(self) -> bool:
        return self.band is None

    @property
    def label(self) -> str:
        return grade_label(self.grade)

    @property
    def normalized(self) -> float:
        """Grade przeliczony na 0–1, do użycia jako składowa oceny zakupowej."""
        return max(0.0, min(1.0, self.grade / MAX_GRADE))

    def summary(self) -> str:
        base = f"{self.grade:.1f} {self.label}"
        if self.band:
            base += f" (szacunek, realnie {self.band[0]:.1f}–{self.band[1]:.1f})"
        if self.source != "obliczony":
            base += f" ({self.source})"
        if self.caps_applied:
            base += f" — {', '.join(self.caps_applied)}"
        return base

    def explain(self) -> list[str]:
        """Rozbicie dla brokera: co i ile zabrało."""
        wiersze = [
            f"{i.label}: −{i.deduction():.2f} ({i.tier.value}, {i.severity.value}"
            + (f", ×{i.count}" if i.count > 1 else "")
            + ")"
            for i in sorted(self.items, key=lambda x: x.deduction(), reverse=True)
        ]
        return wiersze + [f"SUFIT: {c}" for c in self.caps_applied] + self.notes


def grade_label(grade: float) -> str:
    """Nazwa klasy — ta, którą aukcja pokazuje obok liczby."""
    if grade >= 4.6:
        return "Extra Clean"
    if grade >= 4.0:
        return "Clean"
    if grade >= 3.0:
        return "Average"
    if grade >= 2.0:
        return "Rough"
    if grade >= 1.0:
        return "Extra Rough"
    return "Salvage"


def grade_from_items(
    items: list[DamageItem],
    *,
    notes: Optional[list[str]] = None,
    condition_report: bool = True,
) -> AutoGrade:
    """Grade z listy pozycji uszkodzeń.

    `condition_report` mówi, czy mamy POZYCJOWANY raport stanu, czy tylko zgrubny opis.
    Ta różnica jest zmierzona i kosztowna:

      * Raport JEST i nie zawiera uwag → 5,0. Tak wygląda auto, które przeszło inspekcję
        czysto („No exterior condition items were reported").
      * Raportu NIE MA → punktem wyjścia jest 4,6, nie 5,0. Na 280 lotach z Manheimu bez
        żadnego sygnału uszkodzenia w polach ustrukturyzowanych prawdziwy grade wyniósł
        średnio 4,58, przy czym 37% z nich nie było „Extra Clean", a najgorsze auto miało
        2,2. Zakładanie piątki zawyżało ocenę systematycznie o 0,42 punktu — czyli
        obiecywało klientowi stan, którego auto nie miało.

    Szczegóły pomiaru i ograniczenia próbki: `scoring/calibration.py`.

    Przy braku raportu wynik niesie `band` — pasmo, w którym grade realnie leży. Broker
    ma zobaczyć, że to szacunek, a nie odczyt.
    """
    from scoring import calibration as cal

    sufit = MAX_GRADE if condition_report else cal.NO_REPORT_PRIOR
    grade = sufit - sum(item.deduction() for item in items)
    caps: list[str] = []

    # Sufity nakładamy PO odjęciu punktów, biorąc wartość niższą. Auto z uszkodzoną
    # konstrukcją i dwudziestoma rysami ma być gorsze niż samo uszkodzenie konstrukcji,
    # ale nigdy lepsze niż sufit dla konstrukcji.
    # Nazwa `limit`, nie `sufit` — zmienna pętli przesłaniała punkt startowy oceny
    # i pasmo niepewności wychodziło odwrócone (5,1–4,6 zamiast 4,0–4,6).
    for warunek, limit, opis in (
        (any(i.fire_flood for i in items), FIRE_FLOOD_CAP, "pożar/zalanie/biohazard"),
        (any(i.structural for i in items), STRUCTURAL_CAP, "uszkodzenie konstrukcji"),
        (any(i.non_drivable for i in items), NON_DRIVABLE_CAP, "nie jeździ"),
        (any(i.no_keys for i in items), NO_KEYS_CAP, "brak kluczy"),
    ):
        if warunek and grade > limit:
            grade = limit
            caps.append(opis)
        elif warunek:
            caps.append(opis)

    wynik = round(max(MIN_GRADE, min(MAX_GRADE, grade)), 1)

    band = None
    if not condition_report:
        # Pasmo przesuwamy razem z odjętymi punktami, ale nie pozwalamy górnej granicy
        # przekroczyć wyniku — inaczej auto z opisaną szkodą wyglądałoby na potencjalnie
        # lepsze niż wynika z tego, co o nim wiemy.
        odjete = sufit - grade
        band = (
            round(max(MIN_GRADE, cal.NO_REPORT_P10 - odjete), 1),
            round(min(wynik, cal.NO_REPORT_P90 - odjete), 1),
        )

    return AutoGrade(
        grade=wynik,
        items=items,
        caps_applied=caps,
        notes=list(notes or []),
        band=band,
    )


# ──────────────────────────────────────────────────── opony wg reguły z dokumentu


def tire_items(treads_32nds: list[Optional[int]], *, replacement_flagged: bool = False) -> list[DamageItem]:
    """Pozycje za opony.

    Reguła jest w dokumencie wprost i jest nieoczywista: głębokość bieżnika NIE liczy
    się do grade'u, chyba że opona ma 3/32 lub mniej ORAZ nie ma dla niej osobnej
    pozycji o wymianie. Chodzi o to, żeby jedna opona nie obniżyła grade'u dwa razy —
    raz przez bieżnik, raz przez wpis o wymianie.
    """
    if replacement_flagged:
        return []

    do_wymiany = sum(1 for t in treads_32nds if t is not None and t <= TIRE_REPLACEMENT_32NDS)
    zuzyte = sum(
        1 for t in treads_32nds if t is not None and TIRE_WEAR_MIN_32NDS <= t <= TIRE_WEAR_MAX_32NDS
    )

    items: list[DamageItem] = []
    if do_wymiany:
        items.append(
            DamageItem("Opony do wymiany (≤3/32)", Tier.MODERATE, Severity.MODERATE, count=do_wymiany)
        )
    if zuzyte:
        items.append(DamageItem("Zużycie opon (4–7/32)", Tier.MINOR, Severity.LIGHT, count=zuzyte))
    return items


# ─────────────────────────────────── mapowanie opisu szkód z Copartu i IAAI


# Copart i IAAI opisują szkodę jednym z kilkudziesięciu haseł. Mapujemy je na poziomy
# redukcji z dokumentu AutoGrade. Kolejność ma znaczenie — pierwszy trafiony wzorzec
# wygrywa, więc cięższe przypadki muszą stać wyżej ("Burn - Engine" przed "Engine").
_DAMAGE_MAP: tuple[tuple[str, str, Tier, Severity, dict], ...] = (
    # Major — zmieniają klasę auta, nie tylko punktację
    (r"water|flood|zalan", "Zalanie", Tier.MAJOR, Severity.SEVERE, {"fire_flood": True}),
    (r"burn|fire|pożar|pozar", "Pożar", Tier.MAJOR, Severity.SEVERE, {"fire_flood": True}),
    (r"biohazard|hazmat", "Biohazard", Tier.MAJOR, Severity.SEVERE, {"fire_flood": True}),
    (r"rollover|roll over", "Dachowanie", Tier.MAJOR, Severity.SEVERE, {"structural": True}),
    (r"undercarriage|frame|structur", "Konstrukcja", Tier.MAJOR, Severity.SEVERE, {"structural": True}),
    (r"hail", "Grad", Tier.MAJOR, Severity.MODERATE, {}),
    (r"mechanical|engine|transmission|silnik", "Mechanika", Tier.MAJOR, Severity.SEVERE, {"non_drivable": True}),
    (r"stripped|missing parts", "Auto rozkompletowane", Tier.MAJOR, Severity.SEVERE, {}),
    (r"all over", "Uszkodzenia na całym aucie", Tier.MAJOR, Severity.SEVERE, {}),
    # Moderate — realna blacharka, ale auto zostaje autem
    (r"front end|front", "Uszkodzenie przodu", Tier.MODERATE, Severity.MODERATE, {}),
    (r"rear end|rear", "Uszkodzenie tyłu", Tier.MODERATE, Severity.MODERATE, {}),
    (r"side|left|right", "Uszkodzenie boku", Tier.MODERATE, Severity.MODERATE, {}),
    (r"vandalism", "Wandalizm", Tier.MODERATE, Severity.MODERATE, {}),
    (r"glass|windshield|szyb", "Szyby", Tier.MODERATE, Severity.MODERATE, {}),
    (r"wheel|rim", "Felgi", Tier.MODERATE, Severity.LIGHT, {}),
    (r"interior", "Wnętrze", Tier.MODERATE, Severity.LIGHT, {}),
    (r"suspension", "Zawieszenie", Tier.MODERATE, Severity.MODERATE, {}),
    # Minor — kosmetyka
    (r"minor dent|dent|scratch|rysy", "Wgniecenia i rysy", Tier.MINOR, Severity.LIGHT, {}),
    (r"bumper|zderzak", "Zderzak", Tier.MINOR, Severity.LIGHT, {}),
    (r"normal wear|wear", "Normalne zużycie", Tier.MINOR, Severity.LIGHT, {}),
)

_COMPILED = tuple((re.compile(p, re.IGNORECASE), *rest) for p, *rest in _DAMAGE_MAP)


def items_from_damage_text(*descriptions: Optional[str]) -> list[DamageItem]:
    """Pozycje uszkodzeń z opisów aukcyjnych ("Front End", "Water/Flood").

    Każdy opis daje najwyżej jedną pozycję — Copart podaje primary i secondary jako
    dwa osobne pola i to są dwie różne szkody. Zdublowane hasła scalamy, żeby
    "Front End" w obu polach nie liczyło się jak dwa uderzenia.
    """
    znalezione: dict[str, DamageItem] = {}
    for description in descriptions:
        tekst = (description or "").strip()
        if not tekst:
            continue
        for pattern, label, tier, severity, flags in _COMPILED:
            if pattern.search(tekst):
                if label not in znalezione:
                    znalezione[label] = DamageItem(label, tier, severity, **flags)
                break
    return list(znalezione.values())


def has_condition_report(lot: Any) -> bool:
    """Czy dla tego lota istnieje POZYCJOWANY raport stanu.

    To jest rozstrzygnięcie o tym, czy wolno startować od 5,0, więc warunek jest wąski:
    wymagamy dowodu, że raport istnieje, a nie braku dowodu, że go nie ma.

    Copart i IAAI nie robią pozycjowanych raportów w ogóle — dają dwa pola opisu szkody.
    Dla nich ta funkcja zawsze zwraca False i tak ma być.
    """
    listing = getattr(lot, "raw_data", None) or {}
    if isinstance(listing, dict):
        listing = listing.get("listing", listing) or {}
    return bool(listing.get("conditionReportUrl") or listing.get("conditionGrade") is not None)


def grade_for_lot(lot: Any) -> AutoGrade:
    """Grade dla lota z dowolnego źródła.

    Gdy aukcja podaje własny grade (Manheim), to ON jest wynikiem — nasza rekonstrukcja
    nie ma prawa nadpisywać liczby, którą kupujący widzi na ekranie. Liczymy ją wtedy
    równolegle i odnotowujemy rozjazd, bo różnica większa niż pół punktu znaczy, że
    albo raport stanu mówi coś, czego grade nie pokazuje, albo nasze mapowanie się myli.
    """
    listing = getattr(lot, "raw_data", None) or {}
    if isinstance(listing, dict):
        listing = listing.get("listing", listing) or {}

    items = items_from_damage_text(
        getattr(lot, "damage_primary", None),
        getattr(lot, "damage_secondary", None),
    )

    # Sygnały spoza opisu szkody, wprost wymienione w dokumencie jako Major.
    if getattr(lot, "keys", None) is False:
        items.append(DamageItem("Brak kluczy", Tier.MAJOR, Severity.SEVERE, no_keys=True))
    if getattr(lot, "airbags_deployed", None) is True:
        items.append(
            DamageItem("Poduszki odpalone", Tier.MAJOR, Severity.SEVERE, structural=True)
        )

    tread = [
        _as_int(listing.get(k))
        for k in ("tireTreadLF", "tireTreadRF", "tireTreadLR", "tireTreadRR")
    ]
    if any(t is not None for t in tread):
        items.extend(tire_items(tread, replacement_flagged=bool(listing.get("tireReplacement"))))

    obliczony = grade_from_items(items, condition_report=has_condition_report(lot))

    podany = _as_float(listing.get("conditionGrade"))
    if podany is None:
        return obliczony

    rozjazd = abs(podany - obliczony.grade)
    notes = [f"nasza rekonstrukcja: {obliczony.grade:.1f}"]
    if rozjazd >= 0.5:
        notes.append(
            f"ROZJAZD {rozjazd:.1f} pkt wobec grade'u aukcji — sprawdź raport stanu przed licytacją"
        )
    return AutoGrade(
        grade=round(podany, 1),
        items=obliczony.items,
        caps_applied=obliczony.caps_applied,
        source="grade aukcji",
        notes=notes,
    )


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
