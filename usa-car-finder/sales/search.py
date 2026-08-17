"""
Most między leadem a pipeline'em aukcyjnym — brakujące ogniwo agenta.

CO BYŁO NIE TAK

Agent zbierał lead, oceniał go, pisał wiadomości i pilnował etapów lejka — ale
nigdy nie uruchamiał wyszukiwania. Marka, model, rocznik i budżet leżały w bazie,
a broker i tak musiał przepisać je ręcznie do formularza na stronie głównej, puścić
scrape, a potem przekleić wybrane auta do endpointu ofertowego.

Etap `SZUKANIE` istniał w modelu i nic go nie wypełniało. To jest dokładnie ta luka,
przez którą „agent sprzedażowy" był notatnikiem z oceną, a nie agentem.

CO ROBI TEN MODUŁ

Zamienia leada na `ClientCriteria` i puszcza to samo wyszukiwanie, którego używa
panel — ta sama kolejka, ten sam scoring, te same artefakty. Wynik zapisuje przy
leadzie, żeby broker zobaczył kandydatów, nie przepisując niczego.

CZEGO NIE ROBI — I TO JEST ŚWIADOME

Nie wybiera aut do oferty. Wybór zostaje przy człowieku (`sales/offers.py` opisuje
tę samą zasadę), bo to jest moment, w którym ktoś bierze odpowiedzialność za to, co
zobaczy klient. Ten moduł kończy pracę na liście kandydatów.

Nie wysyła też niczego do klienta. Po wyszukiwaniu powstaje najwyżej propozycja
wiadomości w skrzynce brokera, tak jak przy każdym innym etapie.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sales.models import Lead, Stage

logger = logging.getLogger("sales.search")

# Ile lotów bierzemy z wyszukiwania do przeglądu przez brokera. Więcej niż tuzin
# nikt nie ogląda, a każdy dodatkowy to kolejna karta do przewinięcia w panelu.
MAX_CANDIDATES = 12

# Domyślne okno aukcji dla wyszukiwania z leada. Krótsze niż w panelu, bo lead
# oczekuje odpowiedzi w dniach, a nie „kiedyś" — aukcja kończąca się za tydzień
# nie pomaga rozmowie, która toczy się dzisiaj.
DEFAULT_MIN_HOURS = 12
DEFAULT_MAX_HOURS = 120


@dataclass(frozen=True)
class Readiness:
    """Czy da się z tego leada zbudować wyszukiwanie."""

    ready: bool
    #: Dane, których nie mamy. Odpowiedź na pytanie „czego brakuje".
    missing: list[str]
    #: Rzeczy, o których broker ma wiedzieć, choć wyszukiwania nie blokują.
    #: Osobno od `missing`, bo „brakuje: czeka na sprzedaż Audi" to nie jest brak
    #: danych, tylko stan klienta — i czyta się jak pomyłka.
    warnings: list[str] = field(default_factory=list)

    def reason(self) -> str:
        return "brakuje: " + ", ".join(self.missing) if self.missing else "gotowe"

    def notes(self) -> list[str]:
        return [*(f"brakuje: {m}" for m in self.missing), *self.warnings]


def readiness(lead: Lead) -> Readiness:
    """Czego brakuje, żeby ruszyć z wyszukiwaniem.

    Marka jest jedynym polem twardo wymaganym — `ClientCriteria` bez niej nie
    powstanie. Budżet nie jest wymagany technicznie, ale bez niego sufit ceny
    aukcyjnej nie istnieje i scoring nie odróżni auta w zasięgu klienta od auta
    dwa razy za drogiego. Dlatego jest na liście braków, choć nie blokuje.
    """
    missing: list[str] = []
    warnings: list[str] = []

    if not lead.make:
        missing.append("marka")
    if not lead.confirmed_budget_pln:
        missing.append("budżet pod drzwi")

    # Sufit liczymy z budżetu POTWIERDZONEGO, więc klient z autem do sprzedania
    # zobaczy węższą listę, niż na jaką go ostatecznie stać. To jest zamierzone,
    # ale broker musi o tym wiedzieć, zanim wyśle ofertę.
    if lead.waiting_on:
        warnings.append(f"czeka na: {lead.waiting_on}")
    if lead.trade_in_value_pln and not lead.trade_in_sold:
        warnings.append(
            f"sufit liczony bez {lead.trade_in_value_pln:,.0f} zł z niesprzedanego auta".replace(
                ",", " "
            )
        )

    return Readiness(ready=bool(lead.make), missing=missing, warnings=warnings)


def criteria_from_lead(lead: Lead, *, max_results: int = MAX_CANDIDATES):
    """`ClientCriteria` z danych leada. None, gdy nie ma nawet marki.

    Budżet przekazujemy jako kwotę POD DRZWI (`budget_pln_to`), a nie jako
    `budget_usd` — to jest ta sama liczba, którą klient wypowiedział, a sufit
    ceny aukcyjnej wylicza z niej `scoring/budget.py` osobno dla każdego stanu USA.
    Przeliczenie budżetu na dolary tutaj oznaczałoby zgadywanie kursu i kosztów
    transportu w miejscu, które ich nie zna.
    """
    from parser.models import ClientCriteria

    if not lead.make:
        return None

    return ClientCriteria(
        make=lead.make,
        model=lead.model,
        year_from=lead.year_from,
        year_to=lead.year_to,
        max_odometer_mi=lead.max_odometer_mi,
        # POTWIERDZONY, nie potencjalny. Wyszukiwanie decyduje, co klient zobaczy
        # w ofercie — pokazanie mu aut za kwotę, której jeszcze nie ma, kończy się
        # dopłatą po drodze albo wycofaniem się przy podpisaniu.
        budget_pln_to=lead.confirmed_budget_pln,
        settlement=lead.settlement,
        max_results=max_results,
    )


async def run_search_for_lead(lead_id: int) -> dict[str, Any]:
    """Uruchamia wyszukiwanie dla leada i zapisuje kandydatów przy nim.

    Idzie tą samą kolejką, co panel (`api/main._run_job_with_queue`), więc scrape
    nie zaczyna się równolegle do innego i wyniki przechodzą przez ten sam scoring.
    Duplikowanie tej ścieżki dałoby drugi zestaw ocen, a wtedy lead i panel
    pokazywałyby dla tego samego auta inne liczby.

    Wywoływane w tle — trwa minuty. Wyjątek zapisujemy przy leadzie zamiast go
    podnosić: zadanie w tle nie ma komu zgłosić błędu, a broker musi zobaczyć,
    że wyszukiwanie padło, zamiast czekać w nieskończoność na wynik.
    """
    from sales import db

    lead = db.get_lead(lead_id)
    if lead is None:
        raise ValueError(f"nie ma leada {lead_id}")

    criteria = criteria_from_lead(lead)
    if criteria is None:
        raise ValueError("lead nie ma marki — nie ma czego szukać")

    search_id = db.start_lead_search(lead_id, criteria.model_dump(mode="json"))

    try:
        # Import leniwy: `api/main.py` ładuje `api/sales_routes.py`, więc zależność
        # na poziomie modułu zamknęłaby cykl.
        from api import jobs as jobs_store
        from api.main import SearchRequest, _run_job_with_queue

        request = SearchRequest(
            criteria=criteria,
            auction_min_hours=DEFAULT_MIN_HOURS,
            auction_max_hours=DEFAULT_MAX_HOURS,
            suppress_completion_notify=True,
        )
        job = jobs_store.create_job(request_snapshot=request.model_dump(mode="json"))
        await _run_job_with_queue(request, job)

        if job.status != "done" or not job.result:
            raise RuntimeError(job.error or f"wyszukiwanie zakończone statusem {job.status}")

        candidates = _candidates_from_result(job.result)
        db.finish_lead_search(search_id, job_id=job.id, candidates=candidates)
        logger.info("[sales] lead #%s — wyszukiwanie gotowe, %s kandydatów", lead_id, len(candidates))

        lead = db.get_lead(lead_id) or lead
        if lead.stage in (Stage.NOWY, Stage.KWALIFIKACJA, Stage.SZUKANIE):
            lead.stage = Stage.SZUKANIE
            db.update_lead(lead)

        return {"search_id": search_id, "job_id": job.id, "candidates": len(candidates)}

    except Exception as exc:  # noqa: BLE001 — zadanie w tle nie ma komu zgłosić błędu
        logger.warning("[sales] lead #%s — wyszukiwanie padło: %s", lead_id, exc)
        db.fail_lead_search(search_id, str(exc))
        raise


def _candidates_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Kandydaci z wyniku joba — lot razem z oceną, w kolejności z rankingu.

    Zostawiamy `analysis` przy locie, bo broker wybiera auta patrząc na ocenę
    i uzasadnienie, a nie na sam opis. Odcięcie oceny tutaj znaczyłoby, że musi
    ją odszukać w innym ekranie.
    """
    wszystkie = result.get("all_results") or []
    kandydaci: list[dict[str, Any]] = []
    for item in wszystkie[:MAX_CANDIDATES]:
        lot = item.get("lot")
        if not lot:
            continue
        kandydaci.append(
            {
                "lot": lot,
                "score": (item.get("analysis") or {}).get("unified_score"),
                "recommendation": (item.get("analysis") or {}).get("recommendation"),
                "reasoning": (item.get("analysis") or {}).get("reasoning"),
                "is_top": bool(item.get("is_top_recommendation")),
            }
        )
    return kandydaci
