"""
AI Email Parser - wyciąga parametry wyszukiwania z treści emaila.
Używa Claude API do analizy emaili od klientów.
"""
import os
import json
import anthropic
from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class SearchCriteria:
    """Parametry wyszukiwania wyciągnięte z emaila."""
    make: str
    model: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    budget_usd: Optional[float] = None
    max_odometer_mi: Optional[int] = None
    excluded_damage_types: list = None
    client_email: Optional[str] = None
    client_name: Optional[str] = None

    def __post_init__(self):
        if self.excluded_damage_types is None:
            self.excluded_damage_types = ["Flood", "Fire"]


class EmailParser:
    """Parser emaili używający Claude API."""

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY musi być ustawiony w .env")

        self.client = anthropic.Anthropic(api_key=self.api_key)

    def parse_email(self, email_body: str, sender_email: str = None) -> Optional[SearchCriteria]:
        """
        Parsuje treść emaila i wyciąga parametry wyszukiwania.

        Args:
            email_body: Treść emaila od klienta
            sender_email: Email nadawcy (opcjonalnie)

        Returns:
            SearchCriteria lub None jeśli nie udało się sparsować
        """
        prompt = f"""Przeanalizuj poniższy email od klienta i wyciągnij parametry wyszukiwania auta z USA.

Email od: {sender_email or 'nieznany'}

Treść emaila:
{email_body}

Wyciągnij następujące parametry (jeśli są dostępne w emailu):
- make: marka auta (np. Toyota, BMW, Mercedes)
- model: model auta (opcjonalnie, np. Camry, X5, C-Class)
- year_from: rocznik od (rok, np. 2018)
- year_to: rocznik do (rok, np. 2023)
- budget_usd: maksymalny budżet w USD (liczba, np. 15000)
- max_odometer_mi: maksymalny przebieg w milach (liczba, np. 80000)
- excluded_damage_types: lista wykluczonych typów uszkodzeń (domyślnie ["Flood", "Fire"])
- client_email: email klienta (jeśli jest w treści emaila)
- client_name: imię/nazwisko klienta (jeśli jest w treści emaila)

WAŻNE:
- Jeśli klient podaje budżet w PLN lub EUR, przelicz na USD (1 EUR ≈ 1.1 USD, 1 PLN ≈ 0.25 USD)
- Jeśli klient podaje przebieg w km, przelicz na mile (1 km ≈ 0.621371 mil)
- Jeśli klient nie podaje konkretnych wartości, użyj rozsądnych domyślnych (np. budżet 15000 USD, przebieg 100000 mil)
- Jeśli email nie zawiera zapytania o auto, zwróć null

Zwróć WYŁĄCZNIE poprawny JSON w formacie:
{{
  "make": "Toyota",
  "model": "Camry",
  "year_from": 2018,
  "year_to": 2023,
  "budget_usd": 15000,
  "max_odometer_mi": 80000,
  "excluded_damage_types": ["Flood", "Fire"],
  "client_email": "klient@example.com",
  "client_name": "Jan Kowalski"
}}

Jeśli email nie dotyczy wyszukiwania auta, zwróć: null
"""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6-thinking",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()

            # Usuń markdown code blocks jeśli są
            if "```" in response_text:
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            # Parsuj JSON
            data = json.loads(response_text)

            if data is None:
                return None

            # Użyj sender_email jeśli client_email nie został wyciągnięty
            if not data.get("client_email") and sender_email:
                data["client_email"] = sender_email

            return SearchCriteria(**data)

        except Exception as e:
            print(f"Błąd parsowania emaila: {e}")
            return None
