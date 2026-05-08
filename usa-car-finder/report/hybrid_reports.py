"""Hybrid renderer: Jinja2 (struktura + dane + koszty) + LLM (JSON storytelling).

ZASADA: LLM dostaje malutki prompt i zwraca JSON z 4-7 fragmentami tekstu.
Python wkleja te fragmenty w template Jinja2. Wynik:
- input ~500 tok (vs ~10k przed)
- output ~800-1500 tok (vs ~4-8k przed)
- Koszt: $0.014 (klient) / $0.027 (broker) — ~30× taniej

Kompatybilne z cache (llm_cache.py) — fingerprint identyczny, wynik HTML też.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

from parser.models import AnalyzedLot, ClientCriteria
from report import llm_cache
from report.cost_calculator import calculate_full_cost
from scraper.otomoto import lookup_market_price

logger = logging.getLogger("report.hybrid_reports")

# Load .env (różne cwd przy testach/skryptach)
_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=True)
else:
    load_dotenv(override=True)

_TEMPLATES_DIR = Path(__file__).parent / "templates" / "hybrid"
_jinja_env: Optional[Environment] = None


def _env() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _jinja_env


# ============================================================================
# LLM call (mini, JSON-only)
# ============================================================================

def _provider() -> str:
    return (os.getenv("LLM_REPORTS_PROVIDER", "gemini") or "gemini").lower()


def _engine_liters_from_trim(trim: Optional[str], make: Optional[str], model: Optional[str]) -> Optional[float]:
    """Heurystyka: spróbuj wyciągnąć pojemność silnika z trim/model. Default 2.0L."""
    if not trim:
        return 2.0
    t = trim.lower()
    # Common patterns: "5.0L V8", "3.5T", "2.0T", "1.6", "TDI"
    import re
    m = re.search(r"(\d\.\d)\s*[lt]?", t)
    if m:
        try:
            v = float(m.group(1))
            if 0.8 <= v <= 8.0:
                return v
        except ValueError:
            pass
    # Heuristic for known V6/V8/V10/V12
    if "v8" in t or "m5" in t or "m550" in t or "amg" in t:
        return 4.4
    if "v6" in t:
        return 3.0
    return 2.0


def _build_anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Brak ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL") or None
    timeout = int(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "120"))
    kwargs = {"api_key": api_key, "timeout": timeout, "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


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
        raise RuntimeError(f"JSON parse failed even with loose mode: {e}; sanitized[:300]={raw_sanitized[:300]!r}")


def _call_gemini_json(system: str, user: str, max_tokens: int = 1500) -> dict:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Brak GEMINI_API_KEY")
    model = os.getenv("GEMINI_REPORTS_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    timeout = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    # thinkingBudget=0 wyłącza "thinking mode" w Gemini 2.5 (Flash/Pro). Bez tego thinking
    # tokens zjadają output budget → finishReason=MAX_TOKENS → empty text → fallback Anthropic.
    # Override: ustaw GEMINI_THINKING_BUDGET na liczbę >0 żeby pozwolić na thinking.
    thinking_budget = int(os.getenv("GEMINI_THINKING_BUDGET", "0"))
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": thinking_budget},
        },
    }

    last_err: Exception = RuntimeError("Gemini brak odpowiedzi")
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")[:500]
            if exc.code == 429 and attempt < 2:
                wait = 30 if attempt == 0 else 60
                logger.info(f"[Hybrid] Gemini 429, wait {wait}s")
                time.sleep(wait)
                last_err = RuntimeError(f"Gemini 429")
                continue
            raise RuntimeError(f"Gemini HTTP {exc.code}: {err_body}") from exc
        except urllib.error.URLError as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(3)
                continue
            raise

        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini brak candidates")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if p.get("text"))
        if not text:
            finish = candidates[0].get("finishReason")
            raise RuntimeError(f"Gemini empty (finish={finish})")
        try:
            return _parse_json_loose(text)
        except RuntimeError as e:
            raise RuntimeError(f"Gemini JSON parse failed: {e}")
    raise last_err


def _call_claude_json(system: str, user: str, max_tokens: int = 1500) -> dict:
    client = _build_anthropic_client()
    # Hybrid uses cheaper model — storytelling nie wymaga Sonneta
    model = os.getenv("ANTHROPIC_HYBRID_MODEL", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"))
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    chunks = [block.text for block in response.content if block.type == "text"]
    if not chunks:
        raise RuntimeError("Claude empty response")
    raw = "".join(chunks)
    try:
        return _parse_json_loose(raw)
    except RuntimeError as e:
        raise RuntimeError(f"Claude JSON parse failed: {e}")


def _call_llm_json(system: str, user: str, max_tokens: int = 1500) -> dict:
    """Provider dispatch z fallback."""
    provider = _provider()
    fallback = os.getenv("LLM_REPORTS_FALLBACK_ANTHROPIC", "true").lower() == "true"
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    max_retries = int(os.getenv("LLM_REPORTS_MAX_RETRIES", "2"))

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            if provider == "gemini":
                try:
                    return _call_gemini_json(system, user, max_tokens)
                except Exception as ge:
                    if fallback and has_anthropic:
                        logger.warning(f"[Hybrid] Gemini failed ({type(ge).__name__}), fallback Anthropic")
                        return _call_claude_json(system, user, max_tokens)
                    raise
            return _call_claude_json(system, user, max_tokens)
        except Exception as exc:
            last_exc = exc
            err = str(exc).lower()
            if attempt < max_retries - 1 and ("timeout" in err or "timed out" in err or "503" in err or "529" in err):
                logger.info(f"[Hybrid] retry {attempt+1}/{max_retries}: {type(exc).__name__}")
                time.sleep(3)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("Hybrid LLM call failed without exception")


# ============================================================================
# Prompts (krótkie, zwracają JSON)
# ============================================================================

CLIENT_SYSTEM = """Jesteś ekspertem od importu aut z USA. Generujesz spersonalizowane fragmenty raportu dla klienta polskiego.
Zwracasz WYŁĄCZNIE poprawny JSON, bez markdown, bez ```json``` tagów."""

CLIENT_USER_TEMPLATE = """Wygeneruj fragmenty raportu klienta po polsku. RYGORYSTYCZNIE trzymaj się limitów znaków.

Zwróć JSON o schemacie:
{{
  "tagline": "MAX 140 znaków — 1 hook'owe zdanie",
  "story_paragraphs": [
    "MAX 350 znaków — kontekst auta",
    "MAX 400 znaków — stan techniczny",
    "MAX 350 znaków — szansa rynkowa w PL"
  ],
  "red_flags": ["MAX 120 znaków każdy", "max 4 elementy"],
  "verdict_color": "green | amber | red",
  "verdict_headline": "MAX 80 znaków",
  "verdict_pl": "MAX 350 znaków — 2-3 zdania"
}}

DANE AUTA:
{lot_data}

ZASADY (TWARDE):
- KAŻDE pole MUSI mieścić się w limicie znaków — przekroczenie = błąd
- verdict_color: green=POLECAM (>=7), amber=RYZYKO (4-7), red=ODRZUĆ (<4)
- Konkrety: rok, marka, model, koszt, przebieg — bez frazesów
- Nie kłam, nie marketinguj nadmiernie"""


PAIR_SYSTEM = """Jesteś ekspertem importu aut z USA. Generujesz JEDNOCZEŚNIE fragmenty raportu dla:
- KLIENTA polskiego (emocjonalny storytelling, verdict)
- BROKERA (decyzje bidowania, scoring techniczny)

Zwracasz WYŁĄCZNIE poprawny JSON z dwoma sekcjami {"client": {...}, "broker": {...}}, bez markdown."""

PAIR_USER_TEMPLATE = """Dla auta poniżej wygeneruj OBA zestawy fragmentów PO POLSKU. Zwróć JSON:
{{
  "client": {{
    "tagline": "MAX 140 znaków — 1 hook'owe zdanie",
    "story_paragraphs": [
      "MAX 350 znaków — kontekst auta",
      "MAX 400 znaków — stan techniczny",
      "MAX 350 znaków — szansa rynkowa w PL"
    ],
    "red_flags": ["MAX 120 znaków każdy", "max 4"],
    "verdict_color": "green | amber | red",
    "verdict_headline": "MAX 80 znaków",
    "verdict_pl": "MAX 350 znaków — 2-3 zdania"
  }},
  "broker": {{
    "scoring_breakdown": [
      {{"category": "Damage", "points": -2, "reason": "krótkie"}},
      {{"category": "Title", "points": 0, "reason": "..."}},
      {{"category": "Odometer", "points": 1, "reason": "..."}},
      {{"category": "Location", "points": -1, "reason": "..."}},
      {{"category": "Seller type", "points": 2, "reason": "..."}},
      {{"category": "Market fit", "points": 1, "reason": "..."}}
    ],
    "red_flags": [
      {{"severity": "HIGH | MID | LOW", "text": "max 150 znaków"}}
    ],
    "bid_thresholds": {{
      "entry_usd": 8000,
      "target_usd": 10000,
      "walkaway_usd": 12500
    }},
    "bidding_strategy": "3-4 zdania konkretnej strategii (kiedy wejść, kiedy odpuścić), max 600 znaków",
    "checklist": [
      {{"label": "VIN check (Carfax/Autocheck)", "status": "ok | warn | bad", "note": "max 80"}},
      {{"label": "Inspection report", "status": "warn", "note": "..."}}
    ],
    "notes_pl": "3-5 zdań notatek strategicznych, max 700 znaków"
  }}
}}

DANE AUTA + KOSZTY:
{lot_data}

ZASADY:
- KLIENT: każde pole w limicie. verdict_color: green=POLECAM(>=7), amber=RYZYKO(4-7), red=ODRZUĆ(<4)
- BROKER: 6 kategorii scoring (-3 do +3), 4-7 checklist, entry < target < walkaway
- Spójność między sekcjami: client.verdict_color musi pasować do AI score
- Bez markdown, bez ```json```. Zwróć od razu otwarte {{ ... }}"""


BROKER_SYSTEM = """Jesteś ekspertem brokerskim importu aut z USA. Generujesz fragmenty briefa technicznego dla brokera (decyzje bidowania).
Zwracasz WYŁĄCZNIE poprawny JSON, bez markdown."""

BROKER_USER_TEMPLATE = """Dla auta opisanego poniżej wygeneruj fragmenty briefa brokerskiego po polsku. Zwróć JSON o schemacie:
{{
  "scoring_breakdown": [
    {{"category": "Damage", "points": -2, "reason": "krótkie uzasadnienie"}},
    {{"category": "Title", "points": 0, "reason": "..."}},
    {{"category": "Odometer", "points": +1, "reason": "..."}},
    {{"category": "Location", "points": -1, "reason": "..."}},
    {{"category": "Seller type", "points": +2, "reason": "..."}},
    {{"category": "Market fit", "points": +1, "reason": "..."}}
  ],
  "red_flags": [
    {{"severity": "HIGH | MID | LOW", "text": "konkretna obserwacja max 150 znaków"}}
  ],
  "bid_thresholds": {{
    "entry_usd": 8000,
    "target_usd": 10000,
    "walkaway_usd": 12500
  }},
  "bidding_strategy": "3-4 zdania konkretnej strategii (kiedy wejść, kiedy zwiększyć, kiedy odpuścić, max 600 znaków)",
  "checklist": [
    {{"label": "VIN check (Carfax/Autocheck)", "status": "ok | warn | bad", "note": "opcjonalna notka max 80 znaków"}},
    {{"label": "Inspection report", "status": "warn", "note": "..."}}
  ],
  "notes_pl": "3-5 zdań notatek strategicznych (jak licytować, czego unikać, czemu warto/nie warto, max 700 znaków)"
}}

DANE LOTU + KOSZTY:
{lot_data}

ZASADY:
- scoring_breakdown: 6 kategorii, punkty -3 do +3, suma powinna być spójna z AI score
- bid_thresholds: entry < target < walkaway, walkaway typowo target+25%
- checklist: 4-7 punktów technicznych (VIN, inspection, photos quality, transport ready, title clear, mileage check)
- notes_pl: konkretnie, bez ogólników, brokerski ton"""


# ============================================================================
# Helper: lot data dla LLM (mały JSON, bez images)
# ============================================================================

def _lot_data_compact(item: AnalyzedLot, criteria: Optional[ClientCriteria], cost: dict, market_pl: Optional[dict] = None) -> str:
    lot = item.lot
    ai = item.analysis
    payload = {
        "year": lot.year,
        "make": lot.make,
        "model": lot.model,
        "trim": lot.trim,
        "odometer_mi": lot.odometer_mi,
        "damage_primary": lot.damage_primary,
        "damage_secondary": lot.damage_secondary,
        "title": lot.title_type,
        "current_bid_usd": lot.current_bid_usd,
        "buy_now_usd": lot.buy_now_price_usd,
        "location": f"{lot.location_city or ''}, {lot.location_state or ''}".strip(", "),
        "seller_type": lot.seller_type,
        "keys": lot.keys,
        "airbags_deployed": lot.airbags_deployed,
        "ai_score": ai.score,
        "ai_recommendation": ai.recommendation,
        "ai_red_flags": ai.red_flags or [],
        "ai_description": ai.client_description_pl,
        "ai_notes": ai.ai_notes,
        "total_cost_to_pl_pln": cost["grand_total_pln"],
        "total_cost_to_pl_usd": cost["grand_total_usd"],
    }
    if market_pl:
        payload["market_price_pl"] = {
            "low_pln": market_pl.get("low_pln"),
            "high_pln": market_pl.get("high_pln"),
            "mean_pln": market_pl.get("mean_pln"),
            "median_pln": market_pl.get("median_pln"),
            "sample_size": market_pl.get("sample_size"),
            "source": "Otomoto.pl",
        }
    if criteria:
        payload["client_budget_usd"] = criteria.budget_usd
        payload["client_max_odometer_mi"] = criteria.max_odometer_mi
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _budget_delta_pct(bid: Optional[float], budget: Optional[float]) -> int:
    if not bid or not budget or budget <= 0:
        return 0
    return int(round((budget - bid) / budget * 100))


# ============================================================================
# Public renderers
# ============================================================================

def render_client_hybrid(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None) -> str:
    """Hybrydowy raport klienta: ~$0.014/call (Gemini free = $0).

    Split-cache (Faza 2D): preferuje JSON skeleton (LLM output) z cache i
    re-renderuje Jinja2 z fresh cost/market_pl/today. Tylko gdy skeleton MISS,
    odpala LLM call. CSS-only changes = instant Jinja2 rerender bez kosztu.
    """
    lot = item.lot
    ai = item.analysis

    # Cache fingerprint
    fingerprint_payload = {
        "ai_score": ai.score, "ai_recommendation": ai.recommendation,
        "current_bid_usd": lot.current_bid_usd, "buy_now_price_usd": lot.buy_now_price_usd,
        "ai_estimated_repair_usd": ai.estimated_repair_usd,
        "damage_primary": lot.damage_primary, "damage_secondary": lot.damage_secondary,
        "title_type": lot.title_type, "odometer_mi": lot.odometer_mi,
        "year": lot.year, "make": lot.make, "model": lot.model,
        "_kind": "client_hybrid_v1",
    }
    fp = llm_cache.make_fingerprint(fingerprint_payload)

    # 1) Liczymy koszty (zawsze — szybko, deterministycznie)
    engine_l = _engine_liters_from_trim(lot.trim, lot.make, lot.model)
    cost = calculate_full_cost(
        bid_usd=lot.current_bid_usd or lot.buy_now_price_usd or 0,
        engine_liters=engine_l,
        location_state=lot.location_state,
        repair_estimate_usd=ai.estimated_repair_usd,
    )

    # 2) Lookup ceny rynkowej PL z Otomoto (cache 7 dni, ~0ms HIT, ~8s MISS)
    market_pl = None
    try:
        if lot.make and lot.model and os.getenv("OTOMOTO_LOOKUP_ENABLED", "true").lower() == "true":
            market_pl = lookup_market_price(
                make=lot.make,
                model=lot.model,
                year_from=(lot.year - 1) if lot.year else None,
                year_to=(lot.year + 1) if lot.year else None,
            )
    except Exception:
        logger.exception("[Hybrid] Otomoto lookup failed (non-fatal)")
        market_pl = None

    # 3) Skeleton cache check (split cache v2): jeśli LLM JSON jest cached → re-render Jinja2 only
    fragments = llm_cache.get_cached_skeleton(lot.lot_id, lot.source or "", "client_hybrid", fp)
    if fragments is None:
        # Mini-LLM call dla storytellingu (JSON)
        user_prompt = CLIENT_USER_TEMPLATE.format(lot_data=_lot_data_compact(item, criteria, cost, market_pl))
        fragments = _call_llm_json(
            system=CLIENT_SYSTEM,
            user=user_prompt,
            max_tokens=int(os.getenv("HYBRID_CLIENT_MAX_TOKENS", "2500")),
        )
        skeleton_was_cached = False
    else:
        skeleton_was_cached = True

    # 4) Render template (zawsze fresh — Jinja2 + dzisiejsze dane)
    template = _env().get_template("client_hybrid.html.j2")
    html = template.render(
        lot=lot,
        ai=ai,
        cost=cost,
        market_pl=market_pl,
        tagline=fragments.get("tagline", ""),
        story_paragraphs=fragments.get("story_paragraphs", []),
        red_flags=fragments.get("red_flags", ai.red_flags or []),
        verdict_color=fragments.get("verdict_color", "amber"),
        verdict_headline=fragments.get("verdict_headline", ""),
        verdict_pl=fragments.get("verdict_pl", ai.client_description_pl or ""),
        today=datetime.utcnow().strftime("%Y-%m-%d"),
        provider=_provider(),
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash") if _provider() == "gemini" else os.getenv("ANTHROPIC_MODEL"),
        generated_at=datetime.utcnow().isoformat(timespec="seconds"),
    )

    # 5) Store skeleton + html (skeleton tylko jeśli nowy LLM call)
    if not skeleton_was_cached:
        llm_cache.store_skeleton(lot.lot_id, lot.source or "", "client_hybrid", fp, fragments,
                                 html=html, provider=_provider())
    else:
        # Skeleton już cached, zapisujemy tylko HTML (np. po CSS change)
        llm_cache.store(lot.lot_id, lot.source or "", "client_hybrid", fp, html, provider=_provider())
    return html


def render_broker_hybrid(
    item: AnalyzedLot,
    criteria: Optional[ClientCriteria] = None,
    lots_scanned: int = 0,
) -> str:
    """Hybrydowy raport brokerski: ~$0.027/call (Gemini free = $0)."""
    lot = item.lot
    ai = item.analysis

    # Cache
    fingerprint_payload = {
        "ai_score": ai.score, "ai_recommendation": ai.recommendation,
        "current_bid_usd": lot.current_bid_usd, "buy_now_price_usd": lot.buy_now_price_usd,
        "ai_estimated_repair_usd": ai.estimated_repair_usd,
        "damage_primary": lot.damage_primary, "damage_secondary": lot.damage_secondary,
        "title_type": lot.title_type, "odometer_mi": lot.odometer_mi,
        "year": lot.year, "make": lot.make, "model": lot.model,
        "lots_scanned": lots_scanned,
        "_kind": "broker_hybrid_v1",
    }
    fp = llm_cache.make_fingerprint(fingerprint_payload)

    engine_l = _engine_liters_from_trim(lot.trim, lot.make, lot.model)
    cost = calculate_full_cost(
        bid_usd=lot.current_bid_usd or lot.buy_now_price_usd or 0,
        engine_liters=engine_l,
        location_state=lot.location_state,
        repair_estimate_usd=ai.estimated_repair_usd,
    )

    # Lookup ceny rynkowej PL z Otomoto (cache 7 dni)
    market_pl = None
    try:
        if lot.make and lot.model and os.getenv("OTOMOTO_LOOKUP_ENABLED", "true").lower() == "true":
            market_pl = lookup_market_price(
                make=lot.make,
                model=lot.model,
                year_from=(lot.year - 1) if lot.year else None,
                year_to=(lot.year + 1) if lot.year else None,
            )
    except Exception:
        logger.exception("[Hybrid] Otomoto lookup failed (non-fatal)")
        market_pl = None

    # Skeleton cache check (split cache v2)
    fragments = llm_cache.get_cached_skeleton(lot.lot_id, lot.source or "", "broker_hybrid", fp)
    if fragments is None:
        user_prompt = BROKER_USER_TEMPLATE.format(lot_data=_lot_data_compact(item, criteria, cost, market_pl))
        fragments = _call_llm_json(
            system=BROKER_SYSTEM,
            user=user_prompt,
            max_tokens=int(os.getenv("HYBRID_BROKER_MAX_TOKENS", "3500")),
        )
        skeleton_was_cached = False
    else:
        skeleton_was_cached = True

    # Walk-away fallback gdy LLM nie poda lub poda absurd
    bt = fragments.get("bid_thresholds") or {}
    bid_now = int(lot.current_bid_usd or lot.buy_now_price_usd or 0)
    if not bt.get("entry_usd") or bt["entry_usd"] <= 0:
        bt = {
            "entry_usd": int(bid_now * 0.85) if bid_now else 5000,
            "target_usd": int(bid_now * 1.0) if bid_now else 7500,
            "walkaway_usd": int(bid_now * 1.25) if bid_now else 10000,
        }

    template = _env().get_template("broker_hybrid.html.j2")
    html = template.render(
        lot=lot,
        ai=ai,
        cost=cost,
        market_pl=market_pl,
        lots_scanned=lots_scanned,
        budget_delta_pct=_budget_delta_pct(lot.current_bid_usd, criteria.budget_usd if criteria else None),
        scoring_breakdown=fragments.get("scoring_breakdown", []),
        red_flags=fragments.get("red_flags", []),
        bid_thresholds=bt,
        bidding_strategy=fragments.get("bidding_strategy", ai.ai_notes or ""),
        checklist=fragments.get("checklist", []),
        notes_pl=fragments.get("notes_pl", ai.ai_notes or ai.client_description_pl or ""),
        provider=_provider(),
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash") if _provider() == "gemini" else os.getenv("ANTHROPIC_MODEL"),
        generated_at=datetime.utcnow().isoformat(timespec="seconds"),
        cache_status="HIT" if skeleton_was_cached else "MISS",
    )
    if not skeleton_was_cached:
        llm_cache.store_skeleton(lot.lot_id, lot.source or "", "broker_hybrid", fp, fragments,
                                 html=html, provider=_provider())
    else:
        llm_cache.store(lot.lot_id, lot.source or "", "broker_hybrid", fp, html, provider=_provider())
    return html


# ============================================================================
# Faza 3F: Combined client+broker w 1 LLM call (50% mniej calli)
# ============================================================================

def render_pair_hybrid(
    item: AnalyzedLot,
    criteria: Optional[ClientCriteria] = None,
    lots_scanned: int = 0,
) -> tuple[str, str]:
    """Renderuje (client_html, broker_html) z 1 LLM call zamiast 2.

    Single prompt zwraca {"client": {...}, "broker": {...}} → split → render obu
    template Jinja2. Cache strategy: kind="pair_hybrid" trzyma combined skeleton;
    jeśli HIT → 0 LLM, tylko 2× Jinja2.

    Backward compat: render_client_hybrid / render_broker_hybrid wciąż działają
    osobno (regen single-kind, manual on-demand). Główny scrape pipeline używa
    render_pair_hybrid dla 50% redukcji LLM RPM.
    """
    lot = item.lot
    ai = item.analysis

    fingerprint_payload = {
        "ai_score": ai.score, "ai_recommendation": ai.recommendation,
        "current_bid_usd": lot.current_bid_usd, "buy_now_price_usd": lot.buy_now_price_usd,
        "ai_estimated_repair_usd": ai.estimated_repair_usd,
        "damage_primary": lot.damage_primary, "damage_secondary": lot.damage_secondary,
        "title_type": lot.title_type, "odometer_mi": lot.odometer_mi,
        "year": lot.year, "make": lot.make, "model": lot.model,
        "lots_scanned": lots_scanned,
        "_kind": "pair_hybrid_v1",
    }
    fp = llm_cache.make_fingerprint(fingerprint_payload)

    # Koszty + Otomoto (raz, shared dla obu HTMLi)
    engine_l = _engine_liters_from_trim(lot.trim, lot.make, lot.model)
    cost = calculate_full_cost(
        bid_usd=lot.current_bid_usd or lot.buy_now_price_usd or 0,
        engine_liters=engine_l,
        location_state=lot.location_state,
        repair_estimate_usd=ai.estimated_repair_usd,
    )
    market_pl = None
    try:
        if lot.make and lot.model and os.getenv("OTOMOTO_LOOKUP_ENABLED", "true").lower() == "true":
            market_pl = lookup_market_price(
                make=lot.make,
                model=lot.model,
                year_from=(lot.year - 1) if lot.year else None,
                year_to=(lot.year + 1) if lot.year else None,
            )
    except Exception:
        logger.exception("[Hybrid pair] Otomoto lookup failed (non-fatal)")
        market_pl = None

    # Skeleton cache check
    pair_fragments = llm_cache.get_cached_skeleton(lot.lot_id, lot.source or "", "pair_hybrid", fp)
    if pair_fragments is None:
        # Single LLM call dla obu sekcji
        user_prompt = PAIR_USER_TEMPLATE.format(lot_data=_lot_data_compact(item, criteria, cost, market_pl))
        max_tokens = int(os.getenv("HYBRID_PAIR_MAX_TOKENS", "6000"))
        pair_fragments = _call_llm_json(
            system=PAIR_SYSTEM,
            user=user_prompt,
            max_tokens=max_tokens,
        )
        skeleton_was_cached = False
    else:
        skeleton_was_cached = True

    client_frag = pair_fragments.get("client") or {}
    broker_frag = pair_fragments.get("broker") or {}

    # Walk-away fallback dla broker bid_thresholds
    bt = broker_frag.get("bid_thresholds") or {}
    bid_now = int(lot.current_bid_usd or lot.buy_now_price_usd or 0)
    if not bt.get("entry_usd") or bt["entry_usd"] <= 0:
        bt = {
            "entry_usd": int(bid_now * 0.85) if bid_now else 5000,
            "target_usd": int(bid_now * 1.0) if bid_now else 7500,
            "walkaway_usd": int(bid_now * 1.25) if bid_now else 10000,
        }

    # Render KLIENT
    client_template = _env().get_template("client_hybrid.html.j2")
    client_html = client_template.render(
        lot=lot, ai=ai, cost=cost, market_pl=market_pl,
        tagline=client_frag.get("tagline", ""),
        story_paragraphs=client_frag.get("story_paragraphs", []),
        red_flags=client_frag.get("red_flags", ai.red_flags or []),
        verdict_color=client_frag.get("verdict_color", "amber"),
        verdict_headline=client_frag.get("verdict_headline", ""),
        verdict_pl=client_frag.get("verdict_pl", ai.client_description_pl or ""),
        today=datetime.utcnow().strftime("%Y-%m-%d"),
        provider=_provider(),
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash") if _provider() == "gemini" else os.getenv("ANTHROPIC_MODEL"),
        generated_at=datetime.utcnow().isoformat(timespec="seconds"),
    )

    # Render BROKER
    broker_template = _env().get_template("broker_hybrid.html.j2")
    broker_html = broker_template.render(
        lot=lot, ai=ai, cost=cost, market_pl=market_pl,
        lots_scanned=lots_scanned,
        budget_delta_pct=_budget_delta_pct(lot.current_bid_usd, criteria.budget_usd if criteria else None),
        scoring_breakdown=broker_frag.get("scoring_breakdown", []),
        red_flags=broker_frag.get("red_flags", []),
        bid_thresholds=bt,
        bidding_strategy=broker_frag.get("bidding_strategy", ai.ai_notes or ""),
        checklist=broker_frag.get("checklist", []),
        notes_pl=broker_frag.get("notes_pl", ai.ai_notes or ai.client_description_pl or ""),
        provider=_provider(),
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash") if _provider() == "gemini" else os.getenv("ANTHROPIC_MODEL"),
        generated_at=datetime.utcnow().isoformat(timespec="seconds"),
        cache_status="HIT" if skeleton_was_cached else "MISS",
    )

    # Cache: pair skeleton (i — opcjonalnie — populuje cache osobnych kindów dla single-kind regen).
    if not skeleton_was_cached:
        llm_cache.store_skeleton(lot.lot_id, lot.source or "", "pair_hybrid", fp, pair_fragments,
                                 html="", provider=_provider())  # html="" bo trzymamy oba osobno
        # Bonus: zapisz też kindy single-kind żeby regen klient-only / broker-only też miał HIT
        try:
            single_fp_client = llm_cache.make_fingerprint({**fingerprint_payload, "_kind": "client_hybrid_v1"})
            single_fp_broker = llm_cache.make_fingerprint({**fingerprint_payload, "_kind": "broker_hybrid_v1"})
            llm_cache.store_skeleton(lot.lot_id, lot.source or "", "client_hybrid", single_fp_client,
                                     client_frag, html=client_html, provider=_provider())
            llm_cache.store_skeleton(lot.lot_id, lot.source or "", "broker_hybrid", single_fp_broker,
                                     broker_frag, html=broker_html, provider=_provider())
        except Exception:
            logger.exception("[Hybrid pair] failed to mirror to single-kind cache (non-fatal)")
    else:
        llm_cache.store(lot.lot_id, lot.source or "", "client_hybrid", fp, client_html, provider=_provider())
        llm_cache.store(lot.lot_id, lot.source or "", "broker_hybrid", fp, broker_html, provider=_provider())

    return client_html, broker_html
