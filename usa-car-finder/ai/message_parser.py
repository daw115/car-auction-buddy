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
opisującą jakie auta go interesują. Twoim zadaniem jest wyciągnąć z tej wiadomości
listę strukturalnych kryteriów wyszukiwania (jeden lub więcej) ZGODNYCH Z BAZĄ Copart/IAAI.

KLIENT MOZE WYMIENIC KILKA AUT — zwroc tablice w polu "cars".

⚠️ KRYTYCZNA ZASADA NORMALIZACJI MODELU (Copart/IAAI używają BAZOWYCH nazw):

BMW:
- "M440i", "M440i coupé", "M440i Cabrio" → model = "4 Series" (M440i to trim, nie model!)
- "M340i", "340i" → model = "3 Series"
- "M550i", "M550i xDrive" → model = "5 Series"
- "M850i", "M840i", "M840i coupé" → model = "8 Series" (Copart/IAAI ma "8 Series", nie "M850i")
- "M3", "M5", "M8", "X3 M", "X5 M", "X6 M" → ZOSTAW jako model (to są odrębne modele M Performance)
- "X5", "X3", "X7" → ZOSTAW
- "i4", "i7", "iX" → ZOSTAW

AUDI:
- "S5" → model = "S5" (ZOSTAW — odrębny model)
- "S4", "S6", "S7", "S8", "RS5", "RS6", "RS7" → ZOSTAW
- "A5 Sportback", "S5 Sportback" → ZOSTAW jako "S5 Sportback" (wariant nadwozia istotny)

MERCEDES-BENZ:
- "C63 AMG", "E63 AMG", "S63 AMG" → ZOSTAW (modele AMG osobne)
- "E-Class", "C-Class", "S-Class" → tak jak klient pisze, dodaj myślnik
- "G-Wagen", "G63" → "G-Class"

CHEVROLET / FORD / DODGE:
- "Camaro 3.6L", "Camaro SS" → model = "Camaro" (3.6L/SS to silnik/trim, nie model)
- "Mustang GT", "Mustang Mach 1" → model = "Mustang"
- "Charger Hellcat", "Challenger SRT" → model = "Charger" / "Challenger"
- "F-150 Raptor", "F150" → model = "F-150"

HONDA / TOYOTA:
- "Civic Type R", "Civic Si" → model = "Civic"
- "Accord Sport", "Accord Hybrid" → model = "Accord"
- "Camry XSE" → model = "Camry"

REGUŁA OGÓLNA: jeśli nie jesteś pewien czy "X" to model czy trim — wybierz BAZĘ (np. "4 Series" zamiast "M440i").
Trim/wariant zostaw tylko jeśli to RZECZYWIŚCIE odrębny model (M3, M5, S5, RS6, AMG GT, Mustang GT500, Type R).

WAŻNE ZASADY (per kazde auto w cars[]):
- Pole `make` jest WYMAGANE — jeśli klient nie podał marki, pomin to auto
- Pozostałe pola są OPCJONALNE — jeśli klient nie podał, zostaw null
- Budget: tylko jeśli klient podał kwotę. Konwertuj PLN→USD (kurs 4.0)
- Year: parsuj "(2018-2020)" → year_from=2018, year_to=2020
- Odometer: "do 60 tys mil" → 60000; "100 tys km" → konwertuj km→mi (×0.621)
- Sources: domyślnie ["copart", "iaai"]
- excluded_damage_types: zawsze ["Flood", "Fire"] + dodaj inne jeśli klient wykluczył
- max_results: domyślnie 30
- ZAWSZE wypełnij pole `original_text` — dokładne to co klient napisał (np. "BMW M440i coupé")
  żebyśmy mogli zwrócić warning gdy znormalizowaliśmy.

Zwróć WYŁĄCZNIE JSON o schemacie:
{
  "cars": [
    {
      "make": "BMW",
      "model": "4 Series",
      "original_text": "BMW M440i coupé (2020-2022)",
      "year_from": 2020,
      "year_to": 2022,
      "budget_usd": null,
      "max_odometer_mi": null,
      "allowed_damage_types": [],
      "excluded_damage_types": ["Flood", "Fire"],
      "sources": ["copart", "iaai"],
      "max_results": 30
    }
  ],
  "_summary": "1-2 zdania po polsku co wyciagnales",
  "_warnings": ["lista ostrzezen — gdy znormalizowales model dodaj 'BMW M440i znormalizowano do 4 Series (M440i to trim, nie model w Copart/IAAI)'"]
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


def _sanitize_llm_json(raw: str) -> str:
    """Sanityzuje typowe błędy LLM w JSON (leading +, trailing commas, // comments)."""
    import re as _re
    raw = _re.sub(r'([:\[,]\s*)\+(\d)', r'\1\2', raw)  # +1 -> 1
    raw = _re.sub(r",(\s*[}\]])", r"\1", raw)  # trailing commas
    raw = _re.sub(r"//[^\n]*", "", raw)  # // comments
    return raw


def _parse_json_loose(raw: str) -> dict:
    """Tolerantny parser JSON od LLM-ów: strip ```, sanityzacja, balanced extract."""
    raw = _strip_json(raw)
    sanitized = _sanitize_llm_json(raw)

    # 1. Bezpośrednio
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass

    # 2. Extract first balanced {...}
    start = sanitized.find("{")
    if start >= 0:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(sanitized)):
            c = sanitized[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = sanitized[start:i+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    # 3. Last resort: surowy raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON parse failed (loose): {e}; sanitized[:200]={sanitized[:200]!r}")


def _call_gemini(message: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Brak GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    timeout = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    thinking_budget = int(os.getenv("GEMINI_THINKING_BUDGET", "0"))
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": f"Wiadomość od klienta:\n\n{message}\n\nZwróć JSON z kryteriami."}]}],
        "generationConfig": {
            "maxOutputTokens": 1500,
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": thinking_budget},
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
    return _parse_json_loose(text)


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
    # Prefill `{` w assistant message wymusza JSON output (Anthropic best practice).
    # Bez tego model czasem zaczyna chatty: "I see you mentioned X — that's a popular...".
    # Dodajemy `{` z powrotem na początek response przed JSON parse.
    resp = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": f"Wiadomość od klienta:\n\n{message}\n\nZwróć WYŁĄCZNIE JSON, zaczynając od `{{`."},
            {"role": "assistant", "content": "{"},  # prefill — model continues from `{`
        ],
    )
    chunks = [b.text for b in resp.content if b.type == "text"]
    raw = "{" + "".join(chunks)  # dokleamy prefill `{` z powrotem
    return _parse_json_loose(raw)


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
