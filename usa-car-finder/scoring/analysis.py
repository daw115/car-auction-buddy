"""
System analizy lotów: grade, pewność danych, pozycja cenowa i werdykt — na jednej skali.

PROBLEM, KTÓRY TEN MODUŁ ROZWIĄZUJE

Trzy giełdy opisują to samo auto zupełnie inaczej:

  Manheim  — pozycjowany raport stanu, gotowy AutoGrade, notowanie MMR, AutoCheck,
             światło aukcyjne, flagi konstrukcji i lakieru. Około 117 pól.
  Copart   — dwa pola opisu szkody, tytuł, klucze, poduszki. Kilkanaście pól.
  IAAI     — jak Copart, bez wersji wyposażenia.

Porównywanie ich „na oko" kończy się tym, że lot z Manheimu zawsze wygląda lepiej,
bo ma więcej danych. To nie jest przewaga auta, tylko przewaga raportu.

Dlatego każda analiza niesie DWIE liczby: ocenę i pewność, na jakiej ona stoi.
Grade 4,5 policzony z pozycjowanego raportu i grade 4,5 zgadnięty z hasła „Front End"
to nie jest ta sama informacja i nie wolno ich pokazywać jako tej samej liczby.

CO JEST OSOBNO, A CO RAZEM

  stan       → `scoring/autograde.py`, skala 0-5, wyłącznie kondycja (metodyka NAAA)
  cena       → `pricing/` — cło z VIN-u, akcyza z napędu, kurs z NBP
  rynek      → MMR z Manheimu; Copart i IAAI go nie mają i trzeba to powiedzieć wprost
  werdykt    → tutaj, z powyższych

Ten podział jest przepisany z metodyki AutoGrade, gdzie grade celowo nie zna ceny ani
przebiegu — wartość powstaje dopiero z połączenia grade'u z rocznikiem, przebiegiem
i notowaniem. Sklejenie tego w jedną liczbę odbiera możliwość zobaczenia, co
zadecydowało.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from scoring.autograde import AutoGrade, grade_for_lot

# Kryteria, których wymaga metodyka AutoGrade. Sprawdzamy, ile z nich realnie widzimy
# dla danego lota — to jest miara pewności oceny, a nie ozdoba raportu.
AUTOGRADE_INPUTS: tuple[tuple[str, str], ...] = (
    ("structural", "uszkodzenie konstrukcji"),
    ("prior_paint", "wcześniejszy lakier"),
    ("body_damage", "uszkodzenia blacharskie (pozycjowane)"),
    ("glass", "szyby"),
    ("wheels", "felgi"),
    ("interior", "wnętrze"),
    ("missing_parts", "brakujące części"),
    ("tires", "bieżnik opon"),
    ("mechanical", "stan mechaniczny"),
    ("keys", "klucze"),
    ("drivable", "czy jeździ"),
)

CONFIDENCE_HIGH = 0.75
CONFIDENCE_MEDIUM = 0.45


@dataclass
class Coverage:
    """Ile z wejść metodyki AutoGrade realnie mamy dla tego lota."""

    source: str
    available: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        total = len(self.available) + len(self.missing)
        return len(self.available) / total if total else 0.0

    @property
    def confidence(self) -> str:
        if self.ratio >= CONFIDENCE_HIGH:
            return "wysoka"
        if self.ratio >= CONFIDENCE_MEDIUM:
            return "średnia"
        return "niska"

    def summary(self) -> str:
        return f"{self.ratio * 100:.0f}% danych ({self.confidence} pewność)"


@dataclass
class LotAnalysis:
    """Komplet tego, co wiemy o jednym locie, razem z tym, czego nie wiemy."""

    lot: Any
    grade: AutoGrade
    coverage: Coverage
    landed_pln: Optional[float] = None
    bid_usd: Optional[float] = None
    mmr_usd: Optional[float] = None
    duty_free: bool = False
    assembly_country: str = "nieznany"
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def value_gap_pct(self) -> Optional[float]:
        """O ile procent stawka jest poniżej notowania rynkowego. None bez MMR.

        Ujemna wartość znaczy, że licytacja przekroczyła notowanie — na Manheimie
        zdarza się to często i jest najczystszym sygnałem, żeby odpuścić.
        """
        if not self.mmr_usd or not self.bid_usd:
            return None
        return (self.mmr_usd - self.bid_usd) / self.mmr_usd * 100

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)

    def label(self) -> str:
        lot = self.lot
        parts = [str(getattr(lot, "year", "") or ""), getattr(lot, "make", "") or "",
                 getattr(lot, "model", "") or "", getattr(lot, "trim", "") or ""]
        return " ".join(p for p in parts if p).strip() or "auto"


# ───────────────────────────────────────────────────── pokrycie danych per źródło


def coverage_for_lot(lot: Any) -> Coverage:
    """Które wejścia AutoGrade mamy dla tego lota.

    Sprawdzamy OBECNOŚĆ danych, nie ich wartość. `hasFrameDamage: False` to informacja
    (wiemy, że konstrukcja jest cała); brak tego pola to niewiedza. Mylenie tych dwóch
    rzeczy jest dokładnie tym błędem, przez który lot z Copartu wygląda jak auto bez
    uszkodzeń tylko dlatego, że nikt ich nie spisał.
    """
    source = (getattr(lot, "source", "") or "").lower()
    listing = getattr(lot, "raw_data", None) or {}
    if isinstance(listing, dict):
        listing = listing.get("listing", listing) or {}

    obecne: dict[str, bool] = {
        "structural": "hasFrameDamage" in listing or bool(getattr(lot, "damage_primary", None)),
        "prior_paint": "hasPriorPaint" in listing,
        "body_damage": bool(getattr(lot, "damage_primary", None)) or "conditionGrade" in listing,
        "glass": "conditionGrade" in listing,
        "wheels": "conditionGrade" in listing,
        "interior": "conditionGrade" in listing or bool(listing.get("interiorType")),
        "missing_parts": "conditionGrade" in listing,
        "tires": any(k in listing for k in ("tireTreadLF", "tireTreadRF", "tireTreadLR", "tireTreadRR")),
        "mechanical": any(k in listing for k in ("greenLight", "redLight", "yellowLight"))
        or bool(getattr(lot, "damage_primary", None)),
        "keys": getattr(lot, "keys", None) is not None,
        "drivable": any(k in listing for k in ("greenLight", "redLight")),
    }

    available = [label for key, label in AUTOGRADE_INPUTS if obecne.get(key)]
    missing = [label for key, label in AUTOGRADE_INPUTS if not obecne.get(key)]
    return Coverage(source=source or "nieznane", available=available, missing=missing)


# ─────────────────────────────────────────────────────────── twarde blokady


def _blockers_for(lot: Any, grade: AutoGrade) -> list[str]:
    """Powody, dla których auta nie proponujemy klientowi niezależnie od ceny.

    Te same, które `scoring/unified.py` traktuje jako dyskwalifikatory — powtórzone
    tutaj, bo analiza bywa uruchamiana na surowej liście, przed pełnym scoringiem.
    """
    listing = getattr(lot, "raw_data", None) or {}
    if isinstance(listing, dict):
        listing = listing.get("listing", listing) or {}

    powody: list[str] = []
    if listing.get("hasFrameDamage") is True:
        powody.append("uszkodzona konstrukcja (flaga aukcji)")
    if listing.get("salvageVehicle") is True:
        powody.append("salvage")
    if listing.get("redLight") is True:
        powody.append("czerwone światło")
    for cap in grade.caps_applied:
        if cap in ("pożar/zalanie/biohazard", "uszkodzenie konstrukcji"):
            powody.append(cap)

    tytul = (getattr(lot, "title_type", "") or "").lower()
    if any(w in tytul for w in ("salvage", "flood", "parts only", "junk")):
        powody.append(f"tytuł: {lot.title_type}")

    status = (listing.get("titleStatus") or "").lower()
    if "absent" in status:
        powody.append("brak tytułu w dniu aukcji (T/A)")

    return list(dict.fromkeys(powody))


# ───────────────────────────────────────────────────────────────── analiza


def analyze(lot: Any, *, settlement: str = "private") -> LotAnalysis:
    """Pełna analiza jednego lota — stan, pewność, cena i blokady."""
    from pricing.tariff import rates_for_lot
    from scoring.budget import landed_cost_for_lot

    listing = getattr(lot, "raw_data", None) or {}
    if isinstance(listing, dict):
        listing = listing.get("listing", listing) or {}

    grade = grade_for_lot(lot)
    coverage = coverage_for_lot(lot)
    rates = rates_for_lot(lot)

    bid = getattr(lot, "current_bid_usd", None) or getattr(lot, "buy_now_price_usd", None)
    landed = landed_cost_for_lot(lot, settlement=settlement) if bid else None

    mmr = listing.get("mmrPrice") or listing.get("averageMMRValuation")
    wyceny = listing.get("valuationsMmr") or {}
    if isinstance(wyceny, dict) and wyceny.get("adjustedValue"):
        mmr = wyceny["adjustedValue"]

    notes: list[str] = list(rates.assumptions)
    if mmr is None and (getattr(lot, "source", "") or "").lower() in ("copart", "iaai"):
        notes.append(
            "Brak notowania rynkowego — Copart i IAAI go nie podają. "
            "Odniesienie do rynku wymaga osobnego zapytania (report/market_price_cache.py)."
        )
    if coverage.confidence == "niska":
        notes.append(
            f"Ocena stanu stoi na {coverage.ratio * 100:.0f}% wejść metodyki — "
            f"brakuje: {', '.join(coverage.missing[:4])}."
        )

    return LotAnalysis(
        lot=lot,
        grade=grade,
        coverage=coverage,
        landed_pln=landed,
        bid_usd=float(bid) if bid else None,
        mmr_usd=float(mmr) if mmr else None,
        duty_free=rates.duty_free,
        assembly_country=rates.country_name,
        blockers=_blockers_for(lot, grade),
        notes=notes,
    )


# ─────────────────────────────────────────────────────────── ranking i wybór


def rank(
    analyses: list[LotAnalysis],
    *,
    budget_pln: Optional[float] = None,
    min_grade: float = 3.5,
) -> list[LotAnalysis]:
    """Loty od najlepszego, po odrzuceniu zablokowanych.

    Kolejność ustala kombinacja czterech rzeczy, w tej wadze:
      * stan (grade) — bo naprawa jest kosztem, którego nie umiemy oszacować zdalnie,
      * pozycja wobec notowania — jedyna miara „czy to tanio", jaką mamy obiektywnie,
      * pewność danych — auto ocenione z pełnego raportu bije auto ocenione z hasła,
      * cło zerowe — kilkanaście tysięcy złotych różnicy przy tej samej stawce.

    Nie sortujemy po samej cenie. Najtańszy lot na liście jest prawie zawsze najtańszy
    z powodu, który zobaczymy dopiero po rozładunku w Polsce.
    """
    kandydaci = [a for a in analyses if not a.blocked and a.grade.grade >= min_grade]
    if budget_pln:
        kandydaci = [a for a in kandydaci if a.landed_pln and a.landed_pln <= budget_pln]

    def klucz(a: LotAnalysis) -> float:
        punkty = a.grade.grade / 5.0 * 40  # stan: 40 pkt
        luka = a.value_gap_pct
        if luka is not None:
            punkty += max(-20.0, min(30.0, luka))  # rynek: -20 do +30 pkt
        punkty += a.coverage.ratio * 20  # pewność: 20 pkt
        if a.duty_free:
            punkty += 10  # cło 0%: 10 pkt
        return punkty

    return sorted(kandydaci, key=klucz, reverse=True)


def best_per_source(
    analyses: list[LotAnalysis],
    *,
    budget_pln: Optional[float] = None,
    min_grade: float = 3.5,
) -> dict[str, Optional[LotAnalysis]]:
    """Najlepszy lot z każdego źródła osobno.

    Osobno, bo źródła nie są porównywalne co do jakości danych: zwycięzca globalny
    byłby prawie zawsze z Manheimu, i to nie dlatego, że auto jest lepsze, tylko
    dlatego, że raport jest bogatszy. Broker ma zobaczyć najlepsze auto z każdej
    giełdy i sam zdecydować, ile płaci za pewność.
    """
    wynik: dict[str, Optional[LotAnalysis]] = {}
    for source in ("copart", "iaai", "manheim"):
        z_zrodla = [a for a in analyses if (getattr(a.lot, "source", "") or "").lower() == source]
        posortowane = rank(z_zrodla, budget_pln=budget_pln, min_grade=min_grade)
        wynik[source] = posortowane[0] if posortowane else None
    return wynik
