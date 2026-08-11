"""
Agent sprzedażowy: lead trafia tu z formularza, wychodzi propozycja wiadomości.

Podział na moduły:

  models.py         typy — Lead, LeadScore, Message, Draft, Stage, Segment
  qualification.py  ocena leada 0-100, deterministycznie, bez modelu
  playbook.py       wiedza handlowa: cele etapów, obiekcje, fakty rynkowe z datami
  agent.py          propozycja wiadomości od modelu + walidator
  db.py             leady, wątki rozmów i drafty czekające na zgodę
  intake.py         wejście: zgłoszenie z formularza → lead + pierwsza propozycja

ŻADEN Z NICH NICZEGO NIE WYSYŁA. Propozycja czeka w skrzynce, a wiadomość powstaje
dopiero z zatwierdzonego draftu (`db.approve_and_send`).
"""
from sales.models import (
    Author,
    Channel,
    Draft,
    Lead,
    LeadScore,
    Message,
    ScoreComponent,
    Segment,
    Stage,
)
from sales.qualification import score_lead

__all__ = [
    "Author",
    "Channel",
    "Draft",
    "Lead",
    "LeadScore",
    "Message",
    "ScoreComponent",
    "Segment",
    "Stage",
    "score_lead",
]
