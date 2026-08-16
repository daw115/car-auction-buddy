"""
Endpointy agenta sprzedażowego: publiczny formularz i skrzynka brokera.

DWA POZIOMY DOSTĘPU, BO TO DWIE RÓŻNE RZECZY

  /api/public/leads   — otwarty. Tu pisze formularz z landing page'a, więc pisze
                        każdy, kto zna adres. Chroni go limit zapytań i pole-pułapka,
                        a nie token — token na stronie publicznej nie jest tajemnicą.
  /api/sales/*        — za tym samym Bearer tokenem, co reszta panelu. To jest widok
                        brokera: oceny, rozmowy i przycisk wysyłki.

ŻADEN ENDPOINT NICZEGO NIE WYSYŁA DO KLIENTA. `approve` zapisuje wiadomość jako
wysłaną i zwraca gotowy link `wa.me` — otwiera go i wysyła człowiek, ze swojego
telefonu. Tak samo działa dziś `report/whatsapp.py` i jest to decyzja produktowa:
wiadomość idzie pod nazwiskiem brokera, więc broker musi ją zobaczyć.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from sales import db, intake
from sales.models import Author, Channel, Draft, Lead, LeadScore, Stage
from sales.qualification import score_lead

logger = logging.getLogger("api.sales")

# DWA ROUTERY, BO MAJĄ RÓŻNĄ OCHRONĘ, a nie dlatego, że tak ładniej.
#
# Bramkę zakłada `api/main.py` przy `include_router`, a nie każdy endpoint osobno.
# Powód jest praktyczny: dekorator na endpoincie łatwo pominąć przy dopisywaniu
# kolejnego i nikt tego nie zauważy, dopóki ktoś nie odczyta cudzych rozmów.
# Przy podziale na routery nowy endpoint dziedziczy ochronę tego, do którego trafił.
public_router = APIRouter(tags=["sales-public"])
router = APIRouter(tags=["sales"])


# ────────────────────────────────────────────────────── ochrona publicznego wejścia


RATE_LIMIT_WINDOW_S = 3600
RATE_LIMIT_MAX = int(os.getenv("LEAD_RATE_LIMIT_PER_HOUR", "10"))

# Limit trzymamy w pamięci procesu. Świadomie: przy jednej instancji to wystarcza,
# a wprowadzanie Redisa dla formularza, który dostaje kilkanaście zgłoszeń dziennie,
# byłoby kosztem bez pokrycia. Przy skalowaniu na wiele instancji trzeba to przenieść
# do współdzielonego magazynu — inaczej limit zwielokrotni się przez liczbę procesów.
_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request) -> None:
    ip = _client_ip(request)
    now = time.time()
    okno = _hits[ip]
    while okno and now - okno[0] > RATE_LIMIT_WINDOW_S:
        okno.popleft()
    if len(okno) >= RATE_LIMIT_MAX:
        raise HTTPException(429, "Za dużo zgłoszeń z tego adresu. Proszę spróbować później.")
    okno.append(now)


# ───────────────────────────────────────────────────────────────────── schematy


class LeadForm(BaseModel):
    """Zgłoszenie z formularza. Wszystko poza treścią jest opcjonalne."""

    message: str = Field(default="", max_length=2_000)
    name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=160)
    referred_by: Optional[str] = Field(default=None, max_length=120)
    # Pole-pułapka: ukryte w formularzu, więc człowiek go nie wypełni. Bot wypełnia
    # wszystko, co znajdzie. Tańsze i mniej uciążliwe niż CAPTCHA.
    website: str = Field(default="", max_length=200)


class VinCheckIn(BaseModel):
    """Zapytanie z darmowego checkera na stronie."""

    vin: str = Field(min_length=8, max_length=20)
    bid_usd: Optional[float] = Field(default=None, gt=0, le=500_000)
    state: Optional[str] = Field(default=None, max_length=2)
    # Marka i model są opcjonalne, ale ich brak realnie zmienia wynik: bez nich
    # detektor napędu widzi samą wersję ("Long Range") i bierze Teslę za spalinową.
    # Elektryk ma cło 10% i akcyzę 0% — pomyłka idzie wtedy w obie strony naraz.
    make: Optional[str] = Field(default=None, max_length=60)
    model: Optional[str] = Field(default=None, max_length=60)
    trim: Optional[str] = Field(default=None, max_length=120)
    settlement: str = Field(default="private", pattern="^(private|company)$")


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    channel: Channel = Channel.WHATSAPP


class ApproveIn(BaseModel):
    edited_text: Optional[str] = Field(default=None, max_length=2_000)


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class StageIn(BaseModel):
    stage: Stage


class LeadPatch(BaseModel):
    """Poprawka danych leada — wszystko opcjonalne, brak pola znaczy „bez zmian".

    TRÓJSTAN `damage_ok` JEST TU SEDNEM, NIE DETALEM.

    `None` znaczy „nie pytaliśmy", a nie „klient się nie zgadza" — i od tej różnicy
    zależy waga składowej w ocenie oraz to, czy lead trafia na parking. Samo
    `Optional[bool]` tego nie utrzyma: pole pominięte i pole wysłane jako `null`
    dają w modelu dokładnie tę samą wartość.

    Rozstrzyga `model_fields_set` (czyli `exclude_unset`): Pydantic pamięta, które
    pola klient faktycznie przysłał. Bez tego każdy PATCH bez `damage_ok` kasowałby
    odpowiedź, którą broker zapisał wcześniej.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[str] = Field(default=None, max_length=160)
    make: Optional[str] = Field(default=None, max_length=60)
    model: Optional[str] = Field(default=None, max_length=60)
    year_from: Optional[int] = Field(default=None, ge=1980, le=2100)
    year_to: Optional[int] = Field(default=None, ge=1980, le=2100)
    budget_pln: Optional[float] = Field(default=None, gt=0, le=10_000_000)
    settlement: Optional[str] = Field(default=None, pattern="^(private|company)$")
    max_odometer_mi: Optional[int] = Field(default=None, gt=0, le=1_000_000)
    damage_ok: Optional[bool] = None
    timeline_days: Optional[int] = Field(default=None, ge=0, le=3650)
    notes: Optional[str] = Field(default=None, max_length=4000)
    # Warunek wznowienia i auto w rozliczeniu. Bez nich `extra="forbid"` odrzucał
    # z 422 formularz, który te pola wyświetla — pola istniały w modelu i w bazie,
    # a jedyna droga zapisu ich nie znała.
    blocked_by: Optional[str] = Field(default=None, max_length=200)
    trade_in_model: Optional[str] = Field(default=None, max_length=120)
    trade_in_year: Optional[int] = Field(default=None, ge=1980, le=2100)
    trade_in_value_pln: Optional[float] = Field(default=None, gt=0, le=10_000_000)
    trade_in_sold: Optional[bool] = None
    engine_hint: Optional[str] = Field(default=None, max_length=60)
    trim_hint: Optional[str] = Field(default=None, max_length=120)


# ───────────────────────────────────────────────────────────── serializacja


def _score_json(score: LeadScore) -> dict[str, Any]:
    return {
        "score": score.score,
        "segment": score.segment.value,
        "segment_label": score.segment.label,
        "summary": score.summary(),
        "next_action": score.next_action,
        "red_flags": score.red_flags,
        "missing": score.missing,
        "components": [
            {
                "key": c.key,
                "label": c.label,
                "value": round(c.value, 3),
                "weight": round(c.weight, 3),
                "points": round(c.points * 100, 1),
                "note": c.note,
            }
            for c in score.components
        ],
    }


def _lead_json(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "name": lead.name,
        "display_name": lead.display_name(),
        "phone": lead.phone,
        "email": lead.email,
        "channel": lead.channel.value,
        "stage": lead.stage.value,
        "raw_request": lead.raw_request,
        "make": lead.make,
        "model": lead.model,
        "year_from": lead.year_from,
        "year_to": lead.year_to,
        "budget_pln": lead.budget_pln,
        # PATCH go przyjmował i wyszukiwarka go używała, ale _lead_json go nie oddawał —
        # więc karta klienta po zapisaniu sufitu przebiegu i tak pokazywała „bez limitu".
        "max_odometer_mi": lead.max_odometer_mi,
        "settlement": lead.settlement,
        "timeline_days": lead.timeline_days,
        "blocked_by": lead.blocked_by,
        "trade_in_model": lead.trade_in_model,
        "trade_in_year": lead.trade_in_year,
        "trade_in_value_pln": lead.trade_in_value_pln,
        "trade_in_sold": lead.trade_in_sold,
        "engine_hint": lead.engine_hint,
        "trim_hint": lead.trim_hint,
        # Dwa budżety liczone, nie przechowywane — patrz `sales/models.Lead`.
        # Panel pokazuje oba, bo różnica między nimi jest treścią rozmowy
        # („mam sto, będę miał sto osiemdziesiąt pięć po sprzedaży Audi").
        "confirmed_budget_pln": lead.confirmed_budget_pln,
        "potential_budget_pln": lead.potential_budget_pln,
        "waiting_on": lead.waiting_on,
        "damage_ok": lead.damage_ok,
        "bought_before": lead.bought_before,
        "referred_by": lead.referred_by,
        "notes": lead.notes,
        # Ustawione = lead awansował na klienta. Panel po tym poznaje, czy pokazać
        # przycisk awansu, czy link do kartoteki.
        "client_id": lead.client_id,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        "last_client_message_at": (
            lead.last_client_message_at.isoformat() if lead.last_client_message_at else None
        ),
    }


def _draft_json(draft: Draft, lead: Optional[Lead] = None) -> dict[str, Any]:
    return {
        "id": draft.id,
        "lead_id": draft.lead_id,
        "text": draft.text,
        "channel": draft.channel.value,
        "rationale": draft.rationale,
        "stage_after": draft.stage_after.value if draft.stage_after else None,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "lead": _lead_json(lead) if lead else None,
    }


def wa_me_link(phone: Optional[str], text: str) -> Optional[str]:
    """Link otwierający WhatsApp z wpisaną treścią. Broker klika i wysyła.

    To jest cały nasz „kanał wyjścia”. Świadomie — integracja z WhatsApp Business API
    wymaga weryfikacji firmy w Meta i szablonów zatwierdzanych przed użyciem, a link
    działa od razu i zostawia wysyłkę tam, gdzie ma być: u człowieka.
    """
    if not phone:
        return None
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) == 9:
        digits = f"48{digits}"
    return f"https://wa.me/{digits}?text={quote(text)}" if digits else None


VIN_CHECK_RATE_LIMIT = int(os.getenv("VIN_CHECK_RATE_LIMIT_PER_HOUR", "60"))


@public_router.post("/api/public/vin-check")
async def vin_check(body: VinCheckIn, request: Request) -> dict[str, Any]:
    """Darmowe sprawdzenie: czy TO auto ma zerowe cło i ile wyjdzie pod klucz.

    BEZ BRAMKI KONTAKTOWEJ — wynik wraca od razu, bez podawania telefonu. To jest
    świadoma decyzja i wynika z arytmetyki, nie z hojności: przy prowizji rzędu
    3-19 tys. zł nie opłaca się kupować masy leadów, opłaca się kilku właściwych.
    Otwarty checker filtruje przez samoselekcję — kto sam wróci po pełną kalkulację,
    jest wart czasu; kto sprawdził VIN z ciekawości, i tak by nie kupił, a jego
    numer telefonu byłby tylko szumem w skrzynce.

    Osobno: to jest jedyna liczba na rynku, która może być prawdziwa. Osiem publicznych
    kalkulatorów konkurencji pyta o cenę i pojemność, żaden o VIN — więc żaden nie wie,
    czy cło wynosi 0% czy 10%. W naszej próbce 175 z 307 aut było zmontowanych w USA,
    czyli mylą się na większości.

    Limit jest wyższy niż przy formularzu (60/h wobec 10/h), bo to narzędzie ma być
    używane — sprawdzenie kilkunastu lotów pod rząd to normalna praca kupującego,
    a nie nadużycie.
    """
    ip = _client_ip(request)
    now = time.time()
    okno = _hits[f"vin:{ip}"]
    while okno and now - okno[0] > RATE_LIMIT_WINDOW_S:
        okno.popleft()
    if len(okno) >= VIN_CHECK_RATE_LIMIT:
        raise HTTPException(429, "Za dużo zapytań. Proszę spróbować za chwilę.")
    okno.append(now)

    from parser.models import CarLot
    from pricing import fx
    from pricing.drivetrain import detect
    from pricing.tariff import rates_for_lot
    from pricing.vin import origin

    pochodzenie = origin(body.vin)
    if not pochodzenie.confident:
        raise HTTPException(
            422,
            "Nie rozpoznaję tego numeru VIN. Sprawdź, czy jest kompletny — "
            "do ustalenia cła wystarczy początek, ale musi być poprawny.",
        )

    lot = CarLot(
        source="vin-check",
        lot_id=body.vin[:11],
        url="",
        vin=body.vin,
        full_vin=body.vin,
        make=body.make,
        model=body.model,
        trim=body.trim,
        current_bid_usd=body.bid_usd,
        location_state=(body.state or "").upper() or None,
    )
    stawki = rates_for_lot(lot)
    naped = detect(body.make, body.model, body.trim)

    wynik: dict[str, Any] = {
        "vin": body.vin.upper()[:17],
        "assembly_country": stawki.country_name,
        "assembled_in_usa": pochodzenie.assembled_in_usa,
        "duty_rate_pct": round(stawki.duty_rate * 100, 1),
        "duty_free": stawki.duty_free,
        "duty_reason": stawki.duty_reason,
        "excise_rate_pct": round(stawki.excise_rate * 100, 2),
        "excise_reason": stawki.excise_reason,
        "drivetrain": stawki.drivetrain.value,
        "drivetrain_confident": naped.confident,
        "assumptions": stawki.assumptions,
        "usd_rate": round(fx.current_rate(), 4),
    }

    if body.bid_usd:
        from pricing.import_calculator import calculate_import_costs, client_price_pln, towing_for_location

        koszty = calculate_import_costs(
            bid_usd=body.bid_usd,
            towing_usd=towing_for_location(lot.location_state, None),
            usd_rate=fx.current_rate(),
            excise_rate=stawki.excise_rate,
            duty_rate=stawki.duty_rate,
        )
        cena = client_price_pln(koszty, settlement=body.settlement)
        # Ile klient zyskuje na tym, że sprawdziliśmy VIN. To jest cała pointa
        # narzędzia i jedyna liczba, którą warto zapamiętać.
        po_staremu = client_price_pln(
            calculate_import_costs(
                bid_usd=body.bid_usd,
                towing_usd=towing_for_location(lot.location_state, None),
                usd_rate=fx.current_rate(),
                excise_rate=stawki.excise_rate,
                duty_rate=0.10,
            ),
            settlement=body.settlement,
        )
        wynik["landed_pln"] = round(cena)
        wynik["landed_if_duty_10_pln"] = round(po_staremu)
        wynik["saving_pln"] = round(po_staremu - cena)

    logger.info("[vin-check] %s → cło %s%%", body.vin[:8], wynik["duty_rate_pct"])
    return wynik


# ─────────────────────────────────────────────────────── publiczny formularz


def _generate_draft_later(lead_id: int) -> None:
    """Propozycja pierwszej wiadomości, liczona po odpowiedzeniu formularzowi.

    Wywołanie modelu trwa kilkadziesiąt sekund. Trzymanie na nim otwartego żądania
    z landing page'a znaczyłoby, że klient patrzy na kręcące się kółko przez półtorej
    minuty i zamyka kartę, przekonany, że formularz nie działa. Lead jest już wtedy
    zapisany — brakuje tylko propozycji, a ta jest dla brokera, nie dla klienta.

    Błąd tu nie może wywrócić niczego: lead bez draftu i tak trafia do skrzynki,
    w sekcji „czeka na pierwszą wiadomość”.
    """
    try:
        from sales.agent import propose_reply

        lead = db.get_lead(lead_id)
        if lead is None:
            return
        draft = propose_reply(lead, db.messages(lead_id))
        if draft and draft.text:
            db.save_draft(draft)
    except Exception as exc:  # noqa: BLE001 — zadanie w tle nie ma komu zgłosić błędu
        logger.warning("[leads] nie udało się przygotować propozycji dla #%s: %s", lead_id, exc)


@public_router.post("/api/public/leads")
async def submit_lead(
    form: LeadForm, request: Request, background: BackgroundTasks
) -> dict[str, Any]:
    """Zgłoszenie z landing page'a.

    Odpowiedź jest celowo uboga: potwierdzenie i nic więcej. Zwrócenie oceny leada
    albo powodu odrzucenia dałoby każdemu z ulicy wgląd w to, jak kwalifikujemy
    klientów — i gotowy sposób na obejście tej kwalifikacji.
    """
    _rate_limit(request)

    if form.website:
        # Bot wypełnił pole-pułapkę. Odpowiadamy tak samo jak przy sukcesie, żeby nie
        # podpowiadać, że pułapka istnieje — i nie zapisujemy niczego.
        logger.info("[leads] odrzucone przez honeypot z %s", _client_ip(request))
        return {"ok": True}

    try:
        wynik = intake.submit(
            raw_request=form.message,
            name=form.name,
            phone=form.phone,
            email=form.email,
            referred_by=form.referred_by,
            channel=Channel.FORMULARZ,
            make_draft=False,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    background.add_task(_generate_draft_later, wynik.lead.id)

    logger.info(
        "[leads] nowe zgłoszenie #%s (%s) — %s",
        wynik.lead.id,
        "nowy" if wynik.is_new else "powrót",
        wynik.score.summary(),
    )
    return {"ok": True, "lead_id": wynik.lead.id}


# ───────────────────────────────────────────────────────────── skrzynka brokera


@router.get("/api/sales/inbox")
async def inbox() -> dict[str, Any]:
    """Wszystko, co czeka na zgodę brokera, razem z kontekstem leada.

    To jest jedyny ekran, który broker musi otworzyć rano.
    """
    from sales import gate as _gate
    from sales.gate import check as gate_check

    pozycje = []
    parking = []
    for draft in db.pending_drafts():
        lead = db.get_lead(draft.lead_id)
        if lead is None:
            continue
        score = score_lead(lead)
        werdykt = gate_check(lead, score)
        wpis = {
            **_draft_json(draft, lead),
            "score": _score_json(score),
            "wa_me": wa_me_link(lead.phone, draft.final_text),
            "search": _search_summary(lead.id),
        }
        # Sito rozdziela skrzynkę na dwie listy zamiast ukrywać cokolwiek. Lead odrzucony
        # nie znika — leży widocznie, z powodem i z warunkiem powrotu. Ukrywanie go
        # zamieniłoby filtr w cichą utratę klienta, a o to nie chodzi.
        if werdykt.passes:
            pozycje.append(wpis)
        else:
            parking.append({**wpis, "parked_reasons": werdykt.reasons, "unlock": werdykt.unlock})

    # Gorące leady na górze: broker ma zacząć od tych, którzy kupią.
    kolejnosc = {"A": 0, "B": 1, "C": 2, "D": 3}
    pozycje.sort(key=lambda p: (kolejnosc.get(p["score"]["segment"], 9), -p["score"]["score"]))

    # Druga sekcja: leady bez propozycji, na które ktoś czeka.
    #
    # Bez niej lead znika za każdym razem, gdy agent nie ma czego napisać — model
    # nie odpowiedział, reguła nie miała pytania, propozycja poleciała do kosza.
    # To jest awaria, która wygląda jak cisza i nie zgłasza się sama.
    #
    # „Czeka” znaczy: nigdy do niego nie napisaliśmy albo ostatnie słowo należy
    # do klienta. Lead, na którego wiadomość odpowiedzieliśmy, nie wymaga niczego.
    z_draftem = {p["lead_id"] for p in pozycje} | {p["lead_id"] for p in parking}
    czekaja = []
    for lead in db.list_leads(only_open=True):
        if lead.id in z_draftem:
            continue
        historia = db.messages(lead.id)
        odpisalismy = any(m.author is Author.BROKER for m in historia)
        ostatnie_od_klienta = bool(historia) and historia[-1].author is Author.KLIENT
        if odpisalismy and not ostatnie_od_klienta:
            continue
        score = score_lead(lead)
        werdykt = gate_check(lead, score)
        if not werdykt.passes:
            parking.append(
                {
                    # `lead_id` obok `id`, żeby obie ścieżki parkingu — ta z draftem
                    # i ta bez — miały ten sam kształt. Front nie ma się domyślać,
                    # z której gałęzi przyszedł wpis.
                    "lead_id": lead.id,
                    "text": "",
                    "lead": _lead_json(lead),
                    **_lead_json(lead),
                    "score": _score_json(score),
                    "parked_reasons": werdykt.reasons,
                    "unlock": werdykt.unlock,
                }
            )
            continue
        czekaja.append(
            {
                **_lead_json(lead),
                "score": _score_json(score),
                "waiting_since": (
                    historia[-1].created_at.isoformat() if historia and historia[-1].created_at else None
                ),
                "last_client_message": historia[-1].text if ostatnie_od_klienta else None,
            }
        )
    czekaja.sort(key=lambda p: (kolejnosc.get(p["score"]["segment"], 9), -p["score"]["score"]))

    parking.sort(key=lambda p: -p["score"]["score"])
    return {
        "count": len(pozycje),
        "items": pozycje,
        "needs_attention": czekaja,
        # Odrzuceni przez sito — widoczni, z powodem i warunkiem powrotu.
        "parked": parking,
        "gate": {
            "min_budget_pln": _gate.MIN_BUDGET_PLN,
            "min_score": _gate.MIN_SCORE,
        },
    }


@router.get("/api/sales/leads")
async def list_leads(only_open: bool = True) -> dict[str, Any]:
    """Lista leadów z ocenami — do widoku listy w panelu."""
    pozycje = []
    for lead in db.list_leads(only_open=only_open):
        score = score_lead(lead)
        pozycje.append({**_lead_json(lead), "score": _score_json(score)})

    kolejnosc = {"A": 0, "B": 1, "C": 2, "D": 3}
    pozycje.sort(key=lambda p: (kolejnosc.get(p["score"]["segment"], 9), -p["score"]["score"]))
    return {"count": len(pozycje), "items": pozycje}


@router.get("/api/sales/leads/{lead_id}")
async def lead_detail(lead_id: int) -> dict[str, Any]:
    lead = db.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, f"nie ma leada {lead_id}")

    return {
        **_lead_json(lead),
        "score": _score_json(score_lead(lead)),
        "messages": [
            {
                "id": m.id,
                "author": m.author.value,
                "text": m.text,
                "channel": m.channel.value if m.channel else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
            }
            for m in db.messages(lead_id)
        ],
        "pending_drafts": [
            _draft_json(d) for d in db.pending_drafts() if d.lead_id == lead_id
        ],
        "search": _search_summary(lead_id),
    }


def _search_summary(lead_id: int) -> dict[str, Any]:
    """Stan wyszukiwania przy leadzie — bez samych lotów.

    Loty potrafią mieć po kilkadziesiąt pól i listę zdjęć; wpakowanie ich tutaj
    robiłoby z karty leada odpowiedź na kilkaset kilobajtów. Pełną listę wydaje
    `GET /api/sales/leads/{id}/candidates`, wołane dopiero po kliknięciu.
    """
    wyszukiwanie = db.latest_lead_search(lead_id)
    if wyszukiwanie is None:
        return {"status": "brak", "candidate_count": 0, "offer_ready": False}
    # `candidate_count`, nie `candidates` — endpoint szczegółowy zwraca pod tą nazwą
    # TABLICĘ lotów. Ta sama nazwa dla liczby i dla listy to pułapka, na której front
    # wywala się dopiero w runtime.
    return {
        "status": wyszukiwanie["status"],
        "candidate_count": len(wyszukiwanie["candidates"]),
        "error": wyszukiwanie["error"],
        "finished_at": wyszukiwanie["finished_at"],
        "offer_ready": wyszukiwanie["status"] == "done" and bool(wyszukiwanie["candidates"]),
    }


@router.post("/api/sales/leads/{lead_id}/reply")
async def record_reply(lead_id: int, body: ReplyIn) -> dict[str, Any]:
    """Broker wkleja to, co klient odpisał. Agent proponuje odpowiedź.

    Przy pełnej integracji z komunikatorem wejdzie tu webhook — reszta łańcucha
    zostaje bez zmian.
    """
    try:
        wynik = intake.record_client_reply(lead_id, body.text, channel=body.channel)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    return {
        "lead": _lead_json(wynik.lead),
        "score": _score_json(wynik.score),
        "draft": _draft_json(wynik.draft) if wynik.draft else None,
    }


@router.post("/api/sales/leads/{lead_id}/search")
async def start_lead_search(lead_id: int, background: BackgroundTasks) -> dict[str, Any]:
    """Uruchamia wyszukiwanie z kryteriów leada — bez przepisywania czegokolwiek.

    Do tej pory to był jedyny krok, którego agent nie robił: marka, model, rocznik
    i budżet leżały w bazie, a broker i tak wpisywał je ręcznie w formularzu na
    stronie głównej. Etap `SZUKANIE` istniał w modelu i nic go nie wypełniało.

    Scrape trwa minuty, więc leci w tle, a endpoint wraca od razu ze statusem.
    Postęp i wynik czyta się przez `GET /api/sales/leads/{id}/candidates`.
    """
    from sales.search import readiness

    lead = db.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, f"nie ma leada {lead_id}")

    gotowosc = readiness(lead)
    if not gotowosc.ready:
        raise HTTPException(422, f"Nie da się szukać — {gotowosc.reason()}.")

    # Drugi scrape dla tego samego leada tylko zajmuje kolejkę i daje ten sam wynik.
    if db.running_search(lead_id):
        raise HTTPException(409, "Dla tego leada wyszukiwanie już trwa.")

    background.add_task(_run_lead_search, lead_id)
    return {
        "started": True,
        "lead_id": lead_id,
        "warnings": gotowosc.notes(),
    }


def _run_lead_search(lead_id: int) -> None:
    """Zadanie w tle. Wyjątek zapisuje `sales/search.py`, tu go tylko logujemy."""
    import asyncio

    from sales.search import run_search_for_lead

    try:
        asyncio.run(run_search_for_lead(lead_id))
    except Exception as exc:  # noqa: BLE001 — zadanie w tle nie ma komu zgłosić błędu
        logger.warning("[sales] wyszukiwanie dla leada #%s nie doszło do skutku: %s", lead_id, exc)


@router.get("/api/sales/leads/{lead_id}/candidates")
async def lead_candidates(lead_id: int) -> dict[str, Any]:
    """Auta znalezione dla leada — to, z czego broker wybiera do oferty.

    Zwraca też `offer_ready`: czy jest już z czego składać ofertę. Bez tego panel
    musiałby sam interpretować status i pustą listę, a to są dwie różne sytuacje
    („jeszcze szukamy" i „nic nie znaleźliśmy").
    """
    if db.get_lead(lead_id) is None:
        raise HTTPException(404, f"nie ma leada {lead_id}")

    wyszukiwanie = db.latest_lead_search(lead_id)
    if wyszukiwanie is None:
        return {"status": "brak", "candidates": [], "offer_ready": False}

    return {
        "status": wyszukiwanie["status"],
        "job_id": wyszukiwanie["job_id"],
        "criteria": wyszukiwanie["criteria"],
        "candidates": wyszukiwanie["candidates"],
        "error": wyszukiwanie["error"],
        "created_at": wyszukiwanie["created_at"],
        "finished_at": wyszukiwanie["finished_at"],
        "offer_ready": wyszukiwanie["status"] == "done" and bool(wyszukiwanie["candidates"]),
    }


@router.post("/api/sales/leads/{lead_id}/regenerate")
async def regenerate(lead_id: int) -> dict[str, Any]:
    """Nowa propozycja dla leada — gdy broker odrzucił poprzednią."""
    from sales.agent import propose_reply

    lead = db.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, f"nie ma leada {lead_id}")

    draft = propose_reply(lead, db.messages(lead_id))
    if draft is None or not draft.text:
        powod = draft.rationale if draft else "agent nie ma nic do napisania na tym etapie"
        return {"draft": None, "reason": powod}

    return {"draft": _draft_json(db.save_draft(draft))}


class OfferIn(BaseModel):
    """Auta wybrane przez brokera do zaproponowania klientowi."""

    lots: list[dict] = Field(default_factory=list, max_length=10)


@router.post("/api/sales/leads/{lead_id}/offer")
async def propose_offer(lead_id: int, payload: OfferIn) -> dict[str, Any]:
    """Propozycja wiadomości, która ZNA auta wybrane przez brokera.

    Do tej pory na etapie „oferta" agent pisał ogólniki, bo żaden endpoint nie
    przekazywał mu `offers` — miał pole na auta i nigdy nic w nim nie dostawał.

    Auta wybiera człowiek. Kolejności nie zmieniamy: broker zaznaczył je w takiej,
    a przestawianie ich znaczyłoby, że klient dostaje inną propozycję niż ta,
    którą broker zatwierdził.
    """
    from parser.models import CarLot
    from sales.agent import propose_reply
    from sales.offers import offers_from_lots

    lead = db.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, f"nie ma leada {lead_id}")

    lots: list[CarLot] = []
    for raw in payload.lots:
        try:
            lots.append(CarLot(**raw))
        except Exception:
            logger.debug("[leads] pomijam lot o nieprawidłowym kształcie", exc_info=True)

    offers = offers_from_lots(
        lots, budget_pln=lead.budget_pln, settlement=lead.settlement
    )
    if not offers:
        raise HTTPException(
            422,
            "Żadnego z tych aut nie da się wycenić — bez ceny pod klucz nie ma czego proponować.",
        )

    draft = propose_reply(lead, db.messages(lead_id), offers=offers)
    if draft is None or not draft.text:
        powod = draft.rationale if draft else "agent nie ma nic do napisania na tym etapie"
        return {"draft": None, "reason": powod, "offers": offers}

    return {"draft": _draft_json(db.save_draft(draft)), "offers": offers}


@router.post("/api/sales/drafts/{draft_id}/approve")
async def approve(draft_id: int, body: ApproveIn) -> dict[str, Any]:
    """ZGODA BROKERA. Zapisuje wiadomość i zwraca link do wysłania.

    Nic nie wychodzi z serwera do klienta — treść trafia do WhatsAppa dopiero, gdy
    broker otworzy zwrócony link ze swojego telefonu.
    """
    draft = db.get_draft(draft_id)
    if draft is None:
        raise HTTPException(404, f"nie ma draftu {draft_id}")

    wiadomosc = db.approve_and_send(draft_id, edited_text=body.edited_text)
    if wiadomosc is None:
        raise HTTPException(409, "ten draft został już zatwierdzony albo odrzucony")

    lead = db.get_lead(draft.lead_id)
    return {
        "sent": True,
        "text": wiadomosc.text,
        "channel": wiadomosc.channel.value if wiadomosc.channel else None,
        "wa_me": wa_me_link(lead.phone if lead else None, wiadomosc.text),
        "mailto": (
            f"mailto:{lead.email}?body={quote(wiadomosc.text)}"
            if lead and lead.email and wiadomosc.channel is Channel.EMAIL
            else None
        ),
        "lead": _lead_json(lead) if lead else None,
    }


@router.post("/api/sales/drafts/{draft_id}/reject")
async def reject(draft_id: int, body: RejectIn) -> dict[str, Any]:
    if not db.reject_draft(draft_id, reason=body.reason):
        raise HTTPException(409, "ten draft został już zatwierdzony albo odrzucony")
    return {"rejected": True}


@router.patch("/api/sales/leads/{lead_id}")
async def patch_lead(lead_id: int, payload: LeadPatch) -> dict[str, Any]:
    """Poprawka danych leada — to, co broker robi po telefonie z klientem.

    Do tej pory jedynym zapisem z panelu była zmiana etapu, więc budżetu podanego
    przez telefon nie dało się nigdzie wpisać. Bez budżetu nie ma sufitu ceny
    aukcyjnej, a bez sufitu żaden lot nie dostaje werdyktu PONAD BUDŻET i cała ta
    mechanika stoi bezużyteczna.

    Zmieniamy WYŁĄCZNIE pola, które przyszły w żądaniu (`exclude_unset`). Pominięte
    zostają nietknięte, a jawne `null` kasuje wartość — to są dwie różne intencje
    i przy `damage_ok` różnica jest znacząca.

    Ocena wraca przeliczona, bo `LeadScore` nie jest trzymany w bazie: liczy się na
    żądanie z aktualnych pól. Zwrócenie samego leada zostawiłoby panel z nowym
    budżetem obok starego segmentu.
    """
    from sales.gate import check as gate_check
    from sales.intake import _normalize_phone

    lead = db.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, f"nie ma leada {lead_id}")

    zmiany = payload.model_dump(exclude_unset=True)
    if not zmiany:
        raise HTTPException(400, "Puste żądanie — nie ma czego zmieniać.")

    if "phone" in zmiany:
        zmiany["phone"] = _normalize_phone(zmiany["phone"])
    if "email" in zmiany and zmiany["email"]:
        zmiany["email"] = zmiany["email"].strip() or None

    # Dwa leady pod tym samym numerem rozbijają deduplikację: kolejne zgłoszenie
    # od tego klienta trafi w jeden z nich, a rozmowa toczy się w drugim.
    for pole in ("phone", "email"):
        nowa = zmiany.get(pole)
        if not nowa or nowa == getattr(lead, pole):
            continue
        kolizja = db.find_lead_by_contact(**{pole: nowa})
        if kolizja is not None and kolizja.id != lead_id:
            raise HTTPException(
                409,
                f"Ten {'numer' if pole == 'phone' else 'adres'} należy już do leada "
                f"#{kolizja.id} ({kolizja.display_name()}). Scal je zamiast duplikować.",
            )

    for pole, wartosc in zmiany.items():
        setattr(lead, pole, wartosc)
    db.update_lead(lead)

    lead = db.get_lead(lead_id) or lead
    score = score_lead(lead)
    werdykt = gate_check(lead, score)
    logger.info("[leads] #%s zmienione: %s → %s", lead_id, ", ".join(zmiany), score.summary())

    return {
        "lead": _lead_json(lead),
        "score": _score_json(score),
        # Dodatkowo, bo edycja budżetu robi się zwykle właśnie po to, żeby lead
        # wyszedł z parkingu — panel od razu widzi, czy się udało.
        "gate": {"passes": werdykt.passes, "reasons": werdykt.reasons, "unlock": werdykt.unlock},
        "changed": sorted(zmiany),
    }


@router.post("/api/sales/leads/{lead_id}/promote")
async def promote_lead(lead_id: int) -> dict[str, Any]:
    """Awansuje leada na klienta w bazie klientów — ostatnie ogniwo lejka.

    `Lead.client_id` istniał w modelu od początku i nic go nigdy nie zapisywało,
    więc wygrana sprzedaż nie zostawiała śladu: `api/client_database.py` i `sales/`
    żyły obok siebie jako dwa niepołączone zbiory.

    AWANS JEST OSOBNĄ, JAWNĄ AKCJĄ. Nie robimy go automatycznie przy przejściu na
    etap `wygrana`: pierwsze pomyłkowe kliknięcie w select etapu zakładałoby wtedy
    klienta, którego nikt nie chciał, a kartotek klientów się nie kasuje odruchowo.

    IDEMPOTENTNE. Drugie wywołanie zwraca tego samego klienta i `created: false` —
    ten sam wzorzec, co `approve_and_send`, bo panel bywa klikany dwa razy.
    """
    from api import client_database

    lead = db.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, f"nie ma leada {lead_id}")

    if lead.client_id:
        return {
            "lead": _lead_json(lead),
            "client_id": lead.client_id,
            "created": False,
            "linked": False,
            "message": "Ten lead jest już powiązany z klientem.",
        }

    if not lead.contactable:
        raise HTTPException(
            422,
            "Bez telefonu i maila nie ma czego zapisać w bazie klientów — "
            "kartoteka bez kontaktu jest bezużyteczna.",
        )

    # Sprawdzamy PRZED zapisem, żeby wiedzieć, czy klient powstał, czy się podpiął.
    # `upsert_client` zwraca id w obu przypadkach i sam tej różnicy nie zdradza,
    # a brokerowi ona robi różnicę.
    istniejacy = client_database.find_client_by_contact(email=lead.email, phone=lead.phone)

    client_id = client_database.upsert_client(
        {
            "name": lead.name,
            "email": lead.email,
            "phone": lead.phone,
            # Notatki leada niosą to, czego nie ma w polach: czego klient szuka
            # i co ustalono w rozmowie. Zgubienie ich przy awansie znaczyłoby,
            # że kartoteka klienta zaczyna się od pustej strony.
            "notes": lead.notes or lead.raw_request or None,
        }
    )
    if client_id is None:
        raise HTTPException(500, "Nie udało się zapisać klienta.")

    lead.client_id = client_id
    db.update_lead(lead)
    lead = db.get_lead(lead_id) or lead

    podpiety = istniejacy is not None
    logger.info(
        "[leads] #%s → klient #%s (%s)",
        lead_id,
        client_id,
        "podpięty do istniejącego" if podpiety else "nowy",
    )
    return {
        "lead": _lead_json(lead),
        "client_id": client_id,
        "created": not podpiety,
        "linked": podpiety,
        "message": (
            f"Podpięto do istniejącego klienta #{client_id}."
            if podpiety
            else f"Założono klienta #{client_id}."
        ),
    }


@router.put("/api/sales/leads/{lead_id}/stage")
async def set_stage(lead_id: int, body: StageIn) -> dict[str, Any]:
    lead = db.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, f"nie ma leada {lead_id}")
    lead.stage = body.stage
    db.update_lead(lead)
    return {"lead": _lead_json(db.get_lead(lead_id))}
