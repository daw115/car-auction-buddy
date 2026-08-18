"""Parsowanie JSON-a, który przyszedł od modelu językowego.

Model potrafi owinąć odpowiedź w ```json, poprzedzić ją zdaniem, zostawić
przecinek przed klamrą albo dopisać komentarz. Nic z tego nie jest awarią danych
— to literówki w formacie, które da się posprzątać.

JEDEN PARSER, BO DWA SIĘ ROZJECHAŁY. `report/hybrid_reports.py` miał wersję
z sanityzacją, `report/offer_agent.py` własną, prostszą, a `ai/claude_code.py`
trzecią, całkiem nietolerancyjną — i to właśnie przez tę trzecią w nocy z 17 na
18 sierpnia nie powstało 34 raporty: usterka, którą sanityzacja usuwa jednym
podstawieniem, wywracała całe generowanie. Dokładnie ten sam mechanizm co przy
dwóch tabelach tłumaczeń uszkodzeń.
"""

from __future__ import annotations

import json
from typing import Any

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
    """Sanityzuje typowe błędy LLM w JSON:
    - usuwa leading + przed liczbami (Claude lubi pisać "+1" zamiast "1")
    - usuwa trailing commas
    - usuwa komentarze //...
    """
    import re as _re
    # 1. Usuń + przed liczbą (po `:` lub `,` lub spacji): "points": +1 -> "points": 1
    raw = _re.sub(r'([:\[,]\s*)\+(\d)', r'\1\2', raw)
    # 2. Trailing commas before }/]
    raw = _re.sub(r",(\s*[}\]])", r"\1", raw)
    # 3. Komentarze //
    raw = _re.sub(r"//[^\n]*", "", raw)
    return raw


class OdpowiedzNieDoOdczytania(RuntimeError):
    """Model oddał coś, co nie jest poprawnym JSON-em.

    Własny typ, a nie gołe `RuntimeError`, bo pętla ponawiania rozpoznawała
    awarie po fragmentach tekstu w komunikacie („timeout", „503"). Zepsuty JSON
    nie pasował do żadnego wzorca i leciał wyjątek bez drugiej próby — mimo że
    to jest dokładnie ten rodzaj usterki, który przy ponowieniu mija: ten sam
    lot i te same dane dają za drugim razem poprawną odpowiedź. Dopasowywanie
    po napisach jest zresztą tym, przez co ta luka powstała.
    """


def _parse_json_loose(raw: str) -> dict:
    """Parsuje JSON z LLM-a tolerancyjnie:
    1. _strip_json (usuwa ``` wrappers)
    2. _sanitize_llm_json (typowe LLM literówki)
    3. próba bezpośrednia
    4. extract first balanced {...} block
    """
    raw = _strip_json(raw)
    raw_sanitized = _sanitize_llm_json(raw)

    # 1. bezpośrednio po sanityzacji
    try:
        return json.loads(raw_sanitized)
    except json.JSONDecodeError:
        pass

    # 2. extract first balanced {...}
    start = raw_sanitized.find("{")
    if start >= 0:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(raw_sanitized)):
            c = raw_sanitized[i]
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
                    candidate = raw_sanitized[start:i+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    # 3. last resort: surowy raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # Okno WOKÓŁ miejsca błędu, nie pierwsze 300 znaków. Odpowiedzi modelu
        # sypią się w połowie prozy (obserwowane: znak 4015), więc początek
        # dokumentu nie mówi nic o przyczynie i diagnoza stawała w miejscu.
        poz = getattr(e, "pos", 0) or 0
        okno = raw_sanitized[max(0, poz - 120) : poz + 120]
        raise OdpowiedzNieDoOdczytania(
            f"JSON parse failed even with loose mode: {e}; "
            f"dlugosc={len(raw_sanitized)}; wokol_bledu={okno!r}"
        )
