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
from pydantic import BaseModel, Field

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


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=2_000)
    channel: Channel = Channel.WHATSAPP


class ApproveIn(BaseModel):
    edited_text: Optional[str] = Field(default=None, max_length=2_000)


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class StageIn(BaseModel):
    stage: Stage


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
        "settlement": lead.settlement,
        "timeline_days": lead.timeline_days,
        "damage_ok": lead.damage_ok,
        "bought_before": lead.bought_before,
        "referred_by": lead.referred_by,
        "notes": lead.notes,
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
    pozycje = []
    for draft in db.pending_drafts():
        lead = db.get_lead(draft.lead_id)
        if lead is None:
            continue
        score = score_lead(lead)
        pozycje.append(
            {
                **_draft_json(draft, lead),
                "score": _score_json(score),
                "wa_me": wa_me_link(lead.phone, draft.final_text),
            }
        )

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
    z_draftem = {p["lead_id"] for p in pozycje}
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

    return {
        "count": len(pozycje),
        "items": pozycje,
        "needs_attention": czekaja,
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


@router.put("/api/sales/leads/{lead_id}/stage")
async def set_stage(lead_id: int, body: StageIn) -> dict[str, Any]:
    lead = db.get_lead(lead_id)
    if lead is None:
        raise HTTPException(404, f"nie ma leada {lead_id}")
    lead.stage = body.stage
    db.update_lead(lead)
    return {"lead": _lead_json(db.get_lead(lead_id))}
