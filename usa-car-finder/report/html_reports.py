"""
Renders client_report.html.j2 and broker_report.html.j2 from AnalyzedLot data.
"""
import logging
import os
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from parser.models import AnalyzedLot, ClientCriteria
from pricing.import_calculator import (
    calculate_lot_import_costs,
    format_pln,
    format_usd,
    DEFAULT_USD_RATE,
    DEFAULT_EXCISE_RATE,
    AUCTION_FEE_RATE,
)

logger = logging.getLogger("report.html_reports")

TEMPLATES_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
)


def _t(value) -> str:
    if value is None or value == "":
        return "brak danych"
    return str(value)


def _resolve_pipeline_filter_bool(filter_key: str, env_var: str, default: bool) -> bool:
    """Filtr systemowy: nadpisanie z dashboardu (settings_db) ma pierwszeństwo
    przed .env — ten sam mechanizm co w scraper/automated_scraper.py, żeby
    raport pokazywał DOKŁADNIE to, co faktycznie zostało zastosowane."""
    try:
        from api.settings_db import get_pipeline_filter_override
        override = get_pipeline_filter_override(filter_key)
        if override is not None:
            return override
    except Exception as exc:
        logger.debug("[html_reports] settings_db filter override lookup failed for %s, using .env default: %s", filter_key, exc)
    return os.getenv(env_var, str(default)).lower() == "true"


def _mileage(value) -> str:
    """Przebieg w milach i kilometrach.

    Aukcje amerykańskie podają mile, a polski klient liczy w kilometrach —
    „26 897 mi" nie mówi mu, czy auto jest przejechane, dopóki sam nie przeliczy.
    Milę zostawiamy obok, bo to ona widnieje na liczniku i w dokumentach aukcji.
    """
    if value is None:
        return "brak danych"
    try:
        mile = int(value)
    except (TypeError, ValueError):
        return str(value)
    km = round(mile * 1.609344)
    return f"{mile:,} mi ({km:,} km)".replace(",", " ")


def _damage_str(lot) -> str:
    parts = [lot.damage_primary, lot.damage_secondary]
    return " + ".join(p for p in parts if p) or "brak danych"


def _location_str(lot) -> str:
    return ", ".join(p for p in [lot.location_city, lot.location_state] if p) or "brak danych"


def _engine_str(lot) -> str:
    parts = [lot.trim]
    return " ".join(p for p in parts if p) or ""


def _recommendation_css(recommendation: str) -> str:
    mapping = {
        "POLECAM": "polecam",
        "RYZYKO": "obserwuj",
        "ODRZUĆ": "odrzuc",
    }
    return mapping.get(recommendation, "obserwuj")


def _pill_style_for_score(score: float) -> str:
    if score >= 7:
        return "ok"
    if score >= 5:
        return "amber"
    return "blue"


def _build_pills(item: AnalyzedLot) -> list[dict]:
    lot = item.lot
    ai = item.analysis
    pills = []

    if ai.recommendation == "POLECAM":
        pills.append({"text": f"Wynik AI: {ai.score:.1f}/10", "style": "ok"})
    elif ai.recommendation == "RYZYKO":
        pills.append({"text": f"Wynik AI: {ai.score:.1f}/10", "style": "amber"})
    else:
        pills.append({"text": f"Wynik AI: {ai.score:.1f}/10", "style": "blue"})

    if lot.title_type:
        pills.append({"text": lot.title_type, "style": "blue"})

    if lot.keys is True:
        pills.append({"text": "Kluczyki", "style": "ok"})
    elif lot.keys is False:
        pills.append({"text": "Brak kluczyków", "style": "amber"})

    if lot.odometer_mi:
        pills.append({"text": _mileage(lot.odometer_mi), "style": "blue"})

    if lot.location_state:
        pills.append({"text": lot.location_state, "style": "blue"})

    return pills


def _data_aukcji_po_polsku(surowa: Optional[str]) -> str:
    """ISO 8601 z aukcji na datę, jaką człowiek zapisuje w kalendarzu.

    Klient dostawał w ofercie `2026-08-10T20:00:00Z` — czyli strefę UTC i literę Z,
    z których nic mu nie wynika. Jeśli formatu nie da się rozpoznać, oddajemy
    wejście bez zmian: lepiej pokazać surowe niż zgadywać dzień.
    """
    if not surowa:
        return ""
    try:
        moment = datetime.fromisoformat(str(surowa).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(surowa)
    return moment.strftime("%d.%m.%Y, godz. %H:%M")


_OPIS_OCENY = (
    (4.5, "praktycznie bez wad — ślady zwykłego użytkowania, nic do naprawy przed jazdą"),
    (4.0, "bardzo dobry stan — pojedyncze rysy albo odpryski lakieru"),
    (3.0, "widoczne ślady eksploatacji — kosmetyka do poprawy, mechanika sprawna"),
    (2.0, "wymaga napraw blacharsko-lakierniczych"),
    (0.0, "poważne uszkodzenia — auto do gruntownej naprawy"),
)


def _informacje_o_samochodzie(item: AnalyzedLot, koszty: Optional[dict] = None) -> list[str]:
    """Punkty do sekcji „Informacje o samochodzie" — wyłącznie z faktów.

    NIE używamy tu `analysis.client_description_pl`. Mimo nazwy jest to notatka
    dla brokera: zawiera cenę aukcyjną, szacunek naprawy w dolarach i wewnętrzny
    werdykt („Rekomendacja: ryzyko"). Wklejenie jej do oferty pokazywało klientowi
    marżę i opinię, która nigdy nie miała opuścić panelu.

    Każdy punkt to jedno zdanie o jednej rzeczy, po polsku, bez żargonu aukcyjnego
    i bez kwot w dolarach — klient rozlicza się w złotówkach pod klucz.
    """
    lot = item.lot
    punkty: list[str] = []

    rocznik = f"{lot.year} " if lot.year else ""
    marka = " ".join(p for p in [lot.make, lot.model] if p)
    if marka:
        punkty.append(f"{rocznik}{marka}{f' w wersji {lot.trim}' if lot.trim else ''}.")

    if lot.odometer_mi:
        punkty.append(f"Przebieg {_mileage(lot.odometer_mi)}, potwierdzony przez aukcję.")

    if lot.location_state:
        punkty.append(f"Auto stoi w {_location_str(lot)} — stamtąd organizuję transport do portu.")

    if lot.keys is True:
        punkty.append("Kluczyki są w komplecie, nie trzeba ich dorabiać.")

    if lot.airbags_deployed is False:
        punkty.append("Poduszki powietrzne nierozbite — to oszczędza kilka tysięcy przy naprawie.")

    if lot.seller_type == "insurance":
        punkty.append("Sprzedaje ubezpieczalnia, więc historia dokumentów jest kompletna.")

    if koszty and koszty.get("duty_rate_pct") == 0:
        punkty.append(
            "Auto montowane w USA, więc wchodzi do Polski bez cła — przy tej klasie "
            "samochodu to oszczędność rzędu kilkunastu tysięcy złotych."
        )

    punkty.append(
        "Mam komplet zdjęć i danych z aukcji — prześlę wszystko, co chce Pan zobaczyć."
    )
    return punkty


def _zdjecia_do_wklejenia(adresy: list[str]) -> list[str]:
    """Zamienia adresy zdjęć na `data:` — obraz wchodzi do pliku HTML.

    Raport był dotąd zbiorem odnośników do serwerów aukcji. Klient dostaje ten
    plik mailem i otwiera go czasem bez internetu, a aukcja zdejmuje zdjęcia po
    sprzedaży lota — w obu przypadkach zostawała pusta ramka i oferta bez auta.
    Wklejone zdjęcie jedzie razem z dokumentem i przeżywa jedno i drugie.

    Przy niepowodzeniu zostaje zwykły adres: lepszy odnośnik, który może zadziałać,
    niż brak zdjęcia. `REPORT_EMBED_IMAGES=false` wyłącza wklejanie w całości.
    """
    if os.getenv("REPORT_EMBED_IMAGES", "true").lower() != "true":
        return adresy

    import base64
    import urllib.request

    limit_na_zdjecie = int(os.getenv("REPORT_IMAGE_MAX_BYTES", str(2 * 1024 * 1024)))
    # Poczta odbija załączniki powyżej ok. 20 MB, a raport bywa wysyłany mailem.
    limit_razem = int(os.getenv("REPORT_IMAGE_TOTAL_BYTES", str(8 * 1024 * 1024)))
    czas = float(os.getenv("REPORT_IMAGE_TIMEOUT_SECONDS", "5"))

    wynik: list[str] = []
    zuzyte = 0
    for adres in adresy:
        if not adres.startswith("http") or zuzyte >= limit_razem:
            wynik.append(adres)
            continue
        try:
            zadanie = urllib.request.Request(adres, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(zadanie, timeout=czas) as odpowiedz:
                typ = odpowiedz.headers.get("Content-Type", "image/jpeg").split(";")[0]
                dane = odpowiedz.read(limit_na_zdjecie + 1)
            if len(dane) > limit_na_zdjecie or not typ.startswith("image/"):
                wynik.append(adres)
                continue
            zuzyte += len(dane)
            wynik.append(f"data:{typ};base64,{base64.b64encode(dane).decode('ascii')}")
        except Exception:
            logger.debug("[raport] nie udało się wkleić zdjęcia %s", adres, exc_info=True)
            wynik.append(adres)
    return wynik


def _stan_pojazdu(item: AnalyzedLot) -> dict:
    """Sekcja o stanie — inna dla auta po szkodzie, inna dla auta z oceną.

    Manheim nie podaje pola „uszkodzenie": zamiast niego wystawia ocenę stanu
    w skali do 5. Dotąd wchodziła ona pod nagłówek „Co jest uszkodzone" jako
    napis „Condition grade 4.9", co czytało się jak usterka, a znaczy coś wprost
    przeciwnego. Klientowi trzeba powiedzieć, co ta liczba znaczy — sama w sobie
    nie mówi mu nic.
    """
    lot = item.lot
    ai = item.analysis
    surowe = (lot.damage_primary or "").strip()

    import re as _re

    trafienie = _re.search(r"(?:condition\s*grade|grade)\s*([0-5](?:[.,]\d)?)", surowe, _re.I)
    if trafienie:
        ocena = float(trafienie.group(1).replace(",", "."))
        opis = next(tekst for prog, tekst in _OPIS_OCENY if ocena >= prog)
        return {
            "tytul": "Stan techniczny",
            "wartosc": f"Ocena {ocena:.1f} na 5",
            "opis": (
                f"To ocena stanu wystawiona przez giełdę: {opis}. "
                "Dotyczy wyglądu i mechaniki, nie historii pojazdu — tę sprawdzam osobno."
            ),
            "ostrzezenie": ocena < 3.5,
        }

    return {
        "tytul": "Co jest uszkodzone",
        "wartosc": _damage_str(lot),
        "opis": (
            f"Szacowany koszt naprawy: {format_usd(ai.estimated_repair_usd)}"
            if ai.estimated_repair_usd
            else "Zakres naprawy wycenię po obejrzeniu zdjęć w wyższej rozdzielczości."
        ),
        "ostrzezenie": True,
    }


def _build_client_facts(item: AnalyzedLot) -> list[dict]:
    """Fakty do oferty — etykieta i wartość, bez języka sprzedaży.

    Wcześniej szablon rozbijał po dwukropku napisy zbudowane dla innej sekcji
    („Przebieg 26 897 mi" nie miało dwukropka i wychodziła z tego etykieta
    „Szczegół"). Klient ma zobaczyć nazwane pola, a nie ślad po parsowaniu.
    """
    lot = item.lot
    fakty: list[dict] = []

    # Aukcje wstawiają w puste pola napisy, które wyglądają jak dane.
    # „Tytuł własności: Not Specified" nie mówi klientowi nic — a zajmuje wiersz
    # i sprawia wrażenie, że coś sprawdziliśmy.
    PUSTE = {"not specified", "unknown", "n/a", "none", "brak", "-"}

    def dodaj(etykieta: str, wartosc) -> None:
        if wartosc in (None, "", 0):
            return
        if str(wartosc).strip().lower() in PUSTE:
            return
        fakty.append({"etykieta": etykieta, "wartosc": str(wartosc)})

    dodaj("Rocznik", lot.year)
    dodaj("Przebieg", _mileage(lot.odometer_mi) if lot.odometer_mi else None)
    # `_engine_str` schodzi na wersję wyposażenia, gdy nie zna silnika. Podpisanie
    # „XLE" jako silnika jest po prostu nieprawdą, więc etykieta idzie za treścią.
    silnik = _engine_str(lot)
    dodaj("Wersja" if silnik and silnik == (lot.trim or "") else "Silnik", silnik)
    # Gdy „uszkodzeniem" jest ocena stanu z Manheima, wiersz pomijamy: ma własną
    # sekcję niżej, z wyjaśnieniem skali. Powtórzony tutaj wracałby jako
    # „Uszkodzenie: Condition grade 4.9" — czyli w formie, której się pozbywamy.
    import re as _re

    if lot.damage_primary and not _re.search(
        r"(?:condition\s*grade|grade)\s*[0-5]", lot.damage_primary, _re.I
    ):
        dodaj("Uszkodzenie", lot.damage_primary)
    dodaj("Tytuł własności", lot.title_type)
    dodaj("Gdzie stoi", _location_str(lot) if lot.location_state else None)
    dodaj("Aukcja", _data_aukcji_po_polsku(lot.auction_date))
    dodaj("VIN", lot.vin or lot.full_vin)
    return fakty


def _build_spec_rows(item: AnalyzedLot) -> list[dict]:
    lot = item.lot
    rows = []

    if lot.odometer_mi:
        rows.append({
            "feature": f"Przebieg {_mileage(lot.odometer_mi)}",
            "benefit": "Znany rzeczywisty stan licznika z rynku USA",
        })

    if lot.damage_primary:
        rows.append({
            "feature": f"Uszkodzenie: {lot.damage_primary}",
            "benefit": "Konkretny zakres naprawy, bez ukrytych niespodzianek",
        })

    if lot.title_type:
        rows.append({
            "feature": f"Tytuł: {lot.title_type}",
            "benefit": "Znany status prawny pojazdu przed zakupem",
        })

    if lot.keys is True:
        rows.append({
            "feature": "Kluczyki obecne",
            "benefit": "Brak dodatkowych kosztów dorabiania kluczyków",
        })

    if lot.seller_type == "insurance":
        rows.append({
            "feature": "Sprzedawca: ubezpieczalnia",
            "benefit": "Pewna historia dokumentacyjna, brak ukrytych zastawów",
        })

    if lot.location_state:
        rows.append({
            "feature": f"Lokalizacja: {_location_str(lot)}",
            "benefit": "Znany koszt transportu do portu",
        })

    return rows


def _build_damage_ok_items(item: AnalyzedLot) -> list[dict]:
    lot = item.lot
    ok_items = []

    if lot.airbags_deployed is False:
        ok_items.append({
            "title": "Poduszki nierozbite",
            "body": "Brak konieczności wymiany — oszczędność ok. $2 000–$4 000",
        })
    elif lot.airbags_deployed is True:
        pass

    if lot.keys is True:
        ok_items.append({
            "title": "Kluczyki w komplecie",
            "body": "Nie ma potrzeby dorabiania — pojazd gotowy do uruchomienia",
        })

    if lot.title_type and "salvage" not in lot.title_type.lower():
        ok_items.append({
            "title": "Tytuł do rejestracji",
            "body": f"{lot.title_type} — możliwa rejestracja po naprawie",
        })

    if not ok_items:
        ok_items.append({
            "title": "Weryfikacja po zakupie",
            "body": "Pełna ocena po przeglądzie technicznym w Polsce",
        })

    return ok_items


def _build_timeline_steps() -> list[dict]:
    return [
        {"day": "1", "day_label": "Dzień 1", "label": "Wygranie aukcji", "desc": "Potwierdzenie wyniku i wpłata depozytu aukcyjnego"},
        {"day": "7", "day_label": "Tydzień 1", "label": "Transport do portu", "desc": "Załadunek i wysyłka z USA (RORO lub kontener)"},
        {"day": "30", "day_label": "Miesiąc 1–2", "label": "Odprawa celna w DE/PL", "desc": "Dokumenty, VAT, cło, akcyza — przy Pana/Pani obecności lub zdalnie"},
        {"day": "45", "day_label": "Tydzień 6–8", "label": "Naprawa i homologacja", "desc": "Warsztat, badanie techniczne, rejestracja w Polsce"},
        {"day": "60", "day_label": "Miesiąc 2–3", "label": "Odbiór pojazdu", "desc": "Auto gotowe do jazdy — zarejestrowane w Polsce"},
    ]


def _build_docs_list() -> list[str]:
    return [
        "Tytuł własności (Title) z USA",
        "Bill of Sale z aukcji",
        "Dokumenty odprawy celnej",
        "Potwierdzenie akcyzy i VAT",
        "Protokół badania technicznego",
        "Karta pojazdu (PL)",
    ]


def _build_cost_rows(costs: dict) -> list[dict]:
    usd = costs.get("usa_total_usd", 0)
    rate = costs.get("usd_rate", DEFAULT_USD_RATE)
    optimistic_factor = 0.85
    pessimistic_factor = 1.15

    rows = [
        {
            "label": "Cena wylicytowana (bid)",
            "optimistic": format_usd(costs.get("bid_usd", 0) * optimistic_factor),
            "pessimistic": format_usd(costs.get("bid_usd", 0) * pessimistic_factor),
        },
        {
            "label": "Opłata aukcyjna (~8%)",
            "optimistic": format_usd(costs.get("auction_fee_usd", 0) * optimistic_factor),
            "pessimistic": format_usd(costs.get("auction_fee_usd", 0) * pessimistic_factor),
        },
        {
            "label": "Transport lokalny (towing)",
            "optimistic": format_usd(costs.get("towing_usd", 0) * optimistic_factor),
            "pessimistic": format_usd(costs.get("towing_usd", 0) * pessimistic_factor),
        },
        {
            "label": "Załadunek + fracht morski",
            "optimistic": format_usd((costs.get("loading_usd", 560) + costs.get("freight_usd", 1050)) * optimistic_factor),
            "pessimistic": format_usd((costs.get("loading_usd", 560) + costs.get("freight_usd", 1050)) * pessimistic_factor),
        },
        {
            "label": "Cło + VAT DE + odprawa",
            "optimistic": format_pln(costs.get("private_de_fees_pln", 0) * optimistic_factor),
            "pessimistic": format_pln(costs.get("private_de_fees_pln", 0) * pessimistic_factor),
        },
        {
            "label": "Akcyza PL (3,1%)",
            "optimistic": format_pln(costs.get("private_excise_pln", 0) * optimistic_factor),
            "pessimistic": format_pln(costs.get("private_excise_pln", 0) * pessimistic_factor),
        },
    ]
    return rows


def _build_scoring_criteria(item: AnalyzedLot, costs: Optional[dict]) -> list[dict]:
    lot = item.lot
    ai = item.analysis
    rows = []

    if lot.location_state:
        eastern = {"NY", "NJ", "PA", "CT", "MA", "MD", "VA", "NC", "SC", "GA", "FL", "OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "KY", "TN", "AL", "MS"}
        western = {"CA", "WA", "OR", "NV", "AZ", "CO", "UT", "ID", "MT", "WY", "NM", "AK", "HI"}
        if lot.location_state in eastern:
            rows.append({"name": "Lokalizacja (Wschód USA)", "delta": "+1.5", "justification": "Niższy koszt transportu do portu"})
        elif lot.location_state in western:
            rows.append({"name": "Lokalizacja (Zachód USA)", "delta": "−1.0", "justification": "Wyższy koszt transportu do portu"})

    if lot.damage_primary:
        damage_lower = lot.damage_primary.lower()
        if any(w in damage_lower for w in ["flood", "fire", "burn"]):
            rows.append({"name": "Uszkodzenie krytyczne", "delta": "−3.0", "justification": "Automatyczne odrzucenie wg reguł"})
        elif any(w in damage_lower for w in ["front", "rear", "side"]):
            rows.append({"name": "Uszkodzenie karoserii", "delta": "−1.0", "justification": "Standardowa naprawa blacharsko-lakiernicza"})

    if lot.title_type:
        title_lower = lot.title_type.lower()
        if "salvage" in title_lower:
            rows.append({"name": "Tytuł Salvage", "delta": "−0.5", "justification": "Wymaga przerejestrowania w PL"})
        elif "clean" in title_lower:
            rows.append({"name": "Tytuł Clean", "delta": "+0.5", "justification": "Najprostszy import"})

    if lot.keys is True:
        rows.append({"name": "Kluczyki obecne", "delta": "+0.3", "justification": "Brak dodatkowych kosztów"})
    elif lot.keys is False:
        rows.append({"name": "Brak kluczyków", "delta": "−0.3", "justification": "Dodatkowy koszt dorabiania"})

    if lot.airbags_deployed is False:
        rows.append({"name": "Poduszki nierozbite", "delta": "+0.5", "justification": "Brak kosztownej wymiany"})
    elif lot.airbags_deployed is True:
        rows.append({"name": "Poduszki rozbite", "delta": "−1.0", "justification": "$2k–$4k dodatkowego kosztu"})

    rows.append({"name": "Wynik końcowy AI", "delta": f"{ai.score:.1f}/10", "justification": ai.recommendation})

    return rows


def _build_red_flags(item: AnalyzedLot) -> list[dict]:
    ai = item.analysis
    flags = []
    for flag in (ai.red_flags or []):
        flags.append({"level": "amber", "title": "Ryzyko", "description": flag})
    return flags


def _build_checklist(item: AnalyzedLot) -> list[dict]:
    lot = item.lot
    items = [
        {"action": "Sprawdź VIN w CarFax/AutoCheck", "prio_css": "red", "prio_label": "Wysoki"},
        {"action": "Weryfikacja tytułu własności (Title)", "prio_css": "red", "prio_label": "Wysoki"},
        {"action": "Przejrzyj zdjęcia wysokiej rozdzielczości", "prio_css": "red", "prio_label": "Wysoki"},
        {"action": "Potwierdź opłaty aukcyjne i storage", "prio_css": "amber", "prio_label": "Średni"},
        {"action": "Ustal limit bid przed aukcją", "prio_css": "amber", "prio_label": "Średni"},
        {"action": "Zweryfikuj dostępność części zamiennych", "prio_css": "amber", "prio_label": "Średni"},
    ]
    if lot.airbags_deployed is None:
        items.append({"action": "Sprawdź stan poduszek SRS", "prio_css": "red", "prio_label": "Wysoki"})
    if not lot.keys:
        items.append({"action": "Wycena dorobienia kluczyków", "prio_css": "amber", "prio_label": "Średni"})
    return items


def _whatsapp_line(lot) -> str:
    """Jedno auto w formie, w jakiej broker wyśle je klientowi."""
    from report.whatsapp import build_draft

    draft = build_draft([lot])
    if not draft:
        name = f"{lot.year or ''} {lot.make or ''} {lot.model or ''}".strip()
        return f"{name} z aukcji USA — mam pełną kalkulację pod klucz. Podesłać?"
    return draft.text


def _build_notes(item: AnalyzedLot) -> dict:
    lot = item.lot
    ai = item.analysis
    name = f"{lot.year} {lot.make} {lot.model}"

    return {
        "offer_mode": "Oferta importu z aukcji USA",
        "main_trigger": ai.client_description_pl or f"Wyjątkowa okazja na {name} z aukcji USA",
        "headline_a": f"{name} z USA — transparentny import pod klucz",
        "headline_b": f"Oszczędź vs. rynek PL — {name} prosto z aukcji ubezpieczeniowej",
        "headline_c": f"Konkretna kalkulacja kosztów zamiast domysłów — {name}",
        "communication_risks": "Klient może obawiać się ukrytych kosztów i formalności — zaadresuj to w pierwszej wiadomości",
        "followup_48h": f"Aukcja {lot.auction_date or 'wkrótce'} — potrzebuję potwierdzenia limitu bidu do 24h przed końcem",
        # Gotowa treść z report/whatsapp.py: cena pod klucz w złotówkach, bez
        # wewnętrznej oceny. Broker akceptuje i wysyła — nic nie idzie automatem.
        "short_whatsapp": _whatsapp_line(lot),
        "damaging_admission": "To auto ma uszkodzenia karoserii — piszę o tym otwarcie, bo ukrywanie tego nie ma sensu",
    }


def build_client_context(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None) -> dict:
    lot = item.lot
    ai = item.analysis
    costs = calculate_lot_import_costs(lot)

    total_cost_pln = format_pln(costs["private_total_pln"]) if costs else "brak danych"

    cta_headline = f"Zainteresowany tym {lot.make} {lot.model}?"
    cta_body = (
        "Odpiszcie do mnie — ustalimy limit licytacji, kalkulację importu "
        "i harmonogram. Aukcja jest konkretna, terminy napięte."
    )

    return {
        "make": _t(lot.make),
        "model": _t(lot.model),
        "year": _t(lot.year),
        "trim": lot.trim or "",
        "engine_str": _engine_str(lot),
        "hp": None,
        "drive": None,
        "location_state": lot.location_state or "",
        "auction_date": lot.auction_date or "",
        "pills": _build_pills(item),
        "photo_url": lot.images[0] if lot.images else None,
        # Galeria, nie jedno zdjecie: klient decyduje o wydatku rzedu 100 tys. zl
        # i pierwsze, o co pyta, to „a jak to wyglada z drugiej strony".
        "photos": _zdjecia_do_wklejenia(list(lot.images or [])[:6]),
        "headline_text": ai.client_description_pl or f"Sprawdzony {lot.year} {lot.make} {lot.model} z aukcji USA",
        "subhead_text": f"Szacowany koszt w Polsce: {total_cost_pln}",
        "story_paragraphs": [
            ai.client_description_pl or f"Ten {lot.year} {lot.make} {lot.model} pochodzi z aukcji ubezpieczeniowej w USA.",
            f"Pojazd znajdował się w {_location_str(lot)}. "
            f"Uszkodzenie: {_damage_str(lot)}. "
            f"Przebieg: {_mileage(lot.odometer_mi)}.",
            "Każde auto przechodzi przez naszą analizę przed wysłaniem oferty. "
            "Podajemy tylko realne koszty — bez ukrytych opłat.",
        ],
        "spec_rows": _build_spec_rows(item),
        "fakty": _build_client_facts(item),
        "stan": _stan_pojazdu(item),
        "informacje": _informacje_o_samochodzie(item),
        "damage_what": _damage_str(lot),
        "damage_repair": f"Szacowany koszt naprawy: {format_usd(ai.estimated_repair_usd)}" if ai.estimated_repair_usd else "Do wyceny po inspekcji",
        "damage_ok_items": _build_damage_ok_items(item),
        "timeline_steps": _build_timeline_steps(),
        "docs_list": _build_docs_list(),
        "cta_headline": cta_headline,
        "cta_body": cta_body,
        "auction_deadline": _data_aukcji_po_polsku(lot.auction_date),
        "scarcity_note": "Aukcja niepowtarzalna — każdy pojazd licytowany jest tylko raz",
        "vin": lot.vin or lot.full_vin or "",
        "lot_id": lot.lot_id,
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }


def _build_pipeline_rules(criteria: ClientCriteria) -> list[str]:
    """Lista WSZYSTKICH filtrów faktycznie stosowanych przez scraper/pipeline
    dla tego wyszukiwania — łączy env-driven config (seller/auction window)
    z kryteriami klienta (year/odometer/damage/fuel/sources), żeby broker
    widział dokładnie co zawęziło wyniki, nie tylko przybliżony opis.
    """
    rules: list[str] = []

    seller_filter = _resolve_pipeline_filter_bool("seller_insurance_only", "FILTER_SELLER_INSURANCE_ONLY", False)
    rules.append(
        "Sprzedawca: tylko insurance (ubezpieczyciel)" if seller_filter
        else "Sprzedawca: insurance + dealer (bez filtra)"
    )

    min_h = os.getenv("MIN_AUCTION_WINDOW_HOURS", "12")
    max_h = os.getenv("MAX_AUCTION_WINDOW_HOURS", "120")
    rules.append(f"Okno aukcji: {min_h}–{max_h}h od teraz")

    if criteria.year_from or criteria.year_to:
        rules.append(f"Rocznik: {criteria.year_from or '?'}–{criteria.year_to or '?'}")

    if criteria.max_odometer_mi:
        rules.append(f"Maks. przebieg: {criteria.max_odometer_mi:,} mi".replace(",", " "))

    if criteria.fuel_type:
        rules.append(f"Typ paliwa: {criteria.fuel_type} (filtr server-side tylko na Copart — IAAI go nie wspiera)")

    excluded = ", ".join(criteria.excluded_damage_types) if criteria.excluded_damage_types else "brak"
    rules.append(f"Wykluczone uszkodzenia: {excluded}")

    if criteria.allowed_damage_types:
        rules.append(f"Dozwolone uszkodzenia (jawnie wskazane): {', '.join(criteria.allowed_damage_types)}")

    exclude_convertible = _resolve_pipeline_filter_bool("exclude_convertible", "FILTER_EXCLUDE_CONVERTIBLE", True)
    rules.append(
        "Kabriolet/roadster/spider: wykluczony, chyba że model klienta jawnie o to prosi"
        if exclude_convertible else
        "Kabriolet/roadster/spider: NIE wykluczany (filtr wyłączony w ustawieniach)"
    )

    sources = ", ".join(criteria.sources).upper() if criteria.sources else "COPART, IAAI"
    rules.append(f"Źródła: {sources}")

    rules.append(f"Limit wyników: {criteria.max_results} (twardy cap)")
    rules.append("Priorytet otwierania szczegółów: loty z najmniejszymi widocznymi uszkodzeniami najpierw")

    return rules


def build_broker_context(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None, lots_scanned: int = 0) -> dict:
    lot = item.lot
    ai = item.analysis
    costs = calculate_lot_import_costs(lot)

    bid = lot.current_bid_usd or lot.buy_now_price_usd or 0
    repair = ai.estimated_repair_usd or 0
    acv_usd = bid + repair

    criteria_summary = ""
    if criteria:
        parts = [criteria.make, criteria.model or ""]
        if criteria.year_from:
            parts.append(f"od {criteria.year_from}")
        if criteria.year_to:
            parts.append(f"do {criteria.year_to}")
        if criteria.budget_usd:
            parts.append(f"budżet ${criteria.budget_usd:,.0f}")
        criteria_summary = " ".join(p for p in parts if p)

    cost_rows = _build_cost_rows(costs) if costs else []

    total_opt_usd = costs["usa_total_usd"] * 0.85 if costs else None
    total_pes_usd = costs["usa_total_usd"] * 1.15 if costs else None
    total_opt_pln = costs["private_total_pln"] * 0.85 if costs else None
    total_pes_pln = costs["private_total_pln"] * 1.15 if costs else None

    reserve = lot.seller_reserve_usd
    bid_breakeven = acv_usd * 0.6 if acv_usd else None
    bid_max = acv_usd * 0.55 if acv_usd else None

    raw_fields = [
        {"key": "source", "value": lot.source},
        {"key": "lot_id", "value": lot.lot_id},
        {"key": "vin", "value": lot.vin or ""},
        {"key": "full_vin", "value": lot.full_vin or ""},
        {"key": "year", "value": str(lot.year or "")},
        {"key": "make", "value": lot.make or ""},
        {"key": "model", "value": lot.model or ""},
        {"key": "trim", "value": lot.trim or ""},
        {"key": "odometer_mi", "value": str(lot.odometer_mi or "")},
        {"key": "damage_primary", "value": lot.damage_primary or ""},
        {"key": "damage_secondary", "value": lot.damage_secondary or ""},
        {"key": "title_type", "value": lot.title_type or ""},
        {"key": "current_bid_usd", "value": format_usd(lot.current_bid_usd)},
        {"key": "buy_now_price_usd", "value": format_usd(lot.buy_now_price_usd)},
        {"key": "seller_reserve_usd", "value": format_usd(lot.seller_reserve_usd)},
        {"key": "seller_type", "value": lot.seller_type or ""},
        {"key": "location_state", "value": lot.location_state or ""},
        {"key": "location_city", "value": lot.location_city or ""},
        {"key": "auction_date", "value": lot.auction_date or ""},
        {"key": "keys", "value": str(lot.keys)},
        {"key": "airbags_deployed", "value": str(lot.airbags_deployed)},
        {"key": "enriched_by_extension", "value": str(lot.enriched_by_extension)},
    ]

    pipeline_rules = _build_pipeline_rules(criteria) if criteria else ["Brak kryteriów wyszukiwania"]

    excluded_damage = ", ".join(criteria.excluded_damage_types) if criteria and criteria.excluded_damage_types else "Flood, Fire"
    sources_str = ", ".join(criteria.sources).upper() if criteria and criteria.sources else "COPART, IAAI"

    return {
        "make": _t(lot.make),
        "model": _t(lot.model),
        "year": _t(lot.year),
        "trim": lot.trim or "",
        "lot_id": lot.lot_id,
        "source": (lot.source or "").upper(),
        "url": lot.url or "",
        "location_city": lot.location_city or "",
        "location_state": lot.location_state or "",
        "vin": lot.vin or "",
        "full_vin": lot.full_vin or "",
        "recommendation": ai.recommendation,
        "recommendation_css": _recommendation_css(ai.recommendation),
        "score": f"{ai.score:.1f}",
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "criteria_summary": criteria_summary or "Brak kryteriów",
        "sources_str": sources_str,
        "excluded_damage": excluded_damage,
        "lots_scanned": lots_scanned,
        "damage_score": _damage_str(lot),
        "acv_usd": format_usd(acv_usd) if acv_usd else "brak danych",
        "cost_optimistic_usd": format_usd(total_opt_usd),
        "cost_pessimistic_usd": format_usd(total_pes_usd),
        "criteria": criteria,
        "pipeline_rules": pipeline_rules,
        "lot_raw_fields": [f for f in raw_fields if f["value"]],
        "scoring_criteria": _build_scoring_criteria(item, costs),
        "cost_rows": cost_rows,
        "cost_total_optimistic_usd": format_usd(total_opt_usd),
        "cost_total_pessimistic_usd": format_usd(total_pes_usd),
        "cost_total_optimistic_pln": format_pln(total_opt_pln),
        "cost_total_pessimistic_pln": format_pln(total_pes_pln),
        "usd_pln_rate": str(costs.get("usd_rate", DEFAULT_USD_RATE)) if costs else str(DEFAULT_USD_RATE),
        # Raport brokera nie mial ani jednego znacznika obrazu, mimo ze lot niesie
        # adresy zdjec. Broker ogladal auto po opisie, a zdjecie sprawdzal osobno
        # na aukcji — a to wlasnie na nim widac, czy uszkodzenie jest tym, co pisze AI.
        "photos": list(lot.images or [])[:6],
        "red_flags": _build_red_flags(item),
        "raw_api_fields": raw_fields,
        "bid_max_suggested": format_usd(bid_max),
        "bid_breakeven": format_usd(bid_breakeven),
        "bid_acv_warning": f"ACV szacowane na {format_usd(acv_usd)}" if acv_usd else "",
        "bid_reserve_note": f"Reserve: {format_usd(reserve)}" if reserve else "Reserve nieznany",
        "bid_last_ask_note": f"Ostatnia oferta: {format_usd(lot.current_bid_usd)}" if lot.current_bid_usd else "",
        "bid_recommendation": ai.ai_notes or "Ustal limit przed aukcją na podstawie pełnej kalkulacji",
        "checklist_items": _build_checklist(item),
        "notes": _build_notes(item),
        "ai_notes": ai.ai_notes or "",
        "client_description_pl": ai.client_description_pl or "",
        "red_flags_raw": ai.red_flags or [],
        "estimated_repair_usd": format_usd(ai.estimated_repair_usd),
        "estimated_total_cost_usd": format_usd(ai.estimated_total_cost_usd),
    }


def render_client_report(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None) -> str:
    ctx = build_client_context(item, criteria)
    tmpl = _jinja_env.get_template("client_report.html.j2")
    return tmpl.render(**ctx)


def render_broker_report(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None, lots_scanned: int = 0) -> str:
    ctx = build_broker_context(item, criteria, lots_scanned=lots_scanned)
    tmpl = _jinja_env.get_template("broker_report.html.j2")
    return tmpl.render(**ctx)
