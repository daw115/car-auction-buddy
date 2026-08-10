"""
Oferta dla klienta: liczby liczy Python, słowa pisze model.

Poprzednia wersja dawała modelowi cały plik agenta, komplet danych z aukcji i polecenie
"wygeneruj HTML, ceny przelicz USD × 4,0". Model liczył więc cenę końcową sam — i mylił
się o kilkadziesiąt procent, bo kurs to nie kalkulacja importu. Lot za 10 000 USD wychodził
w mailu jako 40 000 zł, podczas gdy klient płaci za niego ~78 000 zł. To nie jest literówka
w prompcie, tylko zła architektura: dokument, który jest de facto ofertą handlową, nie może
mieć liczb pochodzących z generowania tekstu.

Podział odpowiedzialności jest więc twardy:

  Python  — wszystko, co da się policzyć lub przepisać: cena pod klucz, przebieg, tłumaczenie
            żargonu aukcyjnego, prowizja, terminy, HTML. Każda liczba w ofercie pochodzi
            z pricing/import_calculator.py.
  Model   — wyłącznie proza: jedno zdanie wstępu, jedno zdanie "dlaczego to auto", zdanie
            zamykające, notatka dla brokera. Proza z cyframi jest odrzucana (_clean_prose),
            bo cyfra od modelu to liczba, której nikt nie policzył.

Dzięki temu awaria modelu nie blokuje pipeline'u: gdy LLM padnie, oferta i tak powstaje,
tylko bez zdań "dlaczego". Poprzednia wersja rzucała wyjątkiem po sześciu krokach pipeline'u
(scrape + analiza + ranking) i klient nie dostawał nic.

Założenia biznesowe, na których stoi treść — opisane szerzej w agent-oferta-auto-usa.md:

  * Jesteśmy BROKEREM, nie komisem. Nie mamy auta na placu, nie naprawiamy go i nie dajemy
    gwarancji na naprawę. Zarabiamy prowizję. Oferta nie może obiecywać niczego z modelu
    "kupiłem, naprawiłem, sprzedaję".
  * Klient myśli w złotówkach pod klucz. Cena aukcyjna w USD nic mu nie mówi (ta sama
    zasada co w report/whatsapp.py).
  * Cena z aukcji to STAWKA, nie cena. Aukcja może pójść wyżej, więc mówimy "przy tej
    stawce", a nie "cena tego auta".
  * Klient widzi 3-4 auta. Więcej paraliżuje wybór (main_automation.CLIENT_OFFERS_COUNT).
  * Wewnętrzna ocena 0-10 nigdy nie opuszcza firmy.
"""
from __future__ import annotations

import html as html_lib
import json
import math
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

from ai import claude_code
from parser.models import AnalyzedLot, CarLot, ClientCriteria
from scoring.unified import OVER_BUDGET
from pricing.import_calculator import (
    BROKER_FEE_KEY,
    EXCISE_EV,
    EXCISE_LARGE,
    EXCISE_SMALL,
    SETTLEMENT_TOTAL_KEY,
    calculate_lot_import_costs,
    client_price_pln,
    engine_liters_from_trim,
    excise_rate_for,
)

AGENT_PROMPT_PATH = Path(__file__).parent.parent.parent / "agent-oferta-auto-usa.md"

Settlement = Literal["private", "company"]
FeeTier = Literal["basic", "premium"]

# ─────────────────────────────────────────────────────────────── polityka oferty

# Tyle aut widzi klient. Reszta idzie tylko do briefu brokera.
MAX_CLIENT_CARS = 4

# Prowizja doliczana do ceny pokazywanej klientowi. Domyślnie basic — premium to
# świadoma decyzja handlowa, a nie wartość, którą ma zgadywać generator.
DEFAULT_FEE_TIER: FeeTier = "basic"

# Cenę zaokrąglamy W GÓRĘ. Kwota niższa od rzeczywistej to reklamacja przy odbiorze,
# kwota wyższa to co najwyżej rabat przy podsumowaniu.
PRICE_ROUNDING_PLN = 500

# ───────────────────────────────────────────────── czego w ofercie być nie może

# Zakazane zwroty (z v1 agenta) + żargon, którego klient nie zna (z report/whatsapp.py
# i hybrid_reports.py). Sprawdzamy po normalizacji do lowercase, na rdzeniach — "okazji
# życia" ma wpaść tak samo jak "okazja życia".
BANNED_FRAGMENTS = (
    "okazj",           # "okazja życia", "niepowtarzalna okazja"
    "must have",
    "rewelac",
    "jak nowe",
    "stan idealny",
    "nie do odrzucenia",
    "czystym sumieniem",
    "ostatnia sztuka",
    "tylko dziś",
    "tylko dzis",
    "gwarancj",        # broker nie daje gwarancji na auto z aukcji
    "zysk",            # nie obiecujemy zarobku na aucie
    "pewna inwestycj",
    "bezwypadkow",     # auto z Copart/IAAI z definicji nie jest bezwypadkowe
)

JARGON_FRAGMENTS = (
    "score",
    "/10",
    "salvage",
    "rebuilt",
    "clean title",
    "run & drive",
    "run and drive",
    "prefiltr",
    "lot #",
    "copart",
    "iaai",
    "manheim",
)

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]",
    flags=re.UNICODE,
)
_DIGIT = re.compile(r"\d")
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Powitanie pisze szablon ("Dzień dobry, Marek,"), więc model nie ma się witać drugi raz.
# Pomimo instrukcji w prompcie potrafi zacząć od "Panie Marku" i wychodzi z tego
# "Dzień dobry, Marek, Panie Marku, znaleźliśmy..." — ucinamy to deterministycznie.
_GREETING = re.compile(
    r"^\s*(dzień dobry|dzien dobry|witam serdecznie|witam|szanowny panie|szanowna pani|panie|pani)\b[\s,!.–-]*",
    re.IGNORECASE,
)
_VOCATIVE = re.compile(r"^[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+[\s,!.–-]+")

# ───────────────────────────────────────────────────── tłumaczenie żargonu na PL

# Kolejność ma znaczenie: "front end" musi trafić przed samym "front".
_DAMAGE_PL: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"normal wear", re.I), "normalne zużycie"),
    (re.compile(r"minor dent|dent/scratch|scratch", re.I), "drobne wgniecenia i rysy"),
    (re.compile(r"hail", re.I), "grad"),
    (re.compile(r"vandalism", re.I), "wandalizm"),
    (re.compile(r"theft", re.I), "ślady kradzieży"),
    (re.compile(r"front", re.I), "uszkodzony przód"),
    (re.compile(r"rear", re.I), "uszkodzony tył"),
    (re.compile(r"side", re.I), "uszkodzony bok"),
    (re.compile(r"undercarriage", re.I), "uszkodzone podwozie"),
    (re.compile(r"rollover|all over", re.I), "dachowanie"),
    (re.compile(r"mechanical|engine|transmission", re.I), "usterka mechaniczna"),
    (re.compile(r"water|flood", re.I), "auto zalane"),
    (re.compile(r"burn|fire", re.I), "ślady pożaru"),
    (re.compile(r"suspension", re.I), "uszkodzone zawieszenie"),
    (re.compile(r"biohazard", re.I), "skażenie wnętrza"),
)

_TITLE_PL: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"parts", re.I), "dokumenty tylko na części"),
    (re.compile(r"rebuilt", re.I), "auto po naprawie, dopuszczone do ruchu w USA"),
    (re.compile(r"salvage", re.I), "dokumenty auta powypadkowego"),
    (re.compile(r"clean", re.I), "dokumenty bez wpisu o szkodzie"),
)


# ══════════════════════════════════════════════════════════════════════ fakty


@dataclass(frozen=True)
class OfferCar:
    """Jedno auto w ofercie — komplet danych już policzonych i przetłumaczonych.

    Wszystko, co trafia do klienta, jest tutaj. Renderer nie liczy, model nie liczy.
    """

    lot: CarLot
    analysis: Optional[Any]          # AIAnalysis, gdy lot przeszedł przez analyze_lots
    costs: dict[str, float]          # pełny wynik calculate_lot_import_costs
    landed_pln: float                # sprowadzenie bez prowizji
    fee_pln: float                   # prowizja brokera (brutto)
    client_price_pln: float          # to, co klient realnie zapłaci
    excise_rate: float
    settlement: Settlement
    fee_tier: FeeTier
    report_url: Optional[str] = None
    why: Optional[str] = None        # jedno zdanie od modelu, może zostać puste
    over_budget: bool = False        # cena pod klucz wyższa niż budżet klienta

    @property
    def name(self) -> str:
        parts = [str(self.lot.year or ""), self.lot.make or "", self.lot.model or ""]
        return " ".join(part for part in parts if part).strip() or "Auto z aukcji"

    @property
    def price_label(self) -> str:
        return _price_label(self.client_price_pln)

    @property
    def mileage_label(self) -> str:
        return _mileage_label(self.lot.odometer_mi)

    @property
    def damage_label(self) -> str:
        return _damage_pl(self.lot)

    @property
    def title_label(self) -> Optional[str]:
        return _title_pl(self.lot.title_type)

    @property
    def photo(self) -> Optional[str]:
        return self.lot.images[0] if self.lot.images else None


@dataclass(frozen=True)
class Offer:
    """Wynik pracy agenta: dwa dokumenty i ślad tego, jak powstały."""

    client_html: str
    broker_html: str
    cars: list[OfferCar]
    prose_source: Literal["llm", "deterministic"]
    warnings: list[str] = field(default_factory=list)

    @property
    def has_offers(self) -> bool:
        return bool(self.cars)


# ─────────────────────────────────────────────────────────────────── formatowanie


def _round_up(value: float, step: int = PRICE_ROUNDING_PLN) -> int:
    return int(math.ceil(value / step) * step)


def _pln(value: float) -> str:
    """Złotówki ze spacją jako separatorem tysięcy (twarda spacja, żeby nie łamać linii)."""
    return f"{round(value):,.0f}".replace(",", " ") + " zł"


def _usd(value: Optional[float]) -> str:
    if not value:
        return "brak danych"
    return "$" + f"{round(value):,.0f}".replace(",", " ")


def _price_label(value: float) -> str:
    """Cena dla klienta — zaokrąglona w górę i opisana jako szacunek."""
    return "ok. " + _pln(_round_up(value))


def _mileage_label(odometer_mi: Optional[int]) -> str:
    """Klient liczy w kilometrach; mile zostawiamy w nawiasie, bo są w dokumentach."""
    if not odometer_mi:
        return "przebieg do potwierdzenia"
    km = round(odometer_mi * 1.60934 / 1000)
    return f"{km} tys. km ({odometer_mi / 1000:.0f} tys. mil)"


def _damage_pl(lot: CarLot) -> str:
    """Uszkodzenia po polsku, spokojnie i wprost. Nieznany opis = 'do potwierdzenia'."""
    labels: list[str] = []
    for raw in (lot.damage_primary, lot.damage_secondary):
        if not raw:
            continue
        for pattern, label in _DAMAGE_PL:
            if pattern.search(raw):
                if label not in labels:
                    labels.append(label)
                break
    if not labels:
        return "zakres uszkodzeń do potwierdzenia"
    return ", ".join(labels)


def _title_pl(title_type: Optional[str]) -> Optional[str]:
    if not title_type:
        return None
    for pattern, label in _TITLE_PL:
        if pattern.search(title_type):
            return label
    return None


def _car_headline(lot: CarLot) -> str:
    parts = [str(lot.year or ""), lot.make or "", lot.model or ""]
    return " ".join(part for part in parts if part).strip() or "Auto z aukcji"


# ─────────────────────────────────────────────────────────────────────── akcyza


def _engine_liters(lot: CarLot) -> Optional[float]:
    return engine_liters_from_trim(lot.trim, lot.model)


def _excise_rate(lot: CarLot, criteria: Optional[ClientCriteria]) -> float:
    """Stawka akcyzy dla tego auta — reguła wspólna z raportami per lot."""
    electric = bool(criteria and (criteria.fuel_type or "").lower() == "electric")
    return excise_rate_for(_engine_liters(lot), electric=electric)


# ─────────────────────────────────────────────────────────────── budowa pozycji


def _unwrap(item: Any) -> tuple[Optional[CarLot], Optional[Any]]:
    """Przyjmujemy AnalyzedLot (pipeline) albo goły CarLot (dashboard, testy)."""
    if isinstance(item, AnalyzedLot):
        return item.lot, item.analysis
    if isinstance(item, CarLot):
        return item, None
    lot = getattr(item, "lot", None)
    if isinstance(lot, CarLot):
        return lot, getattr(item, "analysis", None)
    return None, None


def _fee_pln(costs: dict[str, float], tier: FeeTier) -> float:
    return float(costs[BROKER_FEE_KEY[tier]])


# Etykieta importowana, nie przepisana: kopia rozjechałaby się po cichu przy zmianie
# w scoringu, a rozpoznanie "ponad budżet" po prostu przestałoby działać — bez błędu,
# za to z ofertą twierdzącą, że auto mieści się w kwocie klienta.
OVER_BUDGET_LABEL = OVER_BUDGET


def is_over_budget(item: Any) -> bool:
    """Czy ten lot przekracza budżet klienta — wg werdyktu ze scoringu.

    Czytamy z dwóch miejsc, bo w zależności od ścieżki dostajemy albo sam lot,
    albo AnalyzedLot: unified_score jedzie w raw_data lota, a rekomendacja
    w analizie. Wystarczy jedno.
    """
    lot, analysis = _unwrap(item)
    if analysis is not None and getattr(analysis, "recommendation", "") == OVER_BUDGET_LABEL:
        return True
    unified = ((lot.raw_data if lot else None) or {}).get("unified_score")
    return bool(isinstance(unified, dict) and unified.get("over_budget"))


def build_car(
    item: Any,
    *,
    settlement: Settlement = "private",
    fee_tier: FeeTier = DEFAULT_FEE_TIER,
    criteria: Optional[ClientCriteria] = None,
    report_url: Optional[str] = None,
) -> Optional[OfferCar]:
    """Pozycja oferty albo None, gdy lota nie da się wycenić.

    Bez ceny aukcyjnej nie ma ceny pod klucz, a auto bez ceny w ofercie to zaproszenie
    do rozmowy o tym, czego nie wiemy — lepiej je pominąć.
    """
    lot, analysis = _unwrap(item)
    if lot is None:
        return None

    excise = _excise_rate(lot, criteria)
    costs = calculate_lot_import_costs(lot, excise_rate=excise)
    if not costs:
        return None

    landed = float(costs[SETTLEMENT_TOTAL_KEY[settlement]])
    return OfferCar(
        lot=lot,
        analysis=analysis,
        costs=costs,
        landed_pln=landed,
        fee_pln=_fee_pln(costs, fee_tier),
        # Jedna definicja ceny końcowej dla całego systemu — patrz import_calculator.
        client_price_pln=client_price_pln(costs, settlement=settlement, fee_tier=fee_tier),
        excise_rate=excise,
        settlement=settlement,
        fee_tier=fee_tier,
        report_url=report_url,
        over_budget=is_over_budget(item),
    )


# ══════════════════════════════════════════════════════════════ proza od modelu


def _load_agent_prompt() -> str:
    if not AGENT_PROMPT_PATH.exists():
        raise FileNotFoundError(f"Brak pliku agenta: {AGENT_PROMPT_PATH}")
    return AGENT_PROMPT_PATH.read_text(encoding="utf-8")


def _facts_for_model(cars: list[OfferCar], client_name: Optional[str], query: str) -> str:
    """Minimalny obraz świata dla modelu.

    Świadomie NIE podajemy tu ocen, cen w USD ani identyfikatorów lotów — model nie
    powinien mieć czym się pomylić ani co przepisać do treści dla klienta.
    """
    payload = {
        "klient": client_name or None,
        "czego_szukal": query or None,
        "auta": [
            {
                "id": car.lot.lot_id,
                "auto": car.name,
                "przebieg": car.mileage_label,
                "stan": car.damage_label,
                "dokumenty": car.title_label,
                "cena_pod_klucz": car.price_label,
                "ponad_budzet": car.over_budget,
                "lokalizacja": car.lot.location_state,
                "uwagi_analizy": (car.analysis.red_flags or [])[:3] if car.analysis else [],
            }
            for car in cars
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=1)


_PROSE_TASK = """Napisz prozę do oferty. Zwróć WYŁĄCZNIE JSON, bez markdown:

{{
  "intro": "jedno zdanie otwarcia, max 180 znaków",
  "cars": [{{"id": "<id auta>", "why": "jedno zdanie, dlaczego akurat to auto, max 130 znaków"}}],
  "closing": "jedno zdanie zamykające, ZAKOŃCZ PYTANIEM, max 150 znaków",
  "broker_note": "3-5 zdań dla brokera: na co uważać przy tych autach, max 600 znaków"
}}

TWARDE ZASADY (złamanie = fragment leci do kosza i zostaje wersja bez niego):
- ŻADNYCH CYFR w polach intro, why, closing. Wszystkie liczby wstawia system.
- Żadnego żargonu: bez "salvage", "rebuilt", "lot", "score", bez nazw giełd.
- Bez wykrzykników, bez emoji, bez wielkich liter dla podkreślenia.
- Bez obietnic gwarancji, naprawy i zysku — jesteśmy pośrednikiem, nie komisem.
- Uszkodzenia nazywaj spokojnie i wprost, nie strasz i nie ukrywaj.
- Zdania krótkie, do 15 słów. Ton doradcy, nie sprzedawcy.

DANE:
{facts}"""


# Zdania, których nie wolno napisać o aucie droższym niż budżet klienta. Nie mają
# cyfr ani żargonu, więc przechodziły przez pozostałe bramki bez zająknięcia.
BUDGET_CLAIM_FRAGMENTS = (
    "budżet",
    "budzet",
    "mieści się w",
    "miesci sie w",
    "w kwocie",
    "na kieszeń",
)


def _clean_prose(
    text: Any,
    limit: int,
    *,
    allow_digits: bool = False,
    banned_extra: tuple[str, ...] = (),
) -> Optional[str]:
    """Zdanie od modelu albo None, gdy łamie zasady.

    Odrzucamy zamiast poprawiać: fragment z cyfrą to liczba, której nikt nie policzył,
    a zdanie z zakazanym zwrotem lepiej wyciąć niż przepisać w locie.
    """
    if not isinstance(text, str):
        return None
    cleaned = _WS.sub(" ", _TAGS.sub(" ", text)).strip().strip('"')
    if not cleaned or len(cleaned) > limit * 2:
        return None
    if not allow_digits and _DIGIT.search(cleaned):
        return None
    if _EMOJI.search(cleaned) or "!" in cleaned:
        return None
    lowered = cleaned.lower()
    if any(bad in lowered for bad in BANNED_FRAGMENTS):
        return None
    if any(bad in lowered for bad in JARGON_FRAGMENTS):
        return None
    if any(bad in lowered for bad in banned_extra):
        return None
    if len(cleaned) > limit:
        cut = cleaned[:limit].rsplit(" ", 1)[0]
        cleaned = cut.rstrip(" ,;–-") + "."
    return cleaned


def _strip_greeting(text: str) -> str:
    """Zdanie bez powitania, z wielkiej litery. Puste, gdy zostało samo powitanie."""
    for _ in range(2):  # "Dzień dobry, Panie Marku, ..." to dwa powitania pod rząd
        match = _GREETING.match(text)
        if not match:
            break
        rest = text[match.end():]
        # Imię w wołaczu ucinamy TYLKO po "Panie"/"Pani" — po "Dzień dobry" następne
        # słowo jest już treścią i skasowanie go zjadałoby początek zdania.
        if match.group(1).lower() in ("panie", "pani"):
            rest = _VOCATIVE.sub("", rest, count=1)
        text = rest.strip()
    return text[:1].upper() + text[1:] if text else ""


def _parse_json_loose(raw: str) -> dict:
    """JSON z odpowiedzi modelu, nawet gdy owinie go w ```json albo doda komentarz."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.split("\n", 1)[1] if text.lower().startswith("json") else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("brak obiektu JSON w odpowiedzi")
    return json.loads(text[start:end + 1])


def _validated_prose(raw: dict, cars: list[OfferCar]) -> tuple[dict, list[str]]:
    """Proza przepuszczona przez walidację; odrzucone pola wracają jako ostrzeżenia."""
    warnings: list[str] = []
    result: dict[str, Any] = {"intro": None, "closing": None, "broker_note": None, "why": {}}
    intro_banned = BUDGET_CLAIM_FRAGMENTS if any(car.over_budget for car in cars) else ()

    for key, limit in (("intro", 180), ("closing", 150)):
        candidate = raw.get(key)
        if key == "intro" and isinstance(candidate, str):
            candidate = _strip_greeting(candidate)
        value = _clean_prose(candidate, limit, banned_extra=intro_banned)
        if value is None and raw.get(key):
            warnings.append(f"odrzucono pole '{key}' (cyfry, żargon lub zakazany zwrot)")
        result[key] = value

    # Notatka brokerska trafia tylko do nas, więc cyfry są w niej dozwolone.
    note = _clean_prose(raw.get("broker_note"), 600, allow_digits=True)
    result["broker_note"] = note

    by_id = {car.lot.lot_id: car for car in cars}
    for entry in raw.get("cars") or []:
        if not isinstance(entry, dict):
            continue
        lot_id = str(entry.get("id") or "")
        if lot_id not in by_id:
            continue
        banned_extra = BUDGET_CLAIM_FRAGMENTS if by_id[lot_id].over_budget else ()
        why = _clean_prose(entry.get("why"), 130, banned_extra=banned_extra)
        if why is None and entry.get("why"):
            warnings.append(f"odrzucono opis auta {lot_id}")
        if why:
            result["why"][lot_id] = why

    return result, warnings


def _fallback_prose(cars: list[OfferCar], client_name: Optional[str], budget_pln: Optional[float]) -> dict:
    """Oferta bez modelu — krótsza, ale poprawna i wysyłalna.

    Treść celowo zbieżna z report/whatsapp.py: klient może dostać oba kanały i nie
    powinien zobaczyć dwóch różnych wersji tej samej propozycji.
    """
    count = len(cars)
    if not count:
        return {
            "intro": "Na ten moment nie mam auta, które mógłbym uczciwie polecić.",
            "closing": "Szukam dalej — poszerzyć kryteria czy poczekać na kolejne aukcje?",
            "broker_note": None,
            "why": {},
        }
    # Liczebnik słownie — ten sam zakaz cyfr, który nakładamy na model, obowiązuje
    # naszą własną wersję. "Mam 1 auto" czyta się jak wiadomość z systemu.
    count_word = {1: "jedno", 2: "dwa", 3: "trzy", 4: "cztery"}.get(count, str(count))
    noun = "auto" if count == 1 else ("auta" if count < 5 else "aut")
    # Budżet wspominamy tylko wtedy, gdy cokolwiek się w nim mieści. "Mam 4 auta pod
    # budżet 60 tys." przy cenach od 62 tys. czyta się jak niedosłuchanie klienta.
    # all(), nie any(): przy jednym aucie w budżecie i trzech ponad, "mam cztery auta
    # pod budżet" jest po prostu nieprawdą.
    fits_budget = budget_pln and all(car.client_price_pln <= budget_pln for car in cars)
    budget_note = f" pod budżet {round(budget_pln / 1000)} tys. zł" if fits_budget else ""
    return {
        "intro": f"Mam {count_word} {noun}{budget_note} — poniżej ceny pod klucz w Polsce.",
        "closing": "Podesłać pełną kalkulację dla któregoś z nich?",
        "broker_note": None,
        "why": {},
    }


# ───────────────────────────────────────────────────────────── dostawcy modelu

# Model bierzemy z konfiguracji, nie z literału w kodzie. Poprzedni default
# ("claude-sonnet-4-6-thinking") to alias proxy oneprovider.dev, a nie identyfikator
# z API Anthropica — wpisany na sztywno rozjeżdżał się z ANTHROPIC_MODEL z .env.
OFFER_MODEL = (
    os.getenv("ANTHROPIC_OFFER_MODEL")
    or os.getenv("ANTHROPIC_MODEL")
    or "claude-sonnet-4-5-20250929"
)

# Identyfikatory publicznego API Anthropica mają postać "claude-<rodzina>-<wersja>[-data]".
# Aliasy proxy (np. "claude-sonnet-4-6-thinking") wyglądają podobnie, ale na oficjalnym
# endpointcie zwracają 404 — a że to ścieżka ratunkowa, błąd wychodził dopiero wtedy,
# gdy pierwszy provider już padł.
_PROXY_ONLY_MODEL = re.compile(r"-thinking$|-4-6", re.IGNORECASE)
_MAX_TOKENS = 1200


def _check_anthropic_config() -> None:
    """Sprzeczną konfigurację zgłaszamy od razu, zamiast czekać na 404 z API.

    Klucz i model w .env należą do proxy `api.oneprovider.dev`. Przy pustym
    ANTHROPIC_BASE_URL SDK strzela na oficjalne api.anthropic.com, gdzie ani klucz,
    ani alias modelu nie działają — patrz AUDYT_SESJA_2026-07-19.md, punkt 6.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("Brak ANTHROPIC_API_KEY")
    if not os.getenv("ANTHROPIC_BASE_URL") and _PROXY_ONLY_MODEL.search(OFFER_MODEL):
        raise RuntimeError(
            f"Model '{OFFER_MODEL}' to alias proxy, a ANTHROPIC_BASE_URL jest puste — "
            "wywołanie poszłoby na oficjalne API i zwróciło 404. Ustaw ANTHROPIC_BASE_URL "
            "na proxy albo ANTHROPIC_MODEL na identyfikator z API Anthropica."
        )


def _call_anthropic_text(system: str, user_prompt: str) -> str:
    from anthropic import Anthropic

    _check_anthropic_config()
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=OFFER_MODEL,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


def _call_gemini_text(system: str, user_prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Brak GEMINI_API_KEY")
    model = os.getenv("GEMINI_OFFER_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    timeout = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "120"))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": _MAX_TOKENS,
            "temperature": 0.7,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": int(os.getenv("GEMINI_THINKING_BUDGET", "0"))},
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini brak candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts if part.get("text"))
    if not text:
        raise RuntimeError(f"Gemini empty (finish={candidates[0].get('finishReason')})")
    return text


_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _resolve_kiro_model() -> str:
    try:
        from api.settings_db import get_ai_model_override

        override = get_ai_model_override("kiro")
        if override:
            return override
    except Exception:
        pass
    return os.getenv("KIRO_MODEL", "claude-haiku-4.5")


def _call_kiro_text(system: str, user_prompt: str) -> str:
    api_key = os.getenv("KIRO_API_KEY")
    if not api_key:
        raise RuntimeError("Brak KIRO_API_KEY")
    cli_path = os.getenv("KIRO_CLI_PATH", os.path.expanduser("~/.local/bin/kiro-cli"))
    timeout = int(os.getenv("KIRO_TIMEOUT_SECONDS", "180"))
    try:
        result = subprocess.run(
            [cli_path, "chat", "--no-interactive", "--trust-tools=", "-w", "never",
             "--effort", os.getenv("KIRO_EFFORT", "low"),
             "--model", _resolve_kiro_model(), f"{system}\n\n{user_prompt}"],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "KIRO_API_KEY": api_key},
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"kiro-cli nie znaleziony ({cli_path}): {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Kiro CLI timeout po {timeout}s") from exc
    if result.returncode != 0:
        raise RuntimeError(f"Kiro CLI exit {result.returncode}: {result.stderr[:300]}")
    text = _ANSI.sub("", result.stdout).strip()
    if not text:
        raise RuntimeError(f"Kiro CLI pusta odpowiedź (stderr: {result.stderr[:300]})")
    return text


def _call_claude_code_text(system: str, user_prompt: str) -> str:
    """Claude Code headless — uwierzytelnienie sesją zalogowanego użytkownika, bez klucza.

    Prompt agenta idzie osobno jako systemowy, bo jest stały co do bajtu: dzięki temu
    trafia w cache promptów i kolejne oferty kosztują ułamek pierwszej (ai/claude_code.py).
    Oferta to jedyny tekst, który czyta klient, więc nie schodzimy tu na niski effort.
    """
    return claude_code.call(
        system, user_prompt,
        model_env="CLAUDE_CODE_OFFER_MODEL",
        label="oferta",
    )


_CALLERS = {
    "gemini": _call_gemini_text,
    "kiro": _call_kiro_text,
    "anthropic": _call_anthropic_text,
    "claude-code": _call_claude_code_text,
}


def _resolve_offer_provider() -> str:
    """Nadpisanie z dashboardu (settings_db) ma pierwszeństwo przed .env."""
    try:
        from api.settings_db import get_ai_provider_override

        override = get_ai_provider_override("offer_agent_ai_provider")
        if override:
            return override.lower()
    except Exception:
        pass
    return (os.getenv("OFFER_AGENT_AI_PROVIDER", "gemini") or "gemini").lower()


def _call_llm(system: str, user_prompt: str) -> str:
    provider = _resolve_offer_provider()
    caller = _CALLERS.get(provider, _call_gemini_text)
    try:
        return caller(system, user_prompt)
    except Exception as exc:
        print(f"[OfferAgent] {provider} nieudany ({type(exc).__name__}: {exc})")
        fallback = os.getenv("LLM_REPORTS_FALLBACK_ANTHROPIC", "true").lower() == "true"
        if provider != "anthropic" and fallback and os.getenv("ANTHROPIC_API_KEY"):
            print("[OfferAgent] Fallback → Anthropic")
            return _call_anthropic_text(system, user_prompt)
        raise


# ══════════════════════════════════════════════════════════════════════ render

_E = html_lib.escape


def _render_client_email(
    cars: list[OfferCar],
    prose: dict,
    *,
    client_name: Optional[str],
    contact_line: str,
) -> str:
    """Mail dla klienta. Inline CSS i tabele — to jedyne, co przeżywa Gmaila i Outlooka."""
    greeting = "Dzień dobry" if not client_name else f"Dzień dobry, {_E(client_name.strip().split()[0])}"
    intro = prose.get("intro") or "Poniżej auta, które wybrałem pod Pana kryteria."
    closing = prose.get("closing") or "Chce Pan, żebym podesłał pełną kalkulację?"

    # Bez aut zostaje sama rama listu. Pusta lista z nagłówkiem "w cenie zawiera się..."
    # brzmiałaby jak oferta, której nie ma.
    price_note = "" if not cars else """
      <div style="background:#f8fafc;border:1px solid #e6e8ee;border-radius:10px;padding:14px;
                  color:#344054;font-size:13px;line-height:1.6;">
        W podanej cenie: zakup auta, opłaty aukcyjne, transport do Polski, odprawa celna,
        akcyza i moja prowizja.<br>
        Ceny są wyliczone dla dzisiejszej stawki na aukcji — licytacja może pójść wyżej
        i wtedy podaję nową kwotę przed zakupem.
      </div>"""

    blocks: list[str] = []
    for car in cars:
        photo = ""
        if car.photo:
            photo = (
                f'<img src="{_E(car.photo)}" alt="{_E(car.name)}" width="560" '
                'style="display:block;width:100%;max-width:560px;height:auto;'
                'border-radius:10px;margin:0 0 12px 0;border:1px solid #e6e8ee;">'
            )
        facts = [car.mileage_label, car.damage_label]
        if car.title_label:
            facts.append(car.title_label)
        why = f'<p style="margin:10px 0 0 0;color:#344054;font-size:15px;line-height:1.5;">{_E(car.why)}</p>' if car.why else ""
        link = ""
        if car.report_url:
            link = (
                f'<p style="margin:12px 0 0 0;"><a href="{_E(car.report_url)}" '
                'style="color:#163b66;font-weight:700;text-decoration:underline;font-size:14px;">'
                'Szczegóły tego auta</a></p>'
            )
        blocks.append(f"""
      <tr><td style="padding:0 28px 20px 28px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
               style="border:1px solid #d9e2ec;border-radius:12px;background:#ffffff;">
          <tr><td style="padding:18px 20px;">
            {photo}
            <h2 style="font-size:20px;line-height:1.25;margin:0 0 6px 0;color:#111827;">{_E(car.name)}</h2>
            <div style="font-size:14px;color:#667085;line-height:1.6;">{_E(" · ".join(facts))}</div>
            <div style="margin-top:12px;font-size:20px;font-weight:800;color:#163b66;">{_E(car.price_label)}</div>
            <div style="font-size:12px;color:#667085;margin-top:2px;">cena pod klucz w Polsce{
                " — powyżej podanego budżetu" if car.over_budget else ""}</div>
            {why}
            {link}
          </td></tr>
        </table>
      </td></tr>""")

    return f"""<!doctype html>
<html lang="pl">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Auta z USA — propozycje</title></head>
<body style="margin:0;padding:0;background:#eef2f7;color:#111827;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eef2f7;padding:24px 0;">
<tr><td align="center">
  <table role="presentation" width="640" cellspacing="0" cellpadding="0"
         style="width:640px;max-width:100%;background:#ffffff;border-radius:14px;overflow:hidden;">
    <tr><td style="background:#163b66;color:#ffffff;padding:26px 28px;">
      <p style="font-size:17px;line-height:1.5;margin:0 0 8px 0;">{greeting},</p>
      <p style="font-size:15px;line-height:1.6;margin:0;color:#dbeafe;">{_E(intro)}</p>
    </td></tr>
{"".join(blocks)}
    <tr><td style="padding:4px 28px 24px 28px;">{price_note}
      <p style="margin:18px 0 0 0;font-size:15px;line-height:1.6;color:#111827;">{_E(closing)}</p>
      <p style="margin:14px 0 0 0;font-size:14px;line-height:1.6;color:#667085;">{_E(contact_line)}</p>
    </td></tr>
  </table>
</td></tr></table>
</body></html>
"""


def _verify_checklist(car: OfferCar) -> list[str]:
    """Czego brakuje, żeby ta pozycja była w pełni sprawdzona. Liczone, nie zgadywane."""
    todo: list[str] = []
    if not car.lot.full_vin:
        todo.append("brak pełnego VIN — bez niego nie ma historii pojazdu")
    if car.lot.keys is None:
        todo.append("nie wiadomo, czy są kluczyki")
    elif car.lot.keys is False:
        todo.append("brak kluczyków")
    if car.lot.airbags_deployed:
        todo.append("poduszki zadziałały — koszt naprawy do doliczenia")
    if len(car.lot.images) < 5:
        todo.append(f"tylko {len(car.lot.images)} zdjęć — za mało na ocenę stanu")
    if _engine_liters(car.lot) is None:
        todo.append("pojemność silnika nieznana — akcyzę policzono po wyższej stawce")
    if not car.lot.auction_date:
        todo.append("brak daty zakończenia aukcji")
    if car.analysis and car.analysis.red_flags:
        todo.extend(car.analysis.red_flags)
    return todo


def _render_broker_brief(
    cars: list[OfferCar],
    extra_cars: list[OfferCar],
    prose: dict,
    *,
    client_name: Optional[str],
    search_query: str,
    warnings: list[str],
    prose_source: str,
) -> str:
    """Brief dla brokera — wszystko, czego nie ma w mailu, w tym pełna kalkulacja."""

    def row(car: OfferCar, client_facing: bool) -> str:
        costs = car.costs
        why = car.why or "—"
        checklist = "".join(f"<li>{_E(item)}</li>" for item in _verify_checklist(car)) or "<li>—</li>"
        score = f"{car.analysis.score:.1f}/10 {car.analysis.recommendation}" if car.analysis else "—"
        return f"""
    <tr><td style="padding:16px;border:1px solid #d9e2ec;border-radius:10px;background:#fff;">
      <div style="font-size:17px;font-weight:700;color:#111827;">{_E(car.name)}
        <span style="font-size:12px;color:#667085;font-weight:400;">
          · {_E((car.lot.source or "").upper())} {_E(car.lot.lot_id)} · {_E(car.lot.location_city or "")} {_E(car.lot.location_state or "")}
          · ocena {_E(score)} · {"W MAILU" if client_facing else "poza mailem"}
        </span>
      </div>
      <table cellspacing="0" cellpadding="4" style="font-size:13px;color:#344054;margin-top:8px;border-collapse:collapse;">
        <tr><td>Stawka aukcyjna</td><td align="right"><b>{_E(_usd(car.lot.current_bid_usd or car.lot.buy_now_price_usd))}</b></td>
            <td style="padding-left:18px;">Opłata aukcyjna (8%)</td><td align="right">{_E(_usd(costs.get("auction_fee_usd")))}</td></tr>
        <tr><td>Transport z placu</td><td align="right">{_E(_usd(costs.get("towing_usd")))}</td>
            <td style="padding-left:18px;">Załadunek + fracht</td><td align="right">{_E(_usd((costs.get("loading_usd") or 0) + (costs.get("freight_usd") or 0)))}</td></tr>
        <tr><td>Akcyza (stawka)</td><td align="right">{car.excise_rate * 100:.1f}%</td>
            <td style="padding-left:18px;">Silnik (heurystyka)</td><td align="right">{_E(str(_engine_liters(car.lot) or "nieznany"))}</td></tr>
        <tr><td>Sprowadzenie ({_E(car.settlement)})</td><td align="right"><b>{_E(_pln(car.landed_pln))}</b></td>
            <td style="padding-left:18px;">Prowizja ({_E(car.fee_tier)})</td><td align="right"><b>{_E(_pln(car.fee_pln))}</b></td></tr>
        <tr style="background:#f0f6ff;"><td><b>Cena w ofercie</b></td><td align="right"><b>{_E(car.price_label)}</b></td>
            <td style="padding-left:18px;">Drugi wariant rozliczenia</td>
            <td align="right">{_E(_pln((costs["company_gross_pln"] if car.settlement == "private" else costs["private_total_pln"]) + car.fee_pln))}</td></tr>
      </table>
      <div style="font-size:13px;color:#344054;margin-top:10px;">
        <b>Zdanie w mailu:</b> {_E(why)}<br>
        <b>Uszkodzenia (oryginał):</b> {_E(car.lot.damage_primary or "—")} / {_E(car.lot.damage_secondary or "—")}
        &nbsp;·&nbsp; <b>Tytuł:</b> {_E(car.lot.title_type or "—")}
        &nbsp;·&nbsp; <b>VIN:</b> {_E(car.lot.full_vin or car.lot.vin or "—")}
        &nbsp;·&nbsp; <b>Koniec aukcji:</b> {_E(car.lot.auction_date or "—")}
      </div>
      <div style="font-size:13px;color:#7a4f00;background:#fff8e6;border:1px solid #f4d27a;
                  border-radius:8px;padding:10px 12px;margin-top:10px;">
        <b>Do potwierdzenia przed licytacją:</b><ul style="margin:6px 0 0 18px;padding:0;">{checklist}</ul>
      </div>
      <div style="margin-top:10px;"><a href="{_E(car.lot.url)}" style="font-size:13px;color:#163b66;">Otwórz aukcję</a></div>
    </td></tr>
    <tr><td style="height:12px;"></td></tr>"""

    note = prose.get("broker_note")
    warn_html = ""
    if warnings:
        warn_html = (
            '<div style="background:#fff1f0;border:1px solid #f5b5b0;border-radius:8px;padding:12px;'
            'color:#7a1c14;font-size:13px;margin-bottom:16px;"><b>Walidacja treści:</b><ul style="margin:6px 0 0 18px;">'
            + "".join(f"<li>{_E(w)}</li>" for w in warnings)
            + "</ul></div>"
        )

    return f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><title>Brief ofertowy</title></head>
<body style="margin:0;padding:24px;background:#eef2f7;font-family:Arial,Helvetica,sans-serif;color:#111827;">
<div style="max-width:900px;margin:0 auto;">
  <h1 style="font-size:22px;margin:0 0 4px 0;">Brief ofertowy — {_E(client_name or "klient")}</h1>
  <p style="font-size:13px;color:#667085;margin:0 0 16px 0;">
    Zapytanie: {_E(search_query or "brak opisu")} · wygenerowano {datetime.now().strftime("%d.%m.%Y %H:%M")}
    · proza: {_E(prose_source)} · w mailu {len(cars)} z {len(cars) + len(extra_cars)} aut
  </p>
  {warn_html}
  <div style="background:#fff;border:1px solid #d9e2ec;border-radius:10px;padding:14px;margin-bottom:16px;font-size:13px;color:#344054;">
    <b>Notatka:</b> {_E(note) if note else "—"}
  </div>
  <table cellspacing="0" cellpadding="0" width="100%">
    {"".join(row(car, True) for car in cars)}
    {"".join(row(car, False) for car in extra_cars)}
  </table>
  <p style="font-size:12px;color:#667085;margin-top:18px;line-height:1.6;">
    Ceny liczone przez pricing/import_calculator.py przy kursie
    {_E(str(cars[0].costs["usd_rate"] if cars else "—"))} USD/PLN. Cena w ofercie zawiera prowizję,
    nie zawiera rejestracji w Polsce ani ewentualnej naprawy. Kwoty w mailu są zaokrąglone
    w górę do {PRICE_ROUNDING_PLN} zł.
  </p>
</div></body></html>
"""


# ═════════════════════════════════════════════════════════════════════════ API


def build_offer(
    items: Iterable[Any],
    *,
    client_name: Optional[str] = None,
    criteria: Optional[ClientCriteria] = None,
    search_query: str = "",
    settlement: Optional[Settlement] = None,
    fee_tier: FeeTier = DEFAULT_FEE_TIER,
    report_urls: Optional[dict[str, str]] = None,
    contact_line: str = "Odpowiedź na tego maila trafia prosto do mnie.",
    use_llm: bool = True,
    allow_over_budget: bool = False,
) -> Offer:
    """Buduje ofertę: mail dla klienta + brief dla brokera.

    Nie rzuca wyjątkiem przy awarii modelu — oferta bez zdań "dlaczego" jest lepsza niż
    brak oferty po pełnym cyklu scrape'u i analizy.

    Auta ponad budżet klienta nie wchodzą do maila same z siebie. Od kiedy scoring
    przestał je zerować, mają normalne wysokie oceny i stoją wysoko w rankingu — bez
    tego filtra wypełniałyby wolne miejsca w czwórce dla klienta. Wchodzą tylko jawną
    decyzją (allow_over_budget), zawsze na końcu listy i zawsze oznaczone w treści.
    Brief brokera widzi je zawsze.
    """
    resolved_settlement: Settlement = settlement or (
        criteria.settlement if criteria and criteria.settlement in ("private", "company") else "private"
    )  # type: ignore[assignment]
    urls = report_urls or {}

    cars: list[OfferCar] = []
    for item in items:
        lot, _ = _unwrap(item)
        car = build_car(
            item,
            settlement=resolved_settlement,
            fee_tier=fee_tier,
            criteria=criteria,
            report_url=urls.get(lot.lot_id) if lot else None,
        )
        if car:
            cars.append(car)

    affordable = [car for car in cars if not car.over_budget]
    over = [car for car in cars if car.over_budget]
    if allow_over_budget:
        client_cars = (affordable + over)[:MAX_CLIENT_CARS]
    else:
        client_cars = affordable[:MAX_CLIENT_CARS]
    chosen = {id(car) for car in client_cars}
    extra_cars = [car for car in cars if id(car) not in chosen]
    budget_pln = criteria.budget_pln() if criteria else None

    prose = _fallback_prose(client_cars, client_name, budget_pln)
    prose_source: Literal["llm", "deterministic"] = "deterministic"
    warnings: list[str] = []
    if not client_cars:
        warnings.append("żadnego lota nie dało się wycenić — tego maila nie ma po co wysyłać")
    if over and not allow_over_budget:
        warnings.append(
            f"{len(over)} aut pominięto — cena pod klucz ponad budżet klienta "
            "(są w sekcji poniżej, do świadomego dobrania)"
        )
    if any(car.over_budget for car in client_cars):
        warnings.append("UWAGA: w mailu jest auto ponad budżet klienta — opisane jako droższe")

    if client_cars and use_llm:
        try:
            raw = _call_llm(
                _load_agent_prompt(),
                _PROSE_TASK.format(facts=_facts_for_model(client_cars, client_name, search_query)),
            )
            validated, warnings = _validated_prose(_parse_json_loose(raw), client_cars)
            # Puste pole zostaje na wersji deterministycznej — nie zostawiamy dziury.
            prose = {
                "intro": validated["intro"] or prose["intro"],
                "closing": validated["closing"] or prose["closing"],
                "broker_note": validated["broker_note"],
                "why": validated["why"],
            }
            prose_source = "llm"
        except Exception as exc:
            warnings.append(f"model nieosiągalny ({type(exc).__name__}: {exc}) — proza deterministyczna")
            print(f"[OfferAgent] proza deterministyczna: {exc}")

    why_by_id = prose.get("why") or {}
    client_cars = [replace(car, why=why_by_id.get(car.lot.lot_id)) for car in client_cars]

    client_html = _render_client_email(
        client_cars, prose, client_name=client_name, contact_line=contact_line
    )
    broker_html = _render_broker_brief(
        client_cars, extra_cars, prose,
        client_name=client_name, search_query=search_query,
        warnings=warnings, prose_source=prose_source,
    )

    leaked = _leaks(client_html)
    if leaked:
        # Ostatnia bramka: cokolwiek przeciekło do maila, broker musi to zobaczyć
        # PRZED zatwierdzeniem, a nie klient po wysyłce.
        warnings.append("UWAGA: w mailu wykryto zakazane sformułowania: " + ", ".join(leaked))
        broker_html = _render_broker_brief(
            client_cars, extra_cars, prose,
            client_name=client_name, search_query=search_query,
            warnings=warnings, prose_source=prose_source,
        )

    return Offer(
        client_html=client_html,
        broker_html=broker_html,
        cars=client_cars + extra_cars,
        prose_source=prose_source,
        warnings=warnings,
    )


def _leaks(client_html: str) -> list[str]:
    """Zakazane zwroty i żargon w gotowym mailu — również te spoza prozy modelu."""
    text = _WS.sub(" ", _TAGS.sub(" ", client_html)).lower()
    return [bad for bad in (*BANNED_FRAGMENTS, *JARGON_FRAGMENTS) if bad in text]


def generate_offers_with_agent(
    top_lots: list[AnalyzedLot],
    remaining_lots: list[AnalyzedLot],
    client_name: str = "Kliencie",
    search_query: str = "",
    *,
    criteria: Optional[ClientCriteria] = None,
) -> tuple[str, str]:
    """Zgodność z main_automation.py: (brief dla brokera, mail dla klienta).

    Kolejność zwracanych dokumentów jest jak w poprzedniej wersji ("pełna, skrócona"),
    ale znaczenie się zmieniło: pierwszy dokument to brief wewnętrzny, nie druga wersja
    oferty. Sprzedający dostaje go na Telegramie i to on zatwierdza wysyłkę.
    """
    # "Kliencie" to placeholder z parsera maila, nie imię — lepiej bez zwrotu po imieniu.
    name = None if client_name in ("", "Kliencie") else client_name
    offer = build_offer(
        [*top_lots, *remaining_lots],
        client_name=name,
        criteria=criteria,
        search_query=search_query,
    )
    # Liczba w mailu to nie min(wszystkie, 4): budżet mógł uciąć pozycje, a log ma
    # mówić, ile klient realnie dostanie.
    in_mail = sum(1 for car in offer.cars if not car.over_budget)
    print(
        f"[OfferAgent] {len(offer.cars)} aut, w mailu {min(in_mail, MAX_CLIENT_CARS)}, "
        f"proza: {offer.prose_source}, ostrzeżeń: {len(offer.warnings)}"
    )
    return offer.broker_html, offer.client_html
