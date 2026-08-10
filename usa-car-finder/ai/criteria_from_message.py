"""
Notatka albo wiadomość od klienta -> ClientCriteria.

Wejście bywa dwojakie i oba są ubogie: notatka brokera z rozmowy telefonicznej
("karoq kodiaq, vw tiguan") albo wiadomość, którą klient napisał na WhatsAppie.
Zadaniem tego modułu jest zamienić je na kryteria, które da się od razu puścić
w wyszukiwanie — z sensownymi wartościami domyślnymi tam, gdzie klient nic nie
powiedział, i z jawną listą tego, czego NIE potwierdził.

Ta lista jest ważniejsza, niż się wydaje: formularz ma pokazać brokerowi, co
zostało zgadnięte, żeby wiedział, o co dopytać przy oddzwonieniu.
"""
from dataclasses import dataclass, field
from typing import Any, Optional

from parser.models import ClientCriteria, SearchTarget

# Domyślne, gdy klient nic nie powiedział. Zaznaczone w formularzu, ale edytowalne.
DEFAULT_EXCLUDED_DAMAGE = ["Flood", "Fire"]
DEFAULT_SOURCES = ["copart", "iaai"]


@dataclass
class ParsedCriteria:
    criteria: ClientCriteria
    #: Pola, których klient NIE potwierdził — formularz ma je oznaczyć do dopytania.
    assumed: list[str] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)


def _first_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def criteria_from_parsed(parsed: dict, *, sources: Optional[list[str]] = None) -> Optional[ParsedCriteria]:
    """Buduje kryteria z odpowiedzi parsera wiadomości.

    Zwraca None, gdy w wiadomości nie było ani jednej marki — bez tego nie ma czego
    szukać, a zgadywanie marki z segmentu należy do agenta, nie do konwersji.
    """
    cars = [car for car in (parsed.get("cars") or []) if isinstance(car, dict) and car.get("make")]
    if not cars:
        return None

    primary, rest = cars[0], cars[1:]
    assumed: list[str] = []

    def note(field_name: str) -> None:
        if field_name not in assumed:
            assumed.append(field_name)

    budget_to = _first_number(parsed.get("budget_pln_to"))
    budget_from = _first_number(parsed.get("budget_pln_from"))
    if not budget_to and not budget_from:
        note("budżet")

    settlement = parsed.get("settlement")
    if settlement not in {"private", "company"}:
        # Forma zakupu przesuwa sufit o ~1400 USD przy 50 tys. zł — zgadywanie jej
        # jest kosztowne, więc zapisujemy domyślną i wołamy o potwierdzenie.
        settlement = "private"
        note("forma zakupu (osoba prywatna czy firma)")

    if parsed.get("risk") not in {"none", "light", "repairable"}:
        note("apetyt na ryzyko (czy dopuszcza naprawę)")

    if not primary.get("year_from") and not primary.get("year_to"):
        note("rocznik")
    if not primary.get("max_odometer_mi"):
        note("maksymalny przebieg")

    criteria = ClientCriteria(
        make=primary["make"],
        model=primary.get("model"),
        targets=[
            SearchTarget(make=car["make"], model=car.get("model"))
            for car in rest
        ],
        year_from=primary.get("year_from"),
        year_to=primary.get("year_to"),
        max_odometer_mi=primary.get("max_odometer_mi"),
        budget_usd=_first_number(primary.get("budget_usd")),
        budget_pln_from=budget_from,
        budget_pln_to=budget_to,
        settlement=settlement,
        segment=parsed.get("segment"),
        excluded_damage_types=primary.get("excluded_damage_types") or list(DEFAULT_EXCLUDED_DAMAGE),
        allowed_damage_types=primary.get("allowed_damage_types") or [],
        sources=sources or primary.get("sources") or list(DEFAULT_SOURCES),
    )

    return ParsedCriteria(
        criteria=criteria,
        assumed=assumed,
        summary=str(parsed.get("_summary") or ""),
        warnings=list(parsed.get("_warnings") or []),
    )
