"""
Wejście leada: zgłoszenie z formularza na stronie → lead, ocena i pierwsza propozycja.

To jest jedyne miejsce w aplikacji, do którego pisze ktoś z zewnątrz. Wszystko, co tu
przychodzi, jest DANYMI, a nie poleceniem — również wtedy, gdy w treści zgłoszenia stoi
zdanie brzmiące jak instrukcja dla modelu. Zgłoszenie trafia potem do wiadomości
użytkownika w `sales/agent.py`, więc traktujemy je jak wejście niezaufane:

  * treść przycinamy do rozsądnej długości, żeby nie dało się zapchać promptu,
  * w wiadomości do modelu opakowujemy ją w wyraźny znacznik cytatu,
  * i tak polegamy na walidatorze wyjścia — bo zasady sprawdzamy na tym, co model
    napisał, a nie na tym, co przeczytał.

DEDUPLIKACJA. Ten sam człowiek pisze drugi raz po dwóch tygodniach. Zakładanie mu
drugiej kartoteki oznacza, że broker widzi dwa leady i nie wie, że rozmowa już trwa —
a klient dostaje pytanie o budżet, który podał poprzednio.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from sales import db
from sales.agent import propose_reply
from sales.models import Author, Channel, Draft, Lead, LeadScore, Stage
from sales.qualification import score_lead

logger = logging.getLogger("sales.intake")

MAX_REQUEST_CHARS = 2_000
MIN_REQUEST_CHARS = 3


@dataclass
class IntakeResult:
    lead: Lead
    score: LeadScore
    draft: Optional[Draft]
    is_new: bool


# ────────────────────────────────────────────────── sygnały wprost z treści


# Sygnały wyciągamy regułami, a nie modelem. Trzy powody: działa bez sesji Claude Code,
# działa natychmiast (formularz nie ma czekać na model) i jest powtarzalne — a to jest
# wejście do oceny, która ma być deterministyczna.
_DAMAGE_YES = (
    "powypadk", "uszkodz", "po szkodzie", "rozbit", "do naprawy", "salvage",
    "lekko uszkodz", "wiem że po", "wiem ze po",
)
_DAMAGE_NO = (
    "bezwypadk", "nieuszkodz", "bez uszkodz", "nie chcę rozbit", "nie chce rozbit",
    "tylko sprawn", "clean title", "nierozbit",
)

_URGENT = ("pilne", "na już", "na juz", "jak najszybciej", "od ręki", "od reki", "w tym miesiącu")
_PATIENT = ("bez pośpiechu", "bez pospiechu", "nie spieszy", "rozglądam się", "rozgladam sie", "na przyszły rok")

# Budżet i rocznik wyciągamy regułami RÓWNIEŻ wtedy, gdy działa parser modelowy.
# Powód jest praktyczny: parser chodzi po sieci i pada — a wtedy lead z wyraźnie
# napisanym "budżet 120 tys." lądował w skrzynce jako lead bez budżetu i dostawał
# pytanie o kwotę, którą przed chwilą podał. Reguła nie zastępuje modelu, tylko
# domyka najczęstsze zapisy.
#
# Wymagamy jednostki ("tys", "k", "zł", "pln") albo sześciocyfrowej kwoty. Gołe "2020"
# to rocznik, a "150000" bez waluty bywa przebiegiem — kwota zgadnięta źle przesuwa
# ocenę i sufit budżetu, więc wolimy jej nie mieć niż mieć nieprawdziwą.
_BUDGET_UNIT = re.compile(
    r"(\d{1,3}(?:[ .]\d{3})*|\d{1,4})\s*(?:[.,]\d+)?\s*(tys\w*|tysi[ąa]c\w*|k)\b",
    re.IGNORECASE,
)
_BUDGET_CURRENCY = re.compile(
    r"(\d{1,3}(?:[ .]\d{3})+|\d{5,7})\s*(?:z[łl]|pln)\b",
    re.IGNORECASE,
)
_YEAR_FROM = re.compile(r"\b(19[89]\d|20[0-4]\d)\s*(?:\+|i nowsz|lub nowsz|od|-|–)", re.IGNORECASE)
_YEAR_RANGE = re.compile(r"\b(19[89]\d|20[0-4]\d)\s*[-–]\s*(19[89]\d|20[0-4]\d)\b")
_YEAR_SINGLE = re.compile(r"\b(?:rocznik|od roku|od)\s+(19[89]\d|20[0-4]\d)\b", re.IGNORECASE)

# Poniżej tego kwota nie jest budżetem na auto, tylko czymś innym w zdaniu.
MIN_PLAUSIBLE_BUDGET_PLN = 10_000.0
MAX_PLAUSIBLE_BUDGET_PLN = 2_000_000.0


def _detect_budget_pln(text: str) -> Optional[float]:
    """Budżet z treści zgłoszenia. None, gdy nie ma pewnego zapisu.

    Bierzemy NAJWIĘKSZĄ znalezioną kwotę. Klient pisze zwykle "do 120 tys." albo
    "80-120 tysięcy" i to górna granica jest budżetem — dolna bywa ceną, od której
    zaczyna oglądać.
    """
    kandydaci: list[float] = []

    for match in _BUDGET_UNIT.finditer(text or ""):
        surowa = match.group(1).replace(" ", "").replace(".", "")
        try:
            kandydaci.append(float(surowa) * 1_000)
        except ValueError:
            continue

    for match in _BUDGET_CURRENCY.finditer(text or ""):
        surowa = match.group(1).replace(" ", "").replace(".", "")
        try:
            kandydaci.append(float(surowa))
        except ValueError:
            continue

    sensowne = [k for k in kandydaci if MIN_PLAUSIBLE_BUDGET_PLN <= k <= MAX_PLAUSIBLE_BUDGET_PLN]
    return max(sensowne) if sensowne else None


def _detect_years(text: str) -> tuple[Optional[int], Optional[int]]:
    """Rocznik od/do z treści. Zakres wygrywa z pojedynczym rokiem."""
    zakres = _YEAR_RANGE.search(text or "")
    if zakres:
        a, b = int(zakres.group(1)), int(zakres.group(2))
        return min(a, b), max(a, b)

    od = _YEAR_FROM.search(text or "") or _YEAR_SINGLE.search(text or "")
    if od:
        return int(od.group(1)), None
    return None, None


def _detect_damage_ok(text: str) -> Optional[bool]:
    """Czy klient sam napisał, że godzi się (lub nie) na auto po szkodzie.

    None znaczy "nie wiemy" i to jest właściwa odpowiedź w większości zgłoszeń.
    Domyślanie się w którąkolwiek stronę psuje ocenę: przyjęcie "tak" ukryłoby
    najczęstszy powód straconych leadów, a przyjęcie "nie" skreślałoby ludzi,
    którzy po prostu o tym nie napisali.
    """
    lowered = (text or "").lower()
    if any(w in lowered for w in _DAMAGE_NO):
        return False
    if any(w in lowered for w in _DAMAGE_YES):
        return True
    return None


def _detect_timeline_days(text: str) -> Optional[int]:
    lowered = (text or "").lower()
    if any(w in lowered for w in _URGENT):
        return 30
    if any(w in lowered for w in _PATIENT):
        return 180
    return None


def _normalize_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) == 9:
        digits = f"48{digits}"
    return digits or None


def _parse_request(text: str) -> dict:
    """Marka, model, rocznik i budżet z treści zgłoszenia.

    Najpierw próbujemy modelem (`ai/message_parser.py`), bo radzi sobie ze zdaniami
    w rodzaju "szukam czegoś jak tiguan, ale z USA". Gdy modelu nie ma, zostają puste
    pola — i to jest w porządku, bo brakujące dane są wejściem do pytania w pierwszej
    wiadomości, a nie awarią.
    """
    try:
        from ai.message_parser import parse_client_message

        parsed = parse_client_message(text) or {}
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:  # noqa: BLE001 — parser jest opcjonalny
        logger.info("parser wiadomości niedostępny (%s) — lead bez sparsowanych pól", exc)
        return {}


def _int_or_none(value) -> Optional[int]:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _float_or_none(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# ─────────────────────────────────────────────────────────────────── wejście


def submit(
    *,
    raw_request: str,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    channel: Channel = Channel.FORMULARZ,
    referred_by: Optional[str] = None,
    make_draft: bool = True,
) -> IntakeResult:
    """Przyjmuje zgłoszenie i zwraca lead z oceną oraz propozycją pierwszej wiadomości.

    Nic nie wysyła. Propozycja ląduje w skrzynce brokera jako draft do zatwierdzenia.

    Podnosi `ValueError` przy pustym zgłoszeniu bez kontaktu — takiego rekordu nie ma
    po co zapisywać, a w skrzynce byłby szumem nie do odróżnienia od bota.
    """
    tresc = (raw_request or "").strip()[:MAX_REQUEST_CHARS]
    telefon = _normalize_phone(phone)
    mail = (email or "").strip() or None

    if len(tresc) < MIN_REQUEST_CHARS and not (telefon or mail):
        raise ValueError("puste zgłoszenie bez kontaktu")

    istniejacy = db.find_lead_by_contact(phone=telefon, email=mail)
    lead = istniejacy or Lead(channel=channel)
    is_new = istniejacy is None

    parsed = _parse_request(tresc) if tresc else {}

    # Przy powtórnym zgłoszeniu nie nadpisujemy tego, co już wiemy — nowa treść bywa
    # uboższa od poprzedniej rozmowy. Uzupełniamy tylko puste pola.
    lead.name = lead.name or (name or "").strip() or parsed.get("client_name")
    lead.phone = lead.phone or telefon
    lead.email = lead.email or mail
    lead.referred_by = lead.referred_by or referred_by
    lead.make = lead.make or parsed.get("make")
    lead.model = lead.model or parsed.get("model")
    lead.max_odometer_mi = lead.max_odometer_mi or _int_or_none(parsed.get("max_odometer_mi"))

    # Model pierwszy, reguła jako domknięcie. Kolejność ma znaczenie: model rozumie
    # "coś w okolicach stówki", reguła nie — ale reguła działa, gdy modelu nie ma,
    # a to jest właśnie moment, w którym lead nie może stracić budżetu podanego wprost.
    rocznik_od, rocznik_do = _detect_years(tresc)
    lead.year_from = lead.year_from or _int_or_none(parsed.get("year_from")) or rocznik_od
    lead.year_to = lead.year_to or _int_or_none(parsed.get("year_to")) or rocznik_do
    lead.budget_pln = (
        lead.budget_pln
        or _float_or_none(parsed.get("budget_pln"))
        or _detect_budget_pln(tresc)
    )

    if lead.damage_ok is None:
        lead.damage_ok = _detect_damage_ok(tresc)
    if lead.timeline_days is None:
        lead.timeline_days = _detect_timeline_days(tresc)

    if is_new:
        lead.raw_request = tresc
        lead = db.create_lead(lead)
    else:
        # Kolejne zgłoszenie dopisujemy do historii, zamiast podmieniać oryginał —
        # pierwsze zdanie klienta bywa najlepszym opisem tego, czego naprawdę szuka.
        lead.raw_request = f"{lead.raw_request}\n---\n{tresc}".strip("\n-") if tresc else lead.raw_request
        db.update_lead(lead)

    if tresc:
        db.add_message(lead.id, author=Author.KLIENT, text=tresc, channel=channel)
        lead = db.get_lead(lead.id) or lead

    ocena = score_lead(lead)

    draft = None
    if make_draft:
        historia = db.messages(lead.id)
        draft = propose_reply(lead, historia, score=ocena)
        if draft and draft.text:
            draft = db.save_draft(draft)

    return IntakeResult(lead=lead, score=ocena, draft=draft, is_new=is_new)


def record_client_reply(
    lead_id: int,
    text: str,
    *,
    channel: Channel = Channel.WHATSAPP,
    make_draft: bool = True,
) -> IntakeResult:
    """Klient odpisał — dopisujemy wiadomość i proponujemy odpowiedź.

    Wołane, gdy broker wkleja do panelu to, co przyszło na WhatsAppie. Przy pełnej
    integracji z komunikatorem wejdzie tu webhook, ale reszta łańcucha się nie zmieni:
    wiadomość klienta → przeliczenie oceny → propozycja → zgoda brokera.
    """
    lead = db.get_lead(lead_id)
    if lead is None:
        raise ValueError(f"nie ma leada {lead_id}")

    db.add_message(lead_id, author=Author.KLIENT, text=text.strip()[:MAX_REQUEST_CHARS], channel=channel)

    # Odpowiedź klienta bywa właśnie tą, która rozstrzyga o zgodzie na auto po szkodzie.
    if lead.damage_ok is None:
        wykryte = _detect_damage_ok(text)
        if wykryte is not None:
            lead.damage_ok = wykryte
            db.update_lead(lead)

    if lead.stage is Stage.OFERTA:
        lead.stage = Stage.ROZMOWA
        db.update_lead(lead)

    lead = db.get_lead(lead_id) or lead
    ocena = score_lead(lead)

    draft = None
    if make_draft:
        draft = propose_reply(lead, db.messages(lead_id), score=ocena)
        if draft and draft.text:
            draft = db.save_draft(draft)

    return IntakeResult(lead=lead, score=ocena, draft=draft, is_new=False)
