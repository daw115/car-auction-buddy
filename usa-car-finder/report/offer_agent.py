"""
Generator ofert sprzedażowych używając agenta @agent-oferta-auto-usa.md
Generuje 2 wersje:
  - Pełna (1200-1500 słów) — dla sprzedającego na Telegram
  - Skrócona (200 słów) — dla klienta na email
"""
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Tuple
from anthropic import Anthropic
from parser.models import AnalyzedLot

AGENT_PROMPT_PATH = Path(__file__).parent.parent.parent / "agent-oferta-auto-usa.md"
OFFER_MODEL = os.getenv("ANTHROPIC_OFFER_MODEL", "claude-sonnet-4-6-thinking")


def _call_anthropic_text(system: str, user_prompt: str, max_tokens: int = 8000) -> str:
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=OFFER_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


def _call_gemini_text(system: str, user_prompt: str, max_tokens: int = 8000) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Brak GEMINI_API_KEY")
    model = os.getenv("GEMINI_OFFER_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    timeout = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "120"))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7,
            "thinkingConfig": {"thinkingBudget": int(os.getenv("GEMINI_THINKING_BUDGET", "0"))},
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
    return text


def _call_kiro_text(system: str, user_prompt: str, max_tokens: int = 8000) -> str:
    api_key = os.getenv("KIRO_API_KEY")
    if not api_key:
        raise RuntimeError("Brak KIRO_API_KEY")
    cli_path = os.getenv("KIRO_CLI_PATH", os.path.expanduser("~/.local/bin/kiro-cli"))
    effort = os.getenv("KIRO_EFFORT", "low")
    timeout = int(os.getenv("KIRO_TIMEOUT_SECONDS", "180"))
    model = _resolve_kiro_model()
    prompt = f"{system}\n\n{user_prompt}"
    env = {**os.environ, "KIRO_API_KEY": api_key}
    try:
        result = subprocess.run(
            [cli_path, "chat", "--no-interactive", "--trust-tools=", "-w", "never",
             "--effort", effort, "--model", model, prompt],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"kiro-cli nie znaleziony ({cli_path}): {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Kiro CLI timeout po {timeout}s") from exc
    if result.returncode != 0:
        raise RuntimeError(f"Kiro CLI exit {result.returncode}: {result.stderr[:300]}")
    text = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", result.stdout).strip()
    if not text:
        raise RuntimeError(f"Kiro CLI pusta odpowiedź (stderr: {result.stderr[:300]})")
    return text


_OFFER_AGENT_CALLERS = {
    "gemini": _call_gemini_text,
    "kiro": _call_kiro_text,
    "anthropic": _call_anthropic_text,
}


def _resolve_kiro_model() -> str:
    """Model Kiro: nadpisanie z dashboardu ma pierwszeństwo przed .env KIRO_MODEL."""
    try:
        from api.settings_db import get_ai_model_override
        override = get_ai_model_override("kiro")
        if override:
            return override
    except Exception:
        pass
    return os.getenv("KIRO_MODEL", "claude-haiku-4.5")


def _resolve_offer_provider() -> str:
    """Nadpisanie z dashboardu (settings_db) ma pierwszeństwo przed .env."""
    try:
        from api.settings_db import get_ai_provider_override
        override = get_ai_provider_override("offer_agent_ai_provider")
        if override:
            return override.lower()
    except Exception:
        pass
    return (os.getenv("OFFER_AGENT_AI_PROVIDER", "gemini") or "gemini").lower()


def _call_offer_agent_llm(system: str, user_prompt: str) -> str:
    """Provider dispatch (OFFER_AGENT_AI_PROVIDER, default 'gemini'), z fallbackiem
    do Anthropic gdy skonfigurowany provider zawiedzie i jest klucz."""
    provider = _resolve_offer_provider()
    caller = _OFFER_AGENT_CALLERS.get(provider, _call_gemini_text)
    try:
        return caller(system, user_prompt)
    except Exception as exc:
        print(f"[OfferAgent] {provider} nieudany ({type(exc).__name__}: {exc})")
        fallback = os.getenv("LLM_REPORTS_FALLBACK_ANTHROPIC", "true").lower() == "true"
        if provider != "anthropic" and fallback and os.getenv("ANTHROPIC_API_KEY"):
            print("[OfferAgent] Fallback → Anthropic")
            return _call_anthropic_text(system, user_prompt)
        raise


def _load_agent_prompt() -> str:
    """Ładuje prompt agenta z pliku markdown."""
    if not AGENT_PROMPT_PATH.exists():
        raise FileNotFoundError(f"Brak pliku agenta: {AGENT_PROMPT_PATH}")
    return AGENT_PROMPT_PATH.read_text(encoding="utf-8")


def _format_lot_data(lot: AnalyzedLot) -> str:
    """Formatuje dane lota do struktury oczekiwanej przez agenta."""
    l = lot.lot
    ai = lot.analysis

    return f"""
=== AUKCJA ===
Platforma: {l.source.upper()}
Lot #: {l.lot_id}
Marka/Model/Rok: {l.year or '?'} {l.make or ''} {l.model or ''} {l.trim or ''}
VIN: {l.full_vin or l.vin or 'brak'}
Przebieg: {l.odometer_mi or '?'} mil ({l.odometer_km or '?'} km)
Lokalizacja: {l.location_city or ''}, {l.location_state or ''}
Title: {l.title_type or 'brak danych'}
Damage Primary: {l.damage_primary or 'brak danych'}
Damage Secondary: {l.damage_secondary or 'brak'}
Run & Drive: {'Yes' if l.keys else 'brak danych'}
Cena aktualna: ${l.current_bid_usd or 0:,.0f}
Koniec aukcji: {l.auction_date or 'brak danych'}

=== ANALIZA AI ===
Score: {ai.score:.1f}/10
Rekomendacja: {ai.recommendation}
Szacowany koszt naprawy: ${ai.estimated_repair_usd or 0:,}
Szacowany koszt całkowity: ${ai.estimated_total_cost_usd or 0:,}
Opis dla klienta: {ai.client_description_pl or 'brak'}
Red flags: {', '.join(ai.red_flags) if ai.red_flags else 'brak'}
Notatki AI: {ai.ai_notes or 'brak'}

=== KLIENT ===
[Brak szczegółowych danych o kliencie — użyj trybu POPULARNY]

=== DODATKOWE ===
Link do aukcji: {l.url}
Zdjęcia: {len(l.images)} dostępnych
"""


def _strip_html_payload(text: str) -> str:
    """Usuwa markdown fences, jeśli model owinie HTML w blok kodu."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _fallback_short_html(
    top_lots: List[AnalyzedLot],
    client_name: str,
    search_query: str,
) -> str:
    """Lokalna skrócona oferta, gdy odpowiedź modelu nie zawiera sekcji SHORT."""
    items = []
    for item in top_lots[:3]:
        lot = item.lot
        ai = item.analysis
        items.append(
            "<li>"
            f"<strong>{lot.year or '?'} {lot.make or ''} {lot.model or ''}</strong> "
            f"({lot.location_state or 'USA'}) - score {ai.score:.1f}/10, "
            f"szacowany koszt całkowity ${ai.estimated_total_cost_usd or 0:,}"
            "</li>"
        )

    return f"""
<html>
<body>
  <p>Dzień dobry {client_name},</p>
  <p>Przygotowaliśmy krótką listę najlepszych propozycji dla zapytania: <strong>{search_query or 'auto z USA'}</strong>.</p>
  <ul>
    {''.join(items)}
  </ul>
  <p>Pełna oferta zawiera szczegółową analizę kosztów, uszkodzeń i ryzyk dla każdego auta.</p>
</body>
</html>
""".strip()


def generate_offers_with_agent(
    top_lots: List[AnalyzedLot],
    remaining_lots: List[AnalyzedLot],
    client_name: str = "Kliencie",
    search_query: str = "",
) -> Tuple[str, str]:
    """
    Generuje 2 wersje oferty używając agenta:
      - Pełna (HTML, 1200-1500 słów) — dla sprzedającego
      - Skrócona (HTML, 200 słów) — dla klienta

    Returns:
        (full_html, short_html)
    """
    agent_system = _load_agent_prompt()

    # Przygotuj dane wszystkich lotów
    lots_data = "\n\n".join([
        f"=== LOT #{i+1} (TOP REKOMENDACJA) ===\n{_format_lot_data(lot)}"
        for i, lot in enumerate(top_lots)
    ])

    if remaining_lots:
        lots_data += "\n\n" + "\n\n".join([
            f"=== LOT #{i+len(top_lots)+1} (DODATKOWA PROPOZYCJA) ===\n{_format_lot_data(lot)}"
            for i, lot in enumerate(remaining_lots)
        ])

    # Prompt dla agenta
    top_count = len(top_lots)
    remaining_count = len(remaining_lots)

    user_prompt = f"""Przygotuj profesjonalną ofertę sprzedaży dla klienta: {client_name}

Zapytanie klienta: {search_query}

DANE LOTÓW:
{lots_data}

ZADANIE:
1. Wygeneruj PEŁNĄ ofertę (tryb POPULARNY, 1200-1500 słów, format HTML)
   - Wszystkie 7 sekcji zgodnie z instrukcją agenta
   - TOP {top_count} rekomendacji szczegółowo
   - {remaining_count} dodatkowych propozycji kompaktowo

2. Wygeneruj SKRÓCONĄ wersję (tryb SHORT, max 200 słów, format HTML)
   - Hook + 3 najmocniejsze argumenty
   - Kalkulacja w 1 linii
   - CTA z linkiem do pełnej oferty

WAŻNE:
- Używaj HTML (nie markdown)
- Zachowaj profesjonalny ton
- Wszystkie ceny w PLN (przelicz USD * 4.0)
- Bądź uczciwy wobec uszkodzeń
- Dodaj sekcję NOTATKI STRATEGICZNE na końcu pełnej oferty

Odpowiedz w formacie:
=== PEŁNA OFERTA ===
[HTML]

=== SKRÓCONA OFERTA ===
[HTML]

=== NOTATKI STRATEGICZNE ===
[tekst dla sprzedającego]
"""

    provider = _resolve_offer_provider()
    print(f"[OfferAgent] Generuję oferty przez {provider}...")

    content = _call_offer_agent_llm(agent_system, user_prompt)

    # Parsuj odpowiedź
    try:
        parts = content.split("=== PEŁNA OFERTA ===")
        if len(parts) < 2:
            raise ValueError("Brak sekcji PEŁNA OFERTA")

        rest = parts[1].split("=== SKRÓCONA OFERTA ===")
        if len(rest) < 2:
            full_html = _strip_html_payload(parts[1])
            short_html = _fallback_short_html(top_lots, client_name, search_query)
            print("[OfferAgent] ⚠ Brak sekcji SKRÓCONA OFERTA — używam lokalnego fallbacku")
            print(f"[OfferAgent] ✅ Pełna: {len(full_html)} znaków | Skrócona fallback: {len(short_html)} znaków")
            return full_html, short_html

        full_html = _strip_html_payload(rest[0])

        short_rest = rest[1].split("=== NOTATKI STRATEGICZNE ===")
        short_html = _strip_html_payload(short_rest[0])

        notes = short_rest[1].strip() if len(short_rest) > 1 else ""

        print(f"[OfferAgent] ✅ Pełna: {len(full_html)} znaków | Skrócona: {len(short_html)} znaków")
        if notes:
            print(f"[OfferAgent] Notatki strategiczne:\n{notes[:200]}...")

        return full_html, short_html

    except Exception as e:
        print(f"[OfferAgent] ❌ Błąd parsowania: {e}")
        print(f"[OfferAgent] Surowa odpowiedź:\n{content[:500]}...")
        raise
