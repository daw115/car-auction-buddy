"""
Typy agenta sprzedażowego: lead, jego ocena, rozmowa i wiadomość czekająca na zgodę.

Cała reszta pakietu `sales/` konsumuje te modele, więc rozszerzenia zaczynaj tutaj —
tak samo jak `parser/models.py` jest punktem wyjścia dla pipeline'u aukcyjnego.

DLACZEGO LEAD NIE JEST KLIENTEM

W bazie (`api/client_database.py`) klient to ktoś, kto ma imię, mail i telefon. Lead to
mniej: zapytanie, o którym jeszcze nie wiemy, czy stoi za nim ktoś, kto kupi. Trzymanie
obu w jednej tabeli kończy się listą trzystu "klientów", z których dwustu nigdy nie
odpisało — a wtedy nie da się odpowiedzieć na jedyne pytanie, które ma znaczenie rano:
do kogo dzwonić dzisiaj.

Lead awansuje na klienta w momencie, w którym zgadza się na licytację. Do tego czasu
żyje tutaj i ma swoją ocenę.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class Stage(str, Enum):
    """Etap lejka. Kolejność ma znaczenie — po niej sortujemy skrzynkę brokera."""

    NOWY = "nowy"                    # zgłoszenie przyszło, nikt go jeszcze nie tknął
    KWALIFIKACJA = "kwalifikacja"    # dopytujemy o budżet, rocznik, oczekiwania
    SZUKANIE = "szukanie"            # kryteria znane, pipeline aukcyjny pracuje
    OFERTA = "oferta"                # oferta wysłana, czekamy na reakcję
    ROZMOWA = "rozmowa"              # klient odpisał, negocjujemy albo tłumaczymy
    DECYZJA = "decyzja"              # klient wybrał auto, ustalamy limit licytacji
    LICYTACJA = "licytacja"          # licytujemy w jego imieniu
    WYGRANA = "wygrana"              # kupione
    PRZEGRANA = "przegrana"          # aukcja poszła wyżej niż limit — wracamy do szukania
    STRACONY = "stracony"            # klient odpadł

    @property
    def open(self) -> bool:
        """Czy sprawa jeszcze żyje i wymaga czyjejś uwagi."""
        return self not in (Stage.WYGRANA, Stage.STRACONY)


class Segment(str, Enum):
    """Do kogo dzwonić dzisiaj. Wynika z oceny, nie z sympatii."""

    A = "A"  # gorący — konkretny, z budżetem, świadomy czego kupuje
    B = "B"  # kwalifikowany — brakuje jednej lub dwóch rzeczy
    C = "C"  # do edukacji — chce, ale nie rozumie modelu zakupu
    D = "D"  # nierealny — oczekiwania nie spotkają się z rynkiem

    @property
    def label(self) -> str:
        return {
            Segment.A: "gorący",
            Segment.B: "kwalifikowany",
            Segment.C: "do edukacji",
            Segment.D: "nierealny",
        }[self]


class Channel(str, Enum):
    FORMULARZ = "formularz"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    TELEFON = "telefon"
    POLECENIE = "polecenie"
    RECZNIE = "recznie"


class Author(str, Enum):
    KLIENT = "klient"
    BROKER = "broker"
    AGENT = "agent"      # propozycja agenta, jeszcze niewysłana


@dataclass
class Message:
    """Jedna wiadomość w wątku. Wysłane i niewysłane leżą w tej samej tabeli.

    `sent_at = None` znaczy "propozycja czeka na zgodę". Trzymanie draftów obok
    wysłanych jest celowe: bez tego nie da się pokazać brokerowi rozmowy tak, jak
    będzie wyglądała po wysłaniu, a to jest dokładnie ta rzecz, którą zatwierdza.
    """

    author: Author
    text: str
    created_at: datetime
    sent_at: Optional[datetime] = None
    channel: Optional[Channel] = None
    id: Optional[int] = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def pending(self) -> bool:
        return self.author is Author.AGENT and self.sent_at is None


@dataclass
class ScoreComponent:
    """Jedna składowa oceny leada — razem z tym, co ją obniżyło."""

    key: str
    label: str
    value: float          # 0.0-1.0
    weight: float
    note: str

    @property
    def points(self) -> float:
        return self.value * self.weight


@dataclass
class LeadScore:
    """Ocena leada. Liczona deterministycznie, model jej nie dotyka.

    Ta sama zasada, co przy ocenie aut w `scoring/unified.py`: liczby liczy Python,
    a model najwyżej opisuje wynik. Ocena, którą wymyśla model, zmienia się między
    wywołaniami dla tych samych danych — a wtedy nie da się na niej oprzeć decyzji
    o tym, komu poświęcić dzień.
    """

    score: float                       # 0-100
    segment: Segment
    components: list[ScoreComponent]
    red_flags: list[str]
    missing: list[str]                 # czego nie wiemy, a musimy się dowiedzieć
    next_action: str

    def component(self, key: str) -> Optional[ScoreComponent]:
        return next((c for c in self.components if c.key == key), None)

    def summary(self) -> str:
        return f"{self.score:.0f}/100 · segment {self.segment.value} ({self.segment.label})"


@dataclass
class Lead:
    """Zapytanie i wszystko, czego się o nim dowiedzieliśmy."""

    id: Optional[int] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    channel: Channel = Channel.FORMULARZ
    stage: Stage = Stage.NOWY

    # Czego szuka — surowo, tak jak napisał, i po sparsowaniu.
    raw_request: str = ""
    make: Optional[str] = None
    model: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    budget_pln: Optional[float] = None
    settlement: str = "private"
    max_odometer_mi: Optional[int] = None

    # Sygnały jakościowe wyciągnięte z rozmowy.
    timeline_days: Optional[int] = None        # za ile chce mieć auto
    # Warunek wznowienia, nie liczba dni. „Najpierw muszę sprzedać Octavię" to nie
    # jest termin — to wyzwalacz. Bez tego lead ląduje na parkingu bez powodu powrotu.
    blocked_by: Optional[str] = None
    # Auto w rozliczeniu. Dla wielu klientów TO JEST budżet: pieniądze są zamrożone
    # w aucie, które dopiero trzeba sprzedać. Bez tych pól lead z pełnym budżetem
    # wygląda w kwalifikacji jak lead bez pieniędzy.
    trade_in_model: Optional[str] = None
    trade_in_year: Optional[int] = None
    trade_in_value_pln: Optional[float] = None
    trade_in_sold: bool = False
    # Podpowiedzi, nie filtry. Klient mówi „dwulitrówka, 248 koni" — pojemność bywa
    # warunkiem, bo przy 2.0 akcyza to 3,1% zamiast 18,6%.
    engine_hint: Optional[str] = None
    trim_hint: Optional[str] = None
    damage_ok: Optional[bool] = None           # czy godzi się na auto powypadkowe
    bought_before: bool = False
    referred_by: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_client_message_at: Optional[datetime] = None
    notes: str = ""
    client_id: Optional[int] = None            # po awansie na klienta

    @property
    def contactable(self) -> bool:
        return bool(self.phone or self.email)

    # DWA BUDŻETY, BO KLIENT MA DWIE RÓŻNE KWOTY I MYLENIE ICH KOSZTUJE W OBIE STRONY.
    #
    # Klient z setką w gotówce i Audi wartym 85 tysięcy ma dziś sto, a po sprzedaży
    # sto osiemdziesiąt pięć. Użycie jednej liczby do wszystkiego psuje albo jedno,
    # albo drugie:
    #
    #   * sito liczące tylko gotówkę odrzuci go jako leada poniżej progu, choć jest
    #     klientem na 185 tysięcy — i to jest strata, której nikt nie zauważy,
    #   * wyszukiwanie liczące razem z niesprzedanym autem pokaże mu auta za 185,
    #     wyceni je i zaproponuje, a klient nie ma dziś czym zapłacić. To jest ta
    #     dopłata po drodze, której obiecujemy nie robić.
    #
    # Stąd rozdział: sito patrzy na potencjał, wycena i wyszukiwanie na potwierdzone.

    @property
    def confirmed_budget_pln(self) -> Optional[float]:
        """Pieniądze, które klient MA dzisiaj. Do sufitu wyszukiwania i do wyceny.

        Auto w rozliczeniu wchodzi dopiero jako sprzedane — deklarowana wartość
        niesprzedanego auta to nadzieja, nie środki.
        """
        czesci = [self.budget_pln or 0.0]
        if self.trade_in_sold and self.trade_in_value_pln:
            czesci.append(self.trade_in_value_pln)
        suma = sum(czesci)
        return suma or None

    @property
    def potential_budget_pln(self) -> Optional[float]:
        """Pieniądze, które klient BĘDZIE MIAŁ po sprzedaży auta. Do sita.

        Sito odpowiada na pytanie „czy warto poświęcić temu człowiekowi czas", a nie
        „co mu dziś pokazać". Klient z autem do sprzedania jest wart czasu — tylko
        rozmowa z nim toczy się w innym tempie.
        """
        suma = (self.budget_pln or 0.0) + (self.trade_in_value_pln or 0.0)
        return suma or None

    @property
    def waiting_on(self) -> Optional[str]:
        """Na co lead czeka, zanim będzie mógł kupić. None = na nic.

        Niesprzedane auto w rozliczeniu jest warunkiem samo w sobie, nawet gdy nikt
        nie wpisał go w `blocked_by` — pieniądze są zamrożone w blasze.
        """
        if self.blocked_by:
            return self.blocked_by
        if self.trade_in_value_pln and not self.trade_in_sold:
            nazwa = self.trade_in_model or "obecne auto"
            return f"sprzedaż: {nazwa}"
        return None

    def display_name(self) -> str:
        return self.name or self.phone or self.email or f"lead #{self.id}"


@dataclass
class Draft:
    """Wiadomość napisana przez agenta, czekająca na zgodę brokera.

    Nic tego nie wysyła. Broker czyta, poprawia albo odrzuca — dopiero jego kliknięcie
    zamienia draft w wysłaną wiadomość. To nie jest ostrożność wobec modelu, tylko
    układ odpowiedzialności: wiadomość idzie do klienta pod nazwiskiem brokera.
    """

    lead_id: int
    text: str
    channel: Channel
    rationale: str                      # dlaczego akurat to — do przeczytania przed zgodą
    stage_after: Optional[Stage] = None  # etap, w który przejdzie lead po wysłaniu
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    edited_text: Optional[str] = None    # broker poprawił treść przed wysłaniem

    @property
    def final_text(self) -> str:
        """Treść, która faktycznie pójdzie — poprawka brokera wygrywa z propozycją."""
        return self.edited_text or self.text

    @property
    def pending(self) -> bool:
        return self.approved_at is None and self.rejected_at is None
