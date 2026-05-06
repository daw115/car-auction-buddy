"""LLM parser wiadomości od klienta -> ClientCriteria.

Klient pisze: "Szukam BMW M5 z lat 2018-2020, najlepiej East Coast,
budżet około 30k USD, do 60 tys mil"

Zwracamy: {make: 'BMW', model: 'M5', year_from: 2018, year_to: 2020,
budget_usd: 30000, max_odometer_mi: 60000, sources: [copart, iaai], ...}

Provider: Gemini Flash (free) → Anthropic fallback.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

logger = logging.getLogger("ai.message_parser")

_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=True)
else:
    load_dotenv(override=True)


SYSTEM_PROMPT = """Jesteś ekspertem od importu aut z USA. Klient pisze wiadomość po polsku
opisującą jakiego auta szuka. Twoim zadaniem jest wyciągnąć z tej wiadomości
strukturalne kryteria wyszukiwania.

WAŻNE ZASADY:
- Pole `make` jest WYMAGANE — jeśli klient nie podał marki, ZWRÓĆ błąd
- Pozostałe pola są OPCJONALNE — jeśli klient nie podał, zostaw null
- NIE wymyślaj wartości — tylko to co klient explicit napisał
- Budget: tylko jeśli klient podał kwotę. Konwertuj PLN→USD (kurs 4.0) jeśli klient podał PLN
- Year: parsuj "rocznik 2018-2020" → year_from=2018, year_to=2020
- Odometer: parsuj "do 60 tys mil" → 60000; "100 tys km" → konwertuj km→mi (×0.621)
- Sources: domyślnie ["copart", "iaai"]; jeśli klient mówi "tylko Copart" → ["copart"]
- excluded_damage_types: zawsze ["Flood", "Fire"] + dodaj inne jeśli klient wykluczył
- allowed_damage_types: pusta lista chyba że klient explicit zaznaczył
- max_results: domyślnie 30 (NIE pytaj klienta)

Zwróć WYŁĄCZNIE JSON z polami:
{
  "make": "BMW",
  "model": "M5",
  "year_from": 2018,
  "year_to": 2020,
  "budget_usd": 30000,
  "max_odometer_mi": 60000,
  "allowed_damage_types": [],
  "excluded_damage_types": ["Flood", "Fire"],
  "sources": ["copart", "iaai"],
  "max_results": 30,
  "_summary": "1-2 zdania po polsku co wyciągnąłeś",
  "_warnings": ["lista ostrzeżeń, np. 'Brak budżetu'"]
}

Bez markdown, bez ```json``` tagów.
"""


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _call_gemini(message: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Brak GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    timeout = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": f"Wiadomość od klienta:\n\n{message}\n\nZwróć JSON z kryteriami."}]}],
        "generationConfig": {
            "maxOutputTokens": 1500,
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini brak candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if p.get("text"))
    if not text:
        raise RuntimeError(f"Gemini empty (finish={candidates[0].get('finishReason')})")
    return json.loads(_strip_json(text))


def _call_anthropic(message: str) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Brak ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL") or None
    timeout = int(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "60"))
    kwargs = {"api_key": api_key, "timeout": timeout, "max_retries": 1}
    if base_url:
        kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**kwargs)
    resp = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Wiadomość od klienta:\n\n{message}"}],
    )
    chunks = [b.text for b in resp.content if b.type == "text"]
    return json.loads(_strip_json("".join(chunks)))


def parse_client_message(message: str) -> dict:
    """Główna funkcja — provider dispatch z fallback.

    Returns dict z polami ClientCriteria + _summary + _warnings.
    Raises RuntimeError gdy oba providery padną.
    """
    if not message or not message.strip():
        raise ValueError("Pusta wiadomość")

    provider = (os.getenv("LLM_REPORTS_PROVIDER", "gemini") or "gemini").lower()
    fallback = os.getenv("LLM_REPORTS_FALLBACK_ANTHROPIC", "true").lower() == "true"
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))

    last_exc: Optional[Exception] = None

    if provider == "gemini":
        try:
            return _call_gemini(message)
        except Exception as exc:
            last_exc = exc
            logger.warning(f"[MessageParser] Gemini failed: {type(exc).__name__}: {str(exc)[:120]}")
            if fallback and has_anthropic:
                try:
                    return _call_anthropic(message)
                except Exception as exc2:
                    last_exc = exc2
                    logger.warning(f"[MessageParser] Anthropic fallback failed: {type(exc2).__name__}")
    else:
        try:
            return _call_anthropic(message)
        except Exception as exc:
            last_exc = exc
            logger.warning(f"[MessageParser] Anthropic failed: {type(exc).__name__}")

    raise RuntimeError(f"Wszyscy providers failed: {last_exc}")
