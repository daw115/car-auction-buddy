"""
Ocena leada — deterministyczna odpowiedź na pytanie "do kogo dzwonić dzisiaj".

WZORZEC JEST TEN SAM CO PRZY OCENIE AUT

`scoring/unified.py` liczy ocenę auta w Pythonie, a model tylko pisze uzasadnienie —
bo ocena wymyślona przez model zmienia się między wywołaniami dla tych samych danych.
Ocena klienta ma dokładnie ten problem i to samo rozwiązanie. Model dostaje gotowy
wynik i pisze wiadomość; liczby są tutaj.

Wagi składowych, dla których brakuje danych, rozkładają się proporcjonalnie na resztę.
Brak sygnału nie obniża oceny — lead, który napisał trzy zdania, nie jest gorszy od
tego, który wypełnił dziesięć pól. Jest po prostu mniej zbadany, a to jest informacja
o nas, nie o nim.

DLACZEGO ŚWIADOMOŚĆ USZKODZEŃ WAŻY NAJWIĘCEJ

Największym pojedynczym powodem straconych leadów w tym biznesie nie jest cena, tylko
zderzenie z faktem, że auto z Copartu jest rozbite. Klient, który tego nie wie, przejdzie
całą kwalifikację, dostanie ofertę i odpadnie przy pierwszym zdjęciu. Klient, który wie,
jest wart trzech takich, choćby miał mniejszy budżet. Dlatego to jest składowa o
najwyższej wadze, a nie ciekawostka w notatkach.

Ocena nie jest wyrokiem. Segment D nie znaczy "odrzuć" — znaczy "nie dzisiaj i nie
w ten sposób". Osobne pole `next_action` mówi, co z takim leadem zrobić.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sales.models import Lead, LeadScore, ScoreComponent, Segment, Stage

# Wagi bazowe. Suma 1,0 przy komplecie danych; przy brakach renormalizujemy.
WEIGHTS: dict[str, float] = {
    "damage_awareness": 0.22,
    "budget": 0.20,
    "spec": 0.15,
    "reachability": 0.13,
    "urgency": 0.12,
    "engagement": 0.10,
    "source": 0.08,
}

LABELS: dict[str, str] = {
    "damage_awareness": "Świadomość, że auto jest po szkodzie",
    "budget": "Budżet",
    "spec": "Konkretność zapytania",
    "reachability": "Kontakt",
    "urgency": "Horyzont zakupu",
    "engagement": "Zaangażowanie w rozmowie",
    "source": "Źródło leada",
}

# Progi segmentów.
SEGMENT_A = 72.0
SEGMENT_B = 52.0
SEGMENT_C = 30.0

# Najniższa stawka aukcyjna, przy której da się jeszcze mówić o aucie na chodzie.
# Poniżej tego progu na Copart są głównie wraki i auta na części — technicznie dostępne,
# ale klient szukający auta do jeżdżenia dostanie od nas listę, na którą sam nie wpadnie.
MIN_SENSIBLE_BID_USD = 3_500.0

# Stawka, poniżej której auta z ostatnich trzech roczników praktycznie nie występują.
YOUNG_CAR_MIN_BID_USD = 11_000.0
YOUNG_CAR_AGE_YEARS = 3

# Po tylu dniach ciszy lead przestaje być leadem, a zaczyna być listą kontaktów.
SILENCE_COLD_DAYS = 14
SILENCE_DEAD_DAYS = 45


def _num(value: float) -> str:
    """Liczba ze spacją jako separatorem tysięcy.

    Formatujemy SAMĄ liczbę, nie całe zdanie. Zamiana przecinków w gotowym zdaniu
    zjada też ten po przecinku zdaniowym i z "auta na części, nie do jeżdżenia"
    robi się "auta na części  nie do jeżdżenia" — ta sama pułapka, przed którą
    ostrzega komentarz w `report/whatsapp.py`.
    """
    return f"{value:,.0f}".replace(",", " ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_since(moment: Optional[datetime]) -> Optional[int]:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, (_now() - moment).days)


# ───────────────────────────────────────────────────────────────────── składowe


def _damage_awareness(lead: Lead) -> Optional[tuple[float, str]]:
    """Czy klient wie, że kupuje auto po szkodzie.

    None (składowa pomijana) tylko wtedy, gdy jeszcze o to nie zapytaliśmy. To jest
    pierwsze pytanie kwalifikacyjne i dopóki nie padnie, nie mamy prawa domyślać się
    odpowiedzi w żadną stronę.
    """
    if lead.damage_ok is None:
        return None
    if lead.damage_ok:
        return 1.0, "wie, że auto jest po szkodzie, i to akceptuje"
    return 0.0, "oczekuje auta nieuszkodzonego — nasz model zakupu tego nie daje"


def _budget(lead: Lead) -> Optional[tuple[float, str]]:
    """Budżet: czy jest i czy da się za niego kupić auto, którego klient szuka.

    Liczymy przez ten sam sufit, co pipeline aukcyjny (`scoring/budget.py`), a nie przez
    dzielenie budżetu przez kurs. Koszty stałe — transport, odprawa, prowizja — nie
    skalują się z ceną auta, więc przy niskim budżecie zjadają go prawie w całości
    i naiwne przeliczenie pokazuje auta, których nie ma.
    """
    budzet = lead.potential_budget_pln
    if not budzet:
        return None

    from scoring.budget import max_bid_for_budget

    # POTENCJAŁ, nie gotówka. Klient z setką i Audi wartym 85 tysięcy jest klientem
    # na 185, a nie na 100 — składowa mierzy, czy go stać, a nie co mu dziś pokazać.
    sufit = max_bid_for_budget(budzet, settlement=lead.settlement).max_bid_usd

    if sufit < MIN_SENSIBLE_BID_USD:
        return 0.1, (
            f"budżet {_num(budzet)} zł daje stawkę ok. {_num(sufit)} USD — "
            f"poniżej progu, od którego zaczynają się auta na chodzie"
        )

    if _wants_young_car(lead) and sufit < YOUNG_CAR_MIN_BID_USD:
        return 0.45, (
            f"budżet daje stawkę ok. {_num(sufit)} USD, a szuka rocznika "
            f"{lead.year_from} — te dwie rzeczy się nie spotkają bez korekty"
        )

    if sufit >= YOUNG_CAR_MIN_BID_USD:
        return 1.0, f"budżet daje stawkę ok. {_num(sufit)} USD — szeroki wybór"

    return 0.75, f"budżet daje stawkę ok. {_num(sufit)} USD — wybór ograniczony"


def _wants_young_car(lead: Lead) -> bool:
    if not lead.year_from:
        return False
    return lead.year_from >= _now().year - YOUNG_CAR_AGE_YEARS


def _spec(lead: Lead) -> tuple[float, str]:
    """Ile wiemy o tym, czego klient szuka.

    Nie ma wariantu "brak danych": każdy lead ma jakieś zapytanie, choćby puste, a puste
    zapytanie jest informacją — znaczy, że rozmowa musi się zacząć od podstaw.
    """
    znane = [
        bool(lead.make),
        bool(lead.model),
        bool(lead.year_from or lead.year_to),
        bool(lead.max_odometer_mi),
    ]
    ile = sum(znane)
    opisy = {
        0: "nie wiemy nawet, jakiej marki szuka",
        1: "znamy tylko markę albo tylko rocznik",
        2: "znamy zarys — brakuje szczegółów",
        3: "zapytanie konkretne",
        4: "zapytanie w pełni określone",
    }
    return ile / 4, opisy[ile]


def _reachability(lead: Lead) -> tuple[float, str]:
    if lead.phone and lead.email:
        return 1.0, "telefon i mail"
    if lead.phone:
        return 0.85, "sam telefon — wystarczy do rozmowy"
    if lead.email:
        return 0.5, "sam mail — wolniejszy kanał, gorsza konwersja"
    return 0.0, "brak kontaktu — nie ma jak odpowiedzieć"


def _urgency(lead: Lead) -> Optional[tuple[float, str]]:
    if lead.timeline_days is None:
        return None
    if lead.timeline_days <= 30:
        return 1.0, "chce auto w ciągu miesiąca"
    if lead.timeline_days <= 90:
        return 0.7, "horyzont do trzech miesięcy"
    return 0.3, "kupuje bez terminu — wróci, kiedy wróci"


def _engagement(lead: Lead) -> Optional[tuple[float, str]]:
    """Czy rozmowa żyje. Cisza jest sygnałem, ale dopiero po czasie."""
    dni = _days_since(lead.last_client_message_at)
    if dni is None:
        return None
    if dni <= 2:
        return 1.0, "odpisał w ciągu ostatnich dwóch dni"
    if dni <= 7:
        return 0.75, f"ostatnia wiadomość {dni} dni temu"
    if dni <= SILENCE_COLD_DAYS:
        return 0.4, f"cisza od {dni} dni"
    if dni <= SILENCE_DEAD_DAYS:
        return 0.15, f"cisza od {dni} dni — lead stygnie"
    return 0.0, f"cisza od {dni} dni"


def _source(lead: Lead) -> tuple[float, str]:
    from sales.models import Channel

    if lead.referred_by or lead.channel is Channel.POLECENIE:
        return 1.0, f"polecenie{f' od: {lead.referred_by}' if lead.referred_by else ''}"
    if lead.bought_before:
        return 1.0, "kupował u nas wcześniej"
    if lead.channel in (Channel.TELEFON, Channel.WHATSAPP):
        return 0.8, "odezwał się sam, kanałem bezpośrednim"
    if lead.channel is Channel.FORMULARZ:
        return 0.6, "formularz ze strony"
    return 0.5, f"kanał: {lead.channel.value}"


# ─────────────────────────────────────────────────────────── czerwone flagi i braki


def _red_flags(lead: Lead, sufit_usd: Optional[float]) -> list[str]:
    """Rzeczy, o których broker ma wiedzieć, zanim cokolwiek wyśle."""
    flagi: list[str] = []

    if lead.damage_ok is False:
        flagi.append(
            "Klient chce auto nieuszkodzone. Z aukcji takich nie ma — albo zmieni "
            "oczekiwania, albo to nie jest nasz klient."
        )

    if sufit_usd is not None and sufit_usd < MIN_SENSIBLE_BID_USD:
        flagi.append(
            f"Budżet daje stawkę ok. {_num(sufit_usd)} USD. Poniżej "
            f"{_num(MIN_SENSIBLE_BID_USD)} USD to auta na części, nie do jeżdżenia."
        )

    if _wants_young_car(lead) and sufit_usd is not None and sufit_usd < YOUNG_CAR_MIN_BID_USD:
        flagi.append(
            f"Szuka rocznika {lead.year_from} przy budżecie na stawkę "
            f"ok. {_num(sufit_usd)} USD. Trzeba zejść z rocznikiem albo dołożyć."
        )

    if not lead.contactable:
        flagi.append("Brak telefonu i maila — nie ma jak odpowiedzieć.")

    # Lead czekający na sprzedaż swojego auta nie kupi w tym tygodniu, choćby miał
    # komplet danych i wysoką ocenę. To nie jest wada — to inne tempo rozmowy,
    # a naciskanie na decyzję psuje ją szybciej niż cisza.
    if lead.waiting_on:
        flagi.append(
            f"Czeka na: {lead.waiting_on}. Nie naciskaj na decyzję — ustal termin powrotu."
        )
    if lead.trade_in_value_pln and not lead.trade_in_sold:
        flagi.append(
            f"Budżet zawiera {_num(lead.trade_in_value_pln)} zł z auta, które nie jest "
            f"jeszcze sprzedane. Wyszukiwanie liczy sufit bez tej kwoty."
        )

    dni = _days_since(lead.last_client_message_at)
    if dni is not None and dni > SILENCE_DEAD_DAYS and lead.stage.open:
        flagi.append(f"Cisza od {dni} dni przy otwartej sprawie — czas domknąć albo odpuścić.")

    return flagi


def _missing(lead: Lead) -> list[str]:
    """Czego nie wiemy, a musimy — to jest lista pytań do zadania w rozmowie."""
    braki: list[str] = []
    if lead.damage_ok is None:
        braki.append("czy godzi się na auto po szkodzie")
    if not lead.potential_budget_pln:
        braki.append("budżet pod klucz w złotówkach")
    if not lead.make:
        braki.append("marka i model")
    if not (lead.year_from or lead.year_to):
        braki.append("rocznik")
    if lead.timeline_days is None:
        braki.append("na kiedy potrzebuje auta")
    if not lead.phone:
        braki.append("numer telefonu")
    return braki


def _next_action(
    lead: Lead,
    segment: Segment,
    braki: list[str],
    sufit_usd: Optional[float],
) -> str:
    """Jedno zdanie: co zrobić z tym leadem teraz."""
    if not lead.contactable:
        return "Uzupełnij kontakt — bez telefonu albo maila nie ruszymy dalej."

    if lead.damage_ok is False:
        return "Wyjaśnij model zakupu: auta z aukcji są po szkodzie. Bez tego nie ma sensu szukać."

    # Kolejność jest tu istotna: przy budżecie bez szans dopytywanie o rocznik i przebieg
    # jest stratą czasu obu stron. Najpierw kwota, dopiero potem reszta.
    if sufit_usd is not None and sufit_usd < MIN_SENSIBLE_BID_USD:
        return (
            f"Powiedz wprost, że przy {_num(lead.potential_budget_pln or 0)} zł nie ma auta na chodzie — "
            "zapytaj, czy budżet da się podnieść."
        )

    if lead.waiting_on:
        return f"Czeka na: {lead.waiting_on}. Umów się na konkretny termin powrotu."

    if braki:
        return f"Dopytaj: {', '.join(braki[:3])}."

    if segment is Segment.D:
        return "Skoryguj oczekiwania albo odłóż — dziś tego nie kupimy."

    if lead.stage is Stage.NOWY:
        return "Kryteria komplet — uruchom wyszukiwanie i przygotuj ofertę."

    if lead.stage is Stage.OFERTA:
        dni = _days_since(lead.last_client_message_at)
        if dni is not None and dni >= 3:
            return "Oferta bez odpowiedzi od kilku dni — dobij jednym pytaniem."
        return "Czekaj na reakcję na ofertę."

    return "Prowadź rozmowę — komplet danych, sprawa w toku."


# ─────────────────────────────────────────────────────────────────────── wynik


def _segment_for(score: float, lead: Lead, sufit_usd: Optional[float]) -> Segment:
    """Segment z punktów, ale z dwoma twardymi sufitami.

    Punkty same nie wystarczą, bo dwie rzeczy nie są wadą stopniowalną, tylko
    warunkiem wstępnym. Lead, który ich nie spełnia, może mieć świetną resztę
    składowych i wyjść na 70 punktów — a i tak nie kupi dzisiaj niczego. Wpisanie
    go do segmentu A albo B znaczyłoby, że broker zaczyna dzień od telefonu,
    który nie mógł się udać.

      * odmowa auta po szkodzie — to nie jest nasz model zakupu,
      * budżet poniżej progu sensownej stawki — nie ma czego kupić.

    W obu przypadkach sufitem jest C, czyli "do edukacji": rozmowa ma sens, tylko
    jej celem nie jest sprzedaż, a skorygowanie oczekiwań.
    """
    if score >= SEGMENT_A:
        base = Segment.A
    elif score >= SEGMENT_B:
        base = Segment.B
    elif score >= SEGMENT_C:
        base = Segment.C
    else:
        base = Segment.D

    blokada = lead.damage_ok is False or (
        sufit_usd is not None and sufit_usd < MIN_SENSIBLE_BID_USD
    )
    if blokada and base in (Segment.A, Segment.B):
        return Segment.C
    return base


def score_lead(lead: Lead) -> LeadScore:
    """Ocena leada w skali 0-100 razem z tym, co ją uzasadnia."""
    surowe: dict[str, Optional[tuple[float, str]]] = {
        "damage_awareness": _damage_awareness(lead),
        "budget": _budget(lead),
        "spec": _spec(lead),
        "reachability": _reachability(lead),
        "urgency": _urgency(lead),
        "engagement": _engagement(lead),
        "source": _source(lead),
    }

    obecne = {k: v for k, v in surowe.items() if v is not None}
    suma_wag = sum(WEIGHTS[k] for k in obecne) or 1.0

    components: list[ScoreComponent] = []
    for key, (value, note) in obecne.items():
        # Renormalizacja: brak danych nie karze, tylko zwiększa wagę tego, co wiemy.
        waga = WEIGHTS[key] / suma_wag
        components.append(
            ScoreComponent(key=key, label=LABELS[key], value=value, weight=waga, note=note)
        )

    score = sum(c.points for c in components) * 100

    sufit = None
    if lead.potential_budget_pln:
        from scoring.budget import max_bid_for_budget

        sufit = max_bid_for_budget(
            lead.potential_budget_pln, settlement=lead.settlement
        ).max_bid_usd

    flagi = _red_flags(lead, sufit)

    segment = _segment_for(score, lead, sufit)

    braki = _missing(lead)
    return LeadScore(
        score=round(score, 1),
        segment=segment,
        components=sorted(components, key=lambda c: c.weight, reverse=True),
        red_flags=flagi,
        missing=braki,
        next_action=_next_action(lead, segment, braki, sufit),
    )
