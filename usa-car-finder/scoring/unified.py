"""
Ujednolicona ocena lota 0-10, liczona deterministycznie — bez LLM-a.

Dlaczego nie prompt: dotychczasowa ocena to jeden system prompt napisany pod aukcje
powypadkowe ("Analizujesz dane z aukcji Copart i IAAI"). Model dostawał tam reguły w
rodzaju "+1.5 za wschodni stan" i miał je dodawać w głowie — wyniku nie dało się ani
odtworzyć, ani przetestować. Gorzej: Manheim był tym promptem KARANY, bo auto bez szkód
nie pasowało do żadnej kategorii uszkodzeń i lądowało w gałęzi "nieprecyzyjny opis".

Tutaj ocena jest arytmetyką na sygnałach, a LLM dostaje ją gotową i pisze uzasadnienie.

Dwie zasady, na których stoi porównywalność między giełdami:

1. WAGI SIĘ RENORMALIZUJĄ. Copart nie publikuje MMR, Manheim nie ma taksonomii szkód.
   Gdyby brakujący sygnał liczył się jako zero, każde źródło byłoby karane za to, czego
   fizycznie nie podaje. Waga składowej bez danych rozkłada się proporcjonalnie na resztę.
   To samo dotyczy kryteriów klienta: lead "suv, 50-60 tys" nie poda rocznika i nie może
   przez to tracić punktów.

2. DYSKWALIFIKATORY STOJĄ PONAD WAGAMI. Zalanie, pożar czy potwierdzona belka nie
   obniżają punktacji — przekreślają lot. Inaczej dobra cena potrafiłaby przegłosować
   szkodę, której broker nigdy nie zaakceptuje.
   Budżet dyskwalifikatorem NIE jest: cena ponad sufit daje osobny werdykt
   (BudgetVerdict, rekomendacja PONAD BUDŻET) i nie rusza oceny. "Za drogie" to nie
   to samo co "bez wartości" — auto ponad budżet bywa najlepsze w stawce, a decyzję
   o jego zaproponowaniu podejmuje broker, nie filtr.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

from parser.models import CarLot, ClientCriteria
from scoring.budget import BudgetCeiling
from scoring.regions import region_of

RiskAppetite = Literal["none", "light", "repairable"]

# Wagi bazowe. Suma 1.0; po odrzuceniu składowych bez danych są renormalizowane.
BASE_WEIGHTS: dict[str, float] = {
    "price_vs_market": 0.25,
    "condition": 0.20,
    "title": 0.15,
    "mileage": 0.15,
    "logistics": 0.10,
    "trust": 0.10,
    "criteria_fit": 0.05,
}

LABELS: dict[str, str] = {
    "price_vs_market": "Cena vs rynek",
    "condition": "Stan techniczny",
    "title": "Tytuł i historia",
    "mileage": "Przebieg vs rocznik",
    "logistics": "Logistyka",
    "trust": "Wiarygodność oferty",
    "criteria_fit": "Dopasowanie do klienta",
}

# Progi rekomendacji. POLECAM celowo wysoko — broker ma dostać 3-4 pozycje, nie listę.
RECOMMEND_THRESHOLD = 7.5
# Osobna rekomendacja zamiast ODRZUĆ: auto jest dobre, tylko dziś za drogie.
OVER_BUDGET = "PONAD BUDŻET"
RISK_THRESHOLD = 5.0

_FLOOD_FIRE = re.compile(r"flood|water damage|fire|burn", re.IGNORECASE)
_FRAME = re.compile(r"\bframe\b|structural", re.IGNORECASE)


@dataclass(frozen=True)
class ClientProfile:
    """Preferencje klienta, których nie ma dziś w ClientCriteria.

    Trzymane osobno, żeby scoring dało się używać, zanim model kryteriów urośnie
    o listy modeli, segment i budżet w PLN (zadanie #1).
    """

    risk: RiskAppetite = "light"
    require_clean_title: bool = False
    # Sufit podany wprost — używany, gdy znamy go z góry.
    budget: Optional[BudgetCeiling] = None
    # Budżet "pod klucz" w PLN. Sufit z niego liczymy PER LOT, bo zależy od stanu USA:
    # towing wchodzi do podstawy celnej i mnoży się przez cło, VAT i akcyzę.
    budget_pln: Optional[float] = None
    settlement: str = "private"


@dataclass
class Component:
    key: str
    label: str
    value: float  # 0-1
    weight: float  # waga po renormalizacji
    detail: str

    @property
    def points(self) -> float:
        """Wkład składowej w końcową ocenę, w punktach 0-10."""
        return self.value * self.weight * 10.0


@dataclass(frozen=True)
class BudgetVerdict:
    """Ile to auto kosztuje pod klucz i czy mieści się w budżecie klienta.

    Przekroczenie budżetu to NIE jest wada auta. Auto ponad budżet może być
    najlepsze w stawce, tylko na dziś za drogie — broker musi widzieć jedno
    i drugie, żeby móc świadomie zaproponować dołożenie.
    """

    price_usd: float
    ceiling_usd: float
    landed_pln: Optional[float] = None
    budget_pln: Optional[float] = None

    @property
    def over(self) -> bool:
        return self.price_usd > self.ceiling_usd

    @property
    def gap_pln(self) -> Optional[float]:
        """O ile złotych pod klucz auto przekracza budżet."""
        if self.landed_pln is None or self.budget_pln is None:
            return None
        return round(self.landed_pln - self.budget_pln, 2)

    def note(self) -> str:
        if not self.over:
            return ""
        gap = self.gap_pln
        if gap and gap > 0:
            return f"ponad budżet o {gap:,.0f} zł".replace(",", "\u00a0")
        return (
            f"cena {self.price_usd:,.0f} USD ponad sufit {self.ceiling_usd:,.0f} USD".replace(
                ",", "\u00a0"
            )
        )

    def as_dict(self) -> dict:
        return {
            "over": self.over,
            "price_usd": round(self.price_usd, 2),
            "ceiling_usd": round(self.ceiling_usd, 2),
            "landed_pln": self.landed_pln,
            "budget_pln": self.budget_pln,
            "gap_pln": self.gap_pln,
            "note": self.note(),
        }


@dataclass
class LotScore:
    score: float
    recommendation: str
    components: list[Component] = field(default_factory=list)
    disqualifiers: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    budget: Optional[BudgetVerdict] = None

    @property
    def over_budget(self) -> bool:
        return bool(self.budget and self.budget.over)

    def explain(self) -> str:
        """Jednolinijkowe rozbicie — broker ma widzieć DLACZEGO, nie samą liczbę."""
        if self.disqualifiers:
            return "ODRZUĆ: " + "; ".join(self.disqualifiers)
        parts = [f"{c.label} {c.value:.2f}×{c.weight:.0%}={c.points:.1f}" for c in self.components]
        body = f"{self.score:.1f}/10 — " + ", ".join(parts)
        if self.over_budget:
            return f"{OVER_BUDGET} ({self.budget.note()}) — {body}"
        return body


def _ramp(x: float, points: list[tuple[float, float]]) -> float:
    """Interpolacja odcinkowa po punktach (x rosnąco), z przycięciem na końcach."""
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            span = x1 - x0
            return y0 if span == 0 else y0 + (y1 - y0) * (x - x0) / span
    return points[-1][1]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _listing(lot: CarLot) -> dict:
    raw = lot.raw_data or {}
    listing = raw.get("listing")
    return listing if isinstance(listing, dict) else {}


def _as_float(value: Any) -> Optional[float]:
    try:
        result = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _ceiling_for(lot: CarLot, profile: "ClientProfile") -> Optional[BudgetCeiling]:
    """Sufit ceny aukcyjnej dla tego konkretnego lota."""
    if profile.budget:
        return profile.budget
    if not profile.budget_pln:
        return None
    from scoring.budget import max_bid_for_budget

    return max_bid_for_budget(
        profile.budget_pln, settlement=profile.settlement, state=lot.location_state
    )


def profile_from_criteria(criteria: ClientCriteria, **over) -> "ClientProfile":
    """Profil klienta z kryteriów — budżet i forma zakupu wprost od niego."""
    values = {"budget_pln": criteria.budget_pln(), "settlement": criteria.settlement}
    values.update(over)
    return ClientProfile(**values)


def _lot_price(lot: CarLot) -> Optional[float]:
    """Cena, po której realnie da się kupić — bid gdy trwa licytacja, inaczej buy now."""
    return lot.current_bid_usd or lot.buy_now_price_usd


def _damage_text(lot: CarLot) -> str:
    raw = lot.raw_data or {}
    return " ".join(
        str(part)
        for part in (
            lot.damage_primary,
            lot.damage_secondary,
            lot.title_type,
            raw.get("listing_damage_text"),
        )
        if part
    )


# --------------------------------------------------------------- dyskwalifikatory


def disqualify(lot: CarLot, profile: ClientProfile) -> list[str]:
    """Powody, dla których lot odpada niezależnie od punktacji."""
    reasons: list[str] = []
    listing = _listing(lot)
    damage = _damage_text(lot)

    if _FLOOD_FIRE.search(damage):
        reasons.append("zalanie lub pożar")

    frame_flags = [
        listing.get("hasFrameDamage") is True,
        bool(_FRAME.search(damage)),
    ]
    vision = (lot.raw_data or {}).get("frame_damage_check") or {}
    if (
        isinstance(vision, dict)
        and vision.get("frame_damaged") is True
        and float(vision.get("confidence") or 0) >= 0.5
        # images_inaccessible = vision nie widział zdjęć, więc jego werdykt nic nie znaczy
        and not vision.get("images_inaccessible")
    ):
        frame_flags.append(True)
    if any(frame_flags):
        reasons.append("uszkodzenie konstrukcji")

    salvage = listing.get("salvageVehicle") is True or "salvage" in (lot.title_type or "").lower()
    if profile.require_clean_title and salvage:
        reasons.append("tytuł salvage przy wymaganym Clean")

    if profile.risk == "none" and listing.get("redLight") is True:
        reasons.append("czerwone światło (sprzedaż as-is)")

    return reasons


def budget_verdict(lot: CarLot, profile: ClientProfile) -> Optional[BudgetVerdict]:
    """Relacja ceny tego lota do budżetu klienta — bez wyroku o jakości auta.

    Świadomie NIE jest dyskwalifikatorem. Auto ponad budżet zostaje w wynikach
    z policzoną oceną, tylko wyraźnie oznaczone: broker sam decyduje, czy
    zaproponować je klientowi, zamiast dowiadywać się, że coś zniknęło z listy.
    """
    price = _lot_price(lot)
    ceiling = _ceiling_for(lot, profile)
    if not price or not ceiling:
        return None

    landed: Optional[float] = None
    if ceiling.budget_pln:
        try:
            from scoring.budget import landed_cost_pln

            landed = round(
                landed_cost_pln(
                    price, settlement=profile.settlement, state=lot.location_state
                ),
                2,
            )
        except Exception:  # kalkulator importu jest opcjonalny w testach jednostkowych
            landed = None

    return BudgetVerdict(
        price_usd=price,
        ceiling_usd=ceiling.max_bid_usd,
        landed_pln=landed,
        budget_pln=ceiling.budget_pln,
    )


# ------------------------------------------------------------------- składowe


def _price_vs_market(lot: CarLot, criteria: ClientCriteria, profile: ClientProfile):
    """Ile poniżej rynku jest ta oferta.

    Manheim podaje MMR (Manheim Market Report) — benchmark hurtowy dla dokładnie tego
    modelu. Na 898 realnych lotach mediana delty wynosi -7%, czyli większość ofert stoi
    POWYŻEJ rynku; okazje siedzą w dodatnim ogonie i to je ta składowa wyławia.
    Copart/IAAI nie mają MMR — tam benchmarkiem jest historyczna cena sprzedaży z bidfax
    albo średnia rynkowa z AutoHelperBota.
    """
    price = _lot_price(lot)
    if not price:
        return None

    listing = _listing(lot)
    raw = lot.raw_data or {}
    benchmark = None
    source = ""
    if lot.source == "manheim":
        benchmark = _as_float(listing.get("mmrPrice")) or _as_float(listing.get("averageMMRValuation"))
        source = "MMR"
    if benchmark is None:
        benchmark = _as_float(raw.get("bidfax_sold_price"))
        source = source or "bidfax"
    if benchmark is None:
        benchmark = _as_float(raw.get("average_price_usd"))
        source = source or "średnia rynkowa"
    if not benchmark:
        return None

    delta_pct = (benchmark - price) / benchmark * 100.0
    value = _ramp(delta_pct, [(-20.0, 0.0), (0.0, 0.5), (15.0, 1.0)])
    return value, f"{delta_pct:+.0f}% wzgl. {source} ({benchmark:,.0f} USD)"


# Cięższa szkoda = niższa wartość. Tabela świadomie lokalna: scraper/base.py ciągnie
# Playwrighta, a scoring ma działać bez przeglądarki.
_DAMAGE_VALUE: list[tuple[re.Pattern[str], float, str]] = [
    (re.compile(r"normal wear", re.I), 0.95, "normalne zużycie"),
    (re.compile(r"minor dent|scratch|dent", re.I), 0.85, "kosmetyka"),
    (re.compile(r"hail", re.I), 0.75, "grad"),
    (re.compile(r"vandalism|theft", re.I), 0.6, "wandalizm/kradzież"),
    (re.compile(r"rear", re.I), 0.5, "tył"),
    (re.compile(r"side", re.I), 0.45, "bok"),
    (re.compile(r"front", re.I), 0.4, "przód"),
    (re.compile(r"undercarriage", re.I), 0.25, "podwozie"),
    (re.compile(r"mechanical|engine|transmission", re.I), 0.2, "mechanika"),
    (re.compile(r"rollover|all over", re.I), 0.1, "dachowanie"),
]


def _condition(lot: CarLot, criteria: ClientCriteria, profile: ClientProfile):
    listing = _listing(lot)

    grade = _as_float(listing.get("conditionGrade"))
    if grade is not None:
        # Manheim ocenia stan w skali CR 0-5; to odpowiednik "typu szkody" z Copartu.
        value = _ramp(grade, [(2.0, 0.0), (3.5, 0.5), (5.0, 1.0)])
        notes = [f"CR {grade:.1f}"]
        if listing.get("hasPriorPaint") is True:
            value -= 0.05
            notes.append("lakierowane")
        if listing.get("yellowLight") is True:
            value -= 0.10
            notes.append("żółte światło")
        if listing.get("redLight") is True:
            value -= 0.25
            notes.append("czerwone światło")
        if listing.get("greenLight") is True:
            notes.append("ride & drive")
        return _clamp01(value), ", ".join(notes)

    damage = _damage_text(lot)
    if not damage.strip():
        return None
    for pattern, value, label in _DAMAGE_VALUE:
        if pattern.search(damage):
            if lot.airbags_deployed:
                value -= 0.2
                label += ", poduszki"
            return _clamp01(value), label
    return 0.35, "opis szkód nierozpoznany"


def _title(lot: CarLot, criteria: ClientCriteria, profile: ClientProfile):
    listing = _listing(lot)
    title = (lot.title_type or "").lower()

    if lot.source == "manheim":
        autocheck = listing.get("autocheck") if isinstance(listing.get("autocheck"), dict) else {}
        if listing.get("salvageVehicle") is True:
            return 0.2, "salvage"
        if autocheck.get("titleAndProblemCheckOK") is False:
            return 0.4, "autocheck zgłasza problem z tytułem"
        if autocheck.get("titleAndProblemCheckOK") is True:
            return 1.0, "autocheck bez zastrzeżeń"
        # titleStatus na Manheimie to najczęściej "Not Specified" — brak sygnału.
        return None

    if not title:
        return None
    if "parts" in title:
        return 0.0, "parts only"
    if "rebuilt" in title:
        return 0.35, "rebuilt"
    if "salvage" in title:
        return 0.6, "salvage"
    if "clean" in title:
        return 1.0, "clean"
    return None


def _mileage(lot: CarLot, criteria: ClientCriteria, profile: ClientProfile):
    if not lot.odometer_mi or not lot.year:
        return None
    age = max(1, datetime.now(timezone.utc).year - int(lot.year) + 1)
    per_year = lot.odometer_mi / age
    value = _ramp(per_year, [(10_000, 1.0), (15_000, 0.5), (25_000, 0.0)])
    return value, f"{per_year:,.0f} mil/rok ({lot.odometer_mi:,} mi, {lot.year})"


def _logistics(lot: CarLot, criteria: ClientCriteria, profile: ClientProfile):
    region = region_of(lot.location_state)
    if region == "unknown":
        return None
    value = {"east": 1.0, "central": 0.6, "west": 0.25}[region]
    label = {"east": "wschód", "central": "centrum", "west": "zachód"}[region]
    return value, f"{label} ({lot.location_state})"


def _trust(lot: CarLot, criteria: ClientCriteria, profile: ClientProfile):
    listing = _listing(lot)

    if lot.source == "manheim":
        notes: list[str] = []
        rating = _as_float(listing.get("sellerRating"))
        value = _ramp(rating, [(2.0, 0.2), (3.5, 0.6), (5.0, 1.0)]) if rating else 0.6
        if rating:
            notes.append(f"sprzedawca {rating:.1f}/5")
        if listing.get("asIs") is True:
            value -= 0.25
            notes.append("as-is")
        if listing.get("isCertified") is True:
            value += 0.10
            notes.append("certyfikowane")
        arbitration = _as_float(listing.get("arbitrationRating"))
        if arbitration is not None and arbitration <= 1:
            value -= 0.10
            notes.append("niska ocena arbitrażu")
        return _clamp01(value), ", ".join(notes) or "brak zastrzeżeń"

    if lot.seller_type == "insurance":
        return 1.0, "ubezpieczyciel"
    if lot.seller_type == "dealer":
        return 0.6, "dealer"
    return None


def _criteria_fit(lot: CarLot, criteria: ClientCriteria, profile: ClientProfile):
    """Zgodność z tym, co klient FAKTYCZNIE powiedział.

    Kryteria niepodane są pomijane, nie zerowane — lead "suv, 50-60 tys" nie może tracić
    punktów za to, że klient nie podał rocznika.
    """
    checks: list[float] = []
    notes: list[str] = []

    if (criteria.year_from or criteria.year_to) and lot.year:
        ok = (not criteria.year_from or lot.year >= criteria.year_from) and (
            not criteria.year_to or lot.year <= criteria.year_to
        )
        checks.append(1.0 if ok else 0.0)
        notes.append("rocznik " + ("ok" if ok else "poza zakresem"))

    if criteria.max_odometer_mi and lot.odometer_mi:
        ok = lot.odometer_mi <= criteria.max_odometer_mi
        checks.append(1.0 if ok else 0.0)
        notes.append("przebieg " + ("ok" if ok else "ponad limit"))

    price = _lot_price(lot)
    ceiling = _ceiling_for(lot, profile)
    if ceiling and price:
        # Zapas budżetu: lot za 4 tys. przy sufcie 8 tys. zostawia miejsce na naprawę
        # i transport, więc jest wart więcej niż taki za 7 900.
        headroom = (ceiling.max_bid_usd - price) / ceiling.max_bid_usd
        checks.append(_ramp(headroom * 100, [(0.0, 0.4), (20.0, 0.8), (40.0, 1.0)]))
        notes.append(f"zapas budżetu {headroom * 100:.0f}%")

    if not checks:
        return None
    return sum(checks) / len(checks), ", ".join(notes)


_COMPONENTS: dict[str, Callable] = {
    "price_vs_market": _price_vs_market,
    "condition": _condition,
    "title": _title,
    "mileage": _mileage,
    "logistics": _logistics,
    "trust": _trust,
    "criteria_fit": _criteria_fit,
}


def score_lot(
    lot: CarLot,
    criteria: ClientCriteria,
    profile: Optional[ClientProfile] = None,
) -> LotScore:
    """Ocena 0-10 z rozbiciem na składowe."""
    profile = profile or ClientProfile()

    verdict = budget_verdict(lot, profile)

    reasons = disqualify(lot, profile)
    if reasons:
        return LotScore(
            score=0.0, recommendation="ODRZUĆ", disqualifiers=reasons, budget=verdict
        )

    available: list[tuple[str, float, str]] = []
    skipped: list[str] = []
    for key, fn in _COMPONENTS.items():
        result = fn(lot, criteria, profile)
        if result is None:
            skipped.append(LABELS[key])
            continue
        value, detail = result
        available.append((key, _clamp01(value), detail))

    if not available:
        return LotScore(
            score=0.0,
            recommendation="ODRZUĆ",
            disqualifiers=["brak jakichkolwiek danych do oceny"],
            skipped=skipped,
            budget=verdict,
        )

    # Renormalizacja: waga składowych bez danych rozkłada się na dostępne.
    total_weight = sum(BASE_WEIGHTS[key] for key, _, _ in available)
    components = [
        Component(
            key=key,
            label=LABELS[key],
            value=value,
            weight=BASE_WEIGHTS[key] / total_weight,
            detail=detail,
        )
        for key, value, detail in available
    ]

    score = round(sum(c.points for c in components), 2)
    if score >= RECOMMEND_THRESHOLD:
        recommendation = "POLECAM"
    elif score >= RISK_THRESHOLD:
        recommendation = "RYZYKO"
    else:
        recommendation = "ODRZUĆ"

    # Budżet nadpisuje rekomendację, ale NIE ocenę. Ocena dalej mówi, ile to auto
    # jest warte; rekomendacja mówi, że dziś nie mieści się w kwocie klienta.
    if verdict and verdict.over:
        recommendation = OVER_BUDGET

    return LotScore(
        score=score,
        recommendation=recommendation,
        components=components,
        skipped=skipped,
        budget=verdict,
    )


def rank_lots(
    lots: list[CarLot],
    criteria: ClientCriteria,
    profile: Optional[ClientProfile] = None,
    *,
    limit: int = 4,
    min_score: float = RISK_THRESHOLD,
    include_over_budget: bool = False,
) -> list[tuple[CarLot, LotScore]]:
    """Najlepsze oferty dla klienta, posortowane malejąco.

    Domyślnie 4 pozycje i próg jakości — lepiej pokazać trzy dobre niż cztery z
    zapchajdziurą. Loty poniżej progu nie trafiają do oferty nawet gdy brakuje lepszych.

    Loty ponad budżet są domyślnie pomijane, ale dopuszczalne jawną decyzją
    (include_over_budget) — wtedy lądują na końcu, za wszystkim, co się mieści.
    """
    scored = [(lot, score_lot(lot, criteria, profile)) for lot in lots]
    qualified = [
        item
        for item in scored
        if item[1].score >= min_score and (include_over_budget or not item[1].over_budget)
    ]
    qualified.sort(key=lambda item: (item[1].over_budget, -item[1].score))
    return qualified[:limit]
