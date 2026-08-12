"""
Sito przed skrzynką brokera: kto zasługuje na czas człowieka, a kto na parking.

DLACZEGO SITO, A NIE WIĘCEJ LEADÓW

Policzone na realnych stawkach z `pricing/import_calculator.py` i benchmarku CPL
dla polskiego lead-genu (~300 zł):

    auto za $15 000, wariant basic → prowizja 3 615 zł
    przy konwersji 5% CAC wynosi 6 000 zł  →  STRATA 2 385 zł na kliencie
    auto za $80 000, wariant premium → prowizja 19 373 zł  →  zysk 13 373 zł

Przy tej strukturze prowizji masowy lead nie jest szansą, tylko kosztem. Każda
godzina brokera włożona w klienta z budżetem 60 tys. zł to godzina niewłożona
w klienta z budżetem 350 tys., a różnica w prowizji jest niemal trzykrotna.

Dlatego ten moduł nie ocenia — od tego jest `qualification.py`. On DECYDUJE, czy
lead w ogóle trafia przed oczy człowieka.

CZEGO TEN MODUŁ NIE ROBI

Nie kasuje leadów i nie odsyła nikogo z kwitkiem. Odrzucony lead ląduje na parkingu:
zostaje w bazie, zachowuje ocenę i wraca do skrzynki w momencie, w którym przestanie
spełniać warunek odrzucenia — bo klient podniósł budżet, uzupełnił kontakt albo
odpisał, że jednak godzi się na auto po szkodzie. Sito ma oszczędzać uwagę, a nie
palić mosty: człowiek z małym budżetem dziś bywa klientem premium za dwa lata.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from sales.models import Lead, LeadScore, Segment, Stage

# Minimalny budżet, przy którym transakcja zarabia na siebie po odjęciu kosztu
# pozyskania. Przy 150 tys. zł pod klucz stawka aukcyjna to około 25 tys. USD,
# a prowizja basic około 4 700 zł — dopiero od tego poziomu jest z czego żyć.
# Niżej trzeba albo wariantu premium, albo leada z polecenia, który nic nie kosztował.
MIN_BUDGET_PLN = float(os.getenv("SALES_MIN_BUDGET_PLN", "150000"))

# Poniżej tej oceny lead nie dostaje uwagi człowieka, choćby budżet się zgadzał.
MIN_SCORE = float(os.getenv("SALES_MIN_SCORE", "50"))


@dataclass(frozen=True)
class Verdict:
    """Czy lead wchodzi do skrzynki i dlaczego."""

    passes: bool
    reasons: list[str]
    #: Co musiałoby się zmienić, żeby wrócił. Puste, gdy już przeszedł.
    unlock: list[str]

    def summary(self) -> str:
        if self.passes:
            return "przechodzi do skrzynki"
        return "parking: " + "; ".join(self.reasons)


def check(lead: Lead, score: LeadScore) -> Verdict:
    """Decyzja o tym, czy lead trafia do brokera.

    Kolejność warunków jest kolejnością pewności. Najpierw rzeczy rozstrzygnięte
    (brak kontaktu, odmowa auta po szkodzie), potem rzeczy do rozmowy (budżet,
    ocena). Lead bez telefonu nie jest „słaby" — on jest nieobsługiwalny, i to
    inny rodzaj odrzucenia.

    Leady z polecenia i klienci powracający przechodzą MIMO progu budżetu. Ich koszt
    pozyskania jest zerowy, więc arytmetyka, która uzasadnia sito, do nich nie stosuje
    się w ogóle — a odrzucenie polecenia psuje źródło, z którego przyszło.
    """
    powody: list[str] = []
    odblokowanie: list[str] = []

    if not lead.contactable:
        powody.append("brak kontaktu — nie ma telefonu ani maila")
        odblokowanie.append("uzupełnić kontakt")

    if lead.damage_ok is False:
        powody.append("nie godzi się na auto po szkodzie")
        odblokowanie.append("wyjaśnić model zakupu i potwierdzić zgodę")

    uprzywilejowany = bool(lead.referred_by) or lead.bought_before
    if not uprzywilejowany:
        # POTENCJAŁ, nie gotówka: sito decyduje, czy warto poświęcić czas, a klient
        # z autem do sprzedania jest go wart — tylko rozmowa toczy się wolniej.
        # Liczenie samej gotówki wyrzucałoby na parking klientów na 185 tysięcy,
        # bo dziś mają w kieszeni sto.
        budzet = lead.potential_budget_pln
        if budzet is not None and budzet < MIN_BUDGET_PLN:
            powody.append(
                f"budżet {budzet / 1000:.0f} tys. zł poniżej progu "
                f"{MIN_BUDGET_PLN / 1000:.0f} tys."
            )
            odblokowanie.append("podnieść budżet albo przejść na wariant premium")
        if score.score < MIN_SCORE:
            powody.append(f"ocena {score.score:.0f} poniżej progu {MIN_SCORE:.0f}")
            odblokowanie.append("uzupełnić brakujące dane")

    return Verdict(passes=not powody, reasons=powody, unlock=odblokowanie)


def worth_model_call(lead: Lead, score: LeadScore) -> bool:
    """Czy warto wołać model, żeby napisał do tego leada.

    Osobna decyzja od `check`, bo dotyczy pieniędzy, nie uwagi. Wywołanie modelu
    kosztuje i trwa kilkanaście sekund; dla leada na parkingu wystarczy wariant
    regułowy, a często nie trzeba nic.

    Wyjątek na segment C przy odmowie auta po szkodzie: tam JEDNA dobrze napisana
    wiadomość potrafi odwrócić decyzję, a to jest najczęstszy powód traconych leadów.
    Model zarabia tam na siebie z nawiązką.
    """
    if lead.stage is Stage.STRACONY or not lead.contactable:
        return False
    if lead.damage_ok is False:
        return True
    return check(lead, score).passes


def parked_reason(lead: Lead, score: LeadScore) -> Optional[str]:
    """Jedno zdanie o tym, czemu lead siedzi na parkingu. None, gdy przeszedł."""
    werdykt = check(lead, score)
    if werdykt.passes:
        return None
    return f"{'; '.join(werdykt.reasons)}. Wróci, gdy: {'; '.join(werdykt.unlock)}."
