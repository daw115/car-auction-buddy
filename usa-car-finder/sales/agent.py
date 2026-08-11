"""
Agent piszący propozycje wiadomości do klienta.

NIC STĄD NIE WYCHODZI DO KLIENTA. Funkcja `propose_reply` zwraca `Draft`, który ląduje
w skrzynce brokera. Dopiero `sales/db.approve_and_send` — czyli kliknięcie człowieka —
zamienia go w wiadomość. Ten podział jest wymaganiem produktu, a nie ostrożnością
techniczną: wiadomość idzie do klienta z telefonu brokera i pod jego nazwiskiem.

PODZIAŁ PRACY, TAKI SAM JAK W `report/offer_agent.py`

  Python liczy       — ocenę leada, ceny, stawki podatkowe, sufit budżetu.
  Model pisze zdania — i tylko zdania.
  Walidator odrzuca  — wszystko, co łamie zasady z `agent-sprzedaz-usa.md`.

Odrzucamy zamiast poprawiać. Zdanie z cyfrą to liczba, której nikt nie policzył;
przepisywanie go w locie znaczyłoby, że nie wiemy, która wersja jest prawdziwa.

PROMPT SYSTEMOWY MUSI BYĆ STAŁY CO DO BAJTU. Idzie przez `--system-prompt`, więc jego
prefiks wpada do cache'u promptów i kolejne wywołania są wielokrotnie tańsze
(`ai/claude_code.py` opisuje pomiary). Dlatego wszystko zmienne — dane leada, fakty
rynkowe, historia rozmowy — wchodzi wiadomością użytkownika, a nie do promptu.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from sales.models import Author, Channel, Draft, Lead, LeadScore, Message, Stage
from sales.playbook import STAGE_GOALS, facts_text, objection_hints, objections_text
from sales.qualification import score_lead

logger = logging.getLogger("sales.agent")

# Listy zakazanych zwrotów są wspólne z ofertą. Klient nie może zobaczyć słowa "salvage"
# w mailu i nie może go zobaczyć na WhatsAppie — dwie kopie tej listy rozjechałyby się
# przy pierwszej zmianie i jeden z kanałów przestałby chronić.
from report.offer_agent import BANNED_FRAGMENTS, JARGON_FRAGMENTS

PROMPT_PATH = Path(__file__).resolve().parents[2] / "agent-sprzedaz-usa.md"

MAX_MESSAGE_CHARS = 480
MAX_SENTENCES = 4
HISTORY_LIMIT = 12

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_SENTENCE = re.compile(r"[.!?]+(?:\s|$)")

# Zwroty zakazane wyłącznie w rozmowie. Oferta ich nie potrzebuje, bo tam nikt nie pyta
# o zaliczkę — a w rozmowie to jest najczęstsze pytanie, na które agent nie ma prawa
# odpowiedzieć. Warunki płatności ustala broker i tylko broker.
#
# DOPASOWANIE PO RDZENIU, NIE PO CAŁYM ZWROCIE. Lista zapisana jako gotowe frazy
# przepuściła wiadomość ze słowami „numeru konta”, bo zakaz brzmiał „numer konta”.
# Polska odmiana odmienia każde z tych słów, a zakaz, który omija odmiana, nie jest
# zakazem. Rdzenie dopasowujemy z granicą słowa od lewej, żeby „kont” nie trafiało
# w „kontakt” ani w „kontrolę”.
_CONVERSATION_STEMS = (
    r"zaliczk\w*",
    r"przedpłat\w*|przedplat\w*",
    r"kont[aoue]\b|kontem\b",          # konto, konta, koncie — ale nie kontakt
    r"przelej\w*|przelew\w*",
    r"wpłat\w*|wplat\w*|wpłac\w*|wplac\w*",
    r"rabat\w*",
    r"upust\w*",
    r"obniż\w*|obniz\w*",
    r"gwarantuj\w*",
    r"na pewno (wygramy|kupimy|uda)",
)
_BANNED_IN_CONVERSATION = re.compile(
    r"\b(?:" + "|".join(_CONVERSATION_STEMS) + r")", re.IGNORECASE
)


class PromptMissing(RuntimeError):
    """Brak pliku promptu — agent nie ma na czym pracować."""


def model_enabled() -> bool:
    """Czy wolno wołać model.

    Wyłącznik istnieje z dwóch powodów. W testach i CI wywołanie modelu byłoby
    zależnością od sieci i od zalogowanej sesji, a przy okazji kosztem. W produkcji
    daje brokerowi sposób na zejście na wariant regułowy, gdy model zaczyna pisać
    rzeczy, których nie chce wysyłać — bez czekania na wdrożenie poprawki.

    Zadanie jest krótkie (cztery zdania), więc domyślnie idzie na niskim wysiłku:
    pomiar na pierwszym wywołaniu dał 6 400 tokenów wyjścia i 85 sekund na coś,
    co ma zmieścić się w czterech zdaniach. `SALES_AGENT_EFFORT` to podnosi.
    """
    return os.getenv("SALES_AGENT_MODEL_ENABLED", "true").lower() in ("1", "true", "yes")


def system_prompt() -> str:
    """Prompt systemowy z pliku. Ładowany za każdym razem, ale bajt w bajt ten sam."""
    if not PROMPT_PATH.exists():
        raise PromptMissing(f"brak promptu: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────── wiadomość użytkownika


def _lead_block(lead: Lead, score: LeadScore) -> str:
    znane = {
        "imię": lead.name,
        "marka": lead.make,
        "model": lead.model,
        "rocznik od": lead.year_from,
        "rocznik do": lead.year_to,
        "budżet pod klucz (PLN)": f"{lead.budget_pln:,.0f}".replace(",", " ") if lead.budget_pln else None,
        "forma rozliczenia": "firma" if lead.settlement == "company" else "osoba prywatna",
        "max przebieg (mile)": lead.max_odometer_mi,
        "na kiedy (dni)": lead.timeline_days,
        "godzi się na auto po szkodzie": (
            "nie pytaliśmy" if lead.damage_ok is None else ("tak" if lead.damage_ok else "NIE")
        ),
        "kupował u nas wcześniej": "tak" if lead.bought_before else "nie",
        "polecony przez": lead.referred_by,
    }
    linie = [f"- {k}: {v}" for k, v in znane.items() if v not in (None, "")]
    return "\n".join(linie)


def _history_block(history: list[Message]) -> str:
    if not history:
        return "(brak — to pierwsza wiadomość w tej rozmowie)"
    kto = {Author.KLIENT: "KLIENT", Author.BROKER: "MY", Author.AGENT: "MY (propozycja)"}
    return "\n".join(f"{kto[m.author]}: {m.text}" for m in history[-HISTORY_LIMIT:])


def _offers_block(offers: Optional[list[dict[str, Any]]]) -> str:
    """Auta w ofercie — z cenami policzonymi w Pythonie.

    Ceny podajemy modelowi gotowe i oznaczone jako nietykalne, bo to jedyne liczby,
    które wolno mu powtórzyć. Bez tego bloku agent nie ma o czym rozmawiać na etapie
    oferty; z nim — nie ma powodu, żeby cokolwiek przeliczać.
    """
    if not offers:
        return "(brak — nie wysłaliśmy jeszcze żadnych aut)"
    linie = []
    for o in offers:
        cena = f"{o['cena_pln']:,.0f}".replace(",", " ")
        linia = f"- {o.get('nazwa', 'auto')} — {cena} zł pod klucz"
        if o.get("ponad_budzet"):
            linia += " (powyżej budżetu)"
        if o.get("uszkodzenie"):
            linia += f", uszkodzenie: {o['uszkodzenie']}"
        linie.append(linia)
    return "\n".join(linie)


def build_user_message(
    lead: Lead,
    score: LeadScore,
    history: list[Message],
    *,
    offers: Optional[list[dict[str, Any]]] = None,
) -> str:
    """Komplet danych dla modelu. Zmienne — nigdy do promptu systemowego."""
    ostatnia_od_klienta = next(
        (m.text for m in reversed(history) if m.author is Author.KLIENT), ""
    )
    hits = objection_hints(ostatnia_od_klienta)

    return f"""# LEAD

{_lead_block(lead, score)}

# OCENA (policzona, nie do zakwestionowania)

- wynik: {score.score:.0f}/100
- segment: {score.segment.value} ({score.segment.label})
- czego nie wiemy: {", ".join(score.missing) if score.missing else "nic — komplet danych"}
- co robić dalej: {score.next_action}

## Czerwone flagi
{chr(10).join(f"- {f}" for f in score.red_flags) if score.red_flags else "- brak"}

# ETAP: {lead.stage.value}

Cel tej wiadomości: {STAGE_GOALS[lead.stage]}

# HISTORIA ROZMOWY

{_history_block(history)}

# AUTA W OFERCIE (ceny policzone — możesz je powtórzyć, nie wolno ich zmieniać)

{_offers_block(offers)}

# OBIEKCJE, KTÓRE MOGĄ SIEDZIEĆ W OSTATNIEJ WIADOMOŚCI KLIENTA

{objections_text(hits) if hits else "(nie wykryto — nie odpowiadaj na obiekcję, której klient nie zgłosił)"}

# FAKTY RYNKOWE, NA KTÓRYCH MOŻESZ SIĘ OPRZEĆ

{facts_text()}

---
Napisz propozycję JEDNEJ wiadomości. Zwróć wyłącznie JSON zgodny z kontraktem."""


# ────────────────────────────────────────────────────────────────── walidacja


def validate_message(text: Any) -> Optional[str]:
    """Treść wiadomości albo None, gdy łamie zasady.

    Cyfry są tu DOZWOLONE, inaczej niż w prozie oferty. Powód: agent powtarza kwotę,
    którą policzył Python i którą dostał w bloku ofert — zakaz cyfr uniemożliwiłby
    rozmowę o cenie. Ryzyko przenosimy więc gdzie indziej: cena, której nie ma
    w danych, jest wychwytywana przez `mentions_unknown_amount`.
    """
    if not isinstance(text, str):
        return None
    cleaned = _WS.sub(" ", _TAGS.sub(" ", text)).strip().strip('"')
    if not cleaned:
        return None
    if len(cleaned) > MAX_MESSAGE_CHARS:
        return None
    if _EMOJI.search(cleaned) or "!" in cleaned:
        return None
    if len(_SENTENCE.findall(cleaned)) > MAX_SENTENCES:
        return None

    lowered = cleaned.lower()
    for bad in (*BANNED_FRAGMENTS, *JARGON_FRAGMENTS):
        if bad in lowered:
            logger.info("odrzucam propozycję — zakazany zwrot %r", bad)
            return None

    trafienie = _BANNED_IN_CONVERSATION.search(lowered)
    if trafienie:
        logger.info("odrzucam propozycję — ustalenia finansowe: %r", trafienie.group(0))
        return None
    return cleaned


_AMOUNT = re.compile(r"\d[\d\s .,]*\s*(?:zł|pln|tys)", re.IGNORECASE)


def mentions_unknown_amount(
    text: str,
    offers: Optional[list[dict[str, Any]]],
    *,
    budget_pln: Optional[float] = None,
) -> bool:
    """Czy w treści jest kwota, której nie policzyliśmy.

    Model dostaje ceny gotowe i wolno mu je powtórzyć. Kwota, której nie ma wśród
    podanych, znaczy, że coś przeliczył sam — a wtedy klient dostanie liczbę, której
    nikt nie potwierdzi, i to ona będzie tą, o którą się upomni.

    BUDŻET KLIENTA JEST KWOTĄ ZNANĄ. Podał go sam i agent musi móc się do niego odnieść
    („szukam w Pana budżecie”, „przy stu dwudziestu tysiącach…”). Bez tego wyjątku
    walidator wycinał każdą sensowną odpowiedź na obiekcję cenową i agent milczał
    dokładnie wtedy, kiedy najbardziej powinien się odezwać.

    Uznajemy też zapis skrócony: „120 tys.” to ta sama kwota co „120 000”, a klient
    czyta ją łatwiej.
    """
    if not _AMOUNT.search(text):
        return False

    dozwolone = {
        re.sub(r"\D", "", f"{o['cena_pln']:.0f}") for o in (offers or []) if o.get("cena_pln")
    }
    if budget_pln:
        pelna = f"{budget_pln:.0f}"
        dozwolone.add(pelna)
        if budget_pln >= 1000 and budget_pln % 1000 == 0:
            dozwolone.add(f"{budget_pln / 1000:.0f}")  # "120" z "120 tys."

    for fragment in _AMOUNT.finditer(text):
        cyfry = re.sub(r"\D", "", fragment.group(0))
        if cyfry and cyfry not in dozwolone:
            return True
    return False


# ─────────────────────────────────────────────────────────────── propozycja


def propose_reply(
    lead: Lead,
    history: Optional[list[Message]] = None,
    *,
    offers: Optional[list[dict[str, Any]]] = None,
    score: Optional[LeadScore] = None,
) -> Optional[Draft]:
    """Propozycja następnej wiadomości. None, gdy nie ma czego pisać.

    Draft nie jest zapisywany — robi to wywołujący przez `sales/db.save_draft`.
    Rozdzielenie jest celowe: propozycję da się wygenerować na próbę, bez śmiecenia
    w skrzynce brokera.
    """
    history = history or []
    score = score or score_lead(lead)

    if lead.stage is Stage.STRACONY:
        return None
    if not lead.contactable:
        return Draft(
            lead_id=lead.id or 0,
            text="",
            channel=_channel_for(lead),
            rationale="Brak telefonu i maila — nie ma dokąd wysłać. Uzupełnij kontakt.",
        )

    surowa = _ask_model(lead, score, history, offers)
    if surowa is None:
        return _fallback_draft(lead, score)

    # Rozróżniamy dwie różne rzeczy, które kończą się brakiem treści:
    #  * model ŚWIADOMIE nie pisze (zwrócił pusty `message`) — to poprawna odpowiedź,
    #  * walidator ODRZUCIŁ to, co napisał — to nasz problem, nie decyzja agenta.
    # Sklejenie ich w jedno dawało brokerowi notatkę „agent celowo nie pisze” pod
    # wiadomością, którą agent napisał i którą myśmy wycięli. Diagnoza była wtedy
    # dokładnie odwrotna od prawdy.
    napisany = str(surowa.get("message") or "").strip()
    tresc = validate_message(napisany) if napisany else None
    odrzucony = bool(napisany) and not tresc

    if tresc and mentions_unknown_amount(tresc, offers, budget_pln=lead.budget_pln):
        logger.info("odrzucam propozycję — kwota spoza danych")
        tresc, odrzucony = None, True

    notatka_brokera = str(surowa.get("broker_note") or "").strip()

    # Pusta wiadomość Z NOTATKĄ to świadoma odmowa pisania, przewidziana w prompcie:
    # pytanie o warunki płatności, sprawa zamknięta, brak kontaktu.
    if not tresc and not odrzucony and notatka_brokera:
        return Draft(
            lead_id=lead.id or 0,
            text="",
            channel=_channel_for(lead),
            rationale=f"Agent celowo nie pisze. {notatka_brokera}",
        )

    if not tresc:
        zapasowy = _fallback_draft(lead, score, history)
        if zapasowy and odrzucony:
            zapasowy.rationale = (
                f"{zapasowy.rationale} UWAGA: propozycję modelu odrzucił walidator "
                f"(złamane zasady treści), to jest wersja regułowa."
            )
        return zapasowy

    uzasadnienie = str(surowa.get("rationale") or "").strip()
    if notatka_brokera:
        uzasadnienie = f"{uzasadnienie}\n\nDla brokera: {notatka_brokera}".strip()

    return Draft(
        lead_id=lead.id or 0,
        text=tresc,
        channel=_channel_for(lead),
        rationale=uzasadnienie or score.next_action,
        stage_after=_stage_after(lead),
    )


def _channel_for(lead: Lead) -> Channel:
    """Czym odpisać. Telefon wygrywa z mailem — na komunikatorze klient odpowiada."""
    if lead.phone:
        return Channel.WHATSAPP
    if lead.email:
        return Channel.EMAIL
    return lead.channel


def _stage_after(lead: Lead) -> Optional[Stage]:
    """Etap po wysłaniu. Zmieniamy tylko tam, gdzie wysyłka faktycznie coś przesuwa."""
    if lead.stage is Stage.NOWY:
        return Stage.KWALIFIKACJA
    return None


def _ask_model(
    lead: Lead,
    score: LeadScore,
    history: list[Message],
    offers: Optional[list[dict[str, Any]]],
) -> Optional[dict]:
    """Wywołanie modelu. None przy każdym problemie — wtedy wchodzi wariant zapasowy."""
    if not model_enabled():
        return None

    try:
        from ai import claude_code
    except ImportError:
        return None

    if not claude_code.is_available():
        logger.info("Claude Code niedostępny — propozycja z wariantu zapasowego")
        return None

    try:
        answer = claude_code.call_json(
            system_prompt(),
            build_user_message(lead, score, history, offers=offers),
            model_env="CLAUDE_CODE_SALES_MODEL",
            effort=os.getenv("SALES_AGENT_EFFORT", "low"),
            label="sales-reply",
        )
    except Exception as exc:  # noqa: BLE001 — każdy błąd ma kończyć się wariantem zapasowym
        # Wygasła sesja, brak promptu, timeout, niepoprawny JSON — z punktu widzenia
        # skrzynki brokera to jeden przypadek: propozycji od modelu nie ma. Rozróżnianie
        # ich tutaj nic nie zmienia, a pusta skrzynka zmienia wszystko.
        logger.warning("model nie odpowiedział (%s) — wariant zapasowy", exc)
        return None

    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except json.JSONDecodeError:
            return None
    return answer if isinstance(answer, dict) else None


# ────────────────────────────────────────────────────────── wariant zapasowy


def _fallback_draft(
    lead: Lead,
    score: LeadScore,
    history: Optional[list[Message]] = None,
) -> Optional[Draft]:
    """Propozycja bez modelu — złożona z reguł.

    Potrzebna z dwóch powodów. Po pierwsze, sesja Claude Code czasem wygasa i skrzynka
    brokera nie może wtedy zostać pusta. Po drugie, to jest miara sensowności: jeśli
    wariant regułowy wystarcza w danym etapie, model nie ma tam nic do dodania i nie
    warto go wołać.

    Zwraca None, gdy nawet reguła nie ma co powiedzieć — cisza jest lepsza od wypełniacza.
    """
    imie = (lead.name or "").strip().split()[0] if lead.name else None
    powitanie = f"Dzień dobry, {imie}" if imie else "Dzień dobry"

    if lead.damage_ok is False:
        tresc = (
            f"{powitanie}. Auta, które sprowadzam, pochodzą z aukcji i są po szkodzie — "
            "dlatego są tańsze niż na rynku. Nieuszkodzonych stamtąd nie ma. "
            "Czy przy takim założeniu mam czegoś szukać?"
        )
        return Draft(
            lead_id=lead.id or 0,
            text=tresc,
            channel=_channel_for(lead),
            rationale="Klient oczekuje auta bez szkody. Bez wyjaśnienia modelu zakupu dalsza rozmowa nie ma sensu.",
        )

    if score.missing:
        pytania = {
            "czy godzi się na auto po szkodzie": (
                "Auta z aukcji są po szkodzie i dlatego są tańsze. "
                "Czy takie wchodzi w grę?"
            ),
            "budżet pod klucz w złotówkach": (
                "Jaką kwotą Pan dysponuje na auto gotowe do odbioru w Polsce, "
                "razem ze wszystkimi kosztami?"
            ),
            "marka i model": "Jakiej marki i modelu Pan szuka?",
            "rocznik": "Od jakiego rocznika mam szukać?",
            "na kiedy potrzebuje auta": "Na kiedy potrzebuje Pan auta?",
            "numer telefonu": "Pod jaki numer mogę zadzwonić?",
        }
        brak = score.missing[0]
        pytanie = pytania.get(brak, f"Proszę o jedną informację: {brak}.")
        return Draft(
            lead_id=lead.id or 0,
            text=f"{powitanie}. {pytanie}",
            channel=_channel_for(lead),
            rationale=f"Wariant zapasowy (bez modelu). Brakuje: {brak}.",
            stage_after=_stage_after(lead),
        )

    # Komplet danych i nikt do klienta nie odezwał się jeszcze ani razu. Milczenie
    # jest tu najgorszą z możliwych odpowiedzi: lead z kompletem kryteriów to lead
    # gotowy do kupienia, a pierwsze wrażenie robi czas reakcji, nie treść.
    # Potwierdzamy przyjęcie i mówimy, kiedy wrócimy — bez obiecywania konkretów.
    #
    # Warunek „ani razu” jest istotny. Bez niego reguła powtarzała tę samą wiadomość
    # powitalną w odpowiedzi na każdą kolejną wiadomość klienta — a powtórzenie
    # brzmi gorzej niż cisza, bo wygląda na automat, którym jest.
    juz_pisalismy = any(m.author is Author.BROKER for m in (history or []))
    if not juz_pisalismy and lead.stage in (Stage.NOWY, Stage.KWALIFIKACJA, Stage.SZUKANIE):
        return Draft(
            lead_id=lead.id or 0,
            text=(
                f"{powitanie}. Mam komplet informacji i zaczynam szukać. "
                "Odezwę się, gdy będę miał konkretne auta do pokazania. "
                "Czy mogę pisać na tym numerze?"
            ),
            channel=_channel_for(lead),
            rationale=(
                "Wariant zapasowy (bez modelu). Komplet kryteriów — potwierdzenie "
                "przyjęcia i zapowiedź kontaktu. Uruchom wyszukiwanie."
            ),
            stage_after=Stage.SZUKANIE if lead.stage is not Stage.SZUKANIE else None,
        )

    return None
