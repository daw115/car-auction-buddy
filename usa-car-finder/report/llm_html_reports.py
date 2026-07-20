"""LLM-driven HTML report generation z dual provider (Gemini default + Anthropic fallback).

Wykorzystuje Claude (Anthropic SDK + RouteAI proxy) lub Gemini (Google AI Studio)
do generowania bogatych raportów HTML w stylu wzorca BMW M550i.

Provider dispatch przez env LLM_REPORTS_PROVIDER:
  - "gemini" (default) — DARMOWE w free tier (1500 RPD, 15 RPM)
  - "anthropic" — Claude Sonnet 4.6 przez RouteAI, lepsza jakość ale kosztuje

Skeleton wzorca (z usuniętymi base64 zdjęciami) jest cachowany — Anthropic ma
prompt caching (cache_control), Gemini ma context caching (jeszcze nie wszędzie).
"""
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from parser.models import AnalyzedLot, ClientCriteria
from report import llm_cache

logger = logging.getLogger("report.llm_html_reports")

# .env może być uruchamiany z różnych cwd (api, skrypty test'owe), więc szukamy explicite
_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=True)
else:
    load_dotenv(override=True)

_SKELETONS_DIR = Path(__file__).parent / "templates" / "llm_skeletons"
_CLIENT_SKELETON: Optional[str] = None
_BROKER_SKELETON: Optional[str] = None


def _load_skeleton(name: str) -> str:
    path = _SKELETONS_DIR / name
    if not path.exists():
        raise RuntimeError(f"Brak skeletonu LLM: {path}")
    return path.read_text(encoding="utf-8")


def _client_skeleton() -> str:
    global _CLIENT_SKELETON
    if _CLIENT_SKELETON is None:
        _CLIENT_SKELETON = _load_skeleton("klient_skeleton.html")
    return _CLIENT_SKELETON


def _broker_skeleton() -> str:
    global _BROKER_SKELETON
    if _BROKER_SKELETON is None:
        _BROKER_SKELETON = _load_skeleton("broker_skeleton.html")
    return _BROKER_SKELETON


def _lot_data_for_prompt(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None) -> str:
    """Spłaszcza AnalyzedLot do JSON który Claude czyta."""
    lot = item.lot
    ai = item.analysis
    payload = {
        "lot_id": lot.lot_id,
        "source": lot.source,
        "url": lot.url,
        "vin": lot.full_vin or lot.vin,
        "year": lot.year,
        "make": lot.make,
        "model": lot.model,
        "trim": lot.trim,
        "odometer_mi": lot.odometer_mi,
        "odometer_km": lot.odometer_km,
        "damage_primary": lot.damage_primary,
        "damage_secondary": lot.damage_secondary,
        "title_type": lot.title_type,
        "current_bid_usd": lot.current_bid_usd,
        "buy_now_price_usd": lot.buy_now_price_usd,
        "seller_reserve_usd": lot.seller_reserve_usd,
        "seller_type": lot.seller_type,
        "location_city": lot.location_city,
        "location_state": lot.location_state,
        "auction_date": lot.auction_date,
        "keys": lot.keys,
        "airbags_deployed": lot.airbags_deployed,
        "images": (lot.images or [])[:6],  # max 6 zdjęć
        "ai_score": ai.score,
        "ai_recommendation": ai.recommendation,
        "ai_red_flags": ai.red_flags or [],
        "ai_estimated_repair_usd": ai.estimated_repair_usd,
        "ai_estimated_total_cost_usd": ai.estimated_total_cost_usd,
        "ai_client_description_pl": ai.client_description_pl,
        "ai_notes": ai.ai_notes,
    }
    if criteria:
        payload["client_criteria"] = {
            "make": criteria.make,
            "model": criteria.model,
            "year_from": criteria.year_from,
            "year_to": criteria.year_to,
            "budget_usd": criteria.budget_usd,
            "max_odometer_mi": criteria.max_odometer_mi,
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _build_anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Brak ANTHROPIC_API_KEY (LLM raporty wymagają Claude API)")
    base_url = os.getenv("ANTHROPIC_BASE_URL") or None
    timeout = int(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "180"))
    kwargs = {"api_key": api_key, "timeout": timeout, "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def _system_prompt_client() -> str:
    return """Jesteś ekspertem od importu aut z USA. Generujesz spersonalizowane raporty HTML dla klientów na podstawie wzorca i danych konkretnego auta z aukcji Copart/IAAI.

ZASADY:
1. Zachowaj DOKŁADNIE strukturę HTML, CSS i sekcje wzorca (HERO, PHOTO, STATS, BODY → HEADLINE, STORY, SPEC, DAMAGE, TIMELINE, DOCS, CTA, FOOTER)
2. Zamień wszystkie dane BMW M550i z 2020 na dane TEGO auta
3. Storytelling po polsku w tonie podobnym do wzorca — entuzjazm techniczny, konkrety, kontekst rynku polskiego
4. Sekcja STORY powinna być rozbudowana (3-4 akapity per blok) — emocjonalna, obrazowa, bez frazesów
5. Liczby (przebieg km/mi, ceny w PLN i USD, koszty importu) — wszystko skalkuluj logicznie
6. PHOTO src zostaw jako URL pierwszego zdjęcia z lot.images (jeśli puste — placeholder)
7. ZWRÓĆ TYLKO kompletny HTML, bez markdown, bez ```html``` tagów, bez komentarzy poza HTMLem"""


def _system_prompt_broker() -> str:
    return """Jesteś ekspertem brokerskim importu aut z USA. Generujesz szczegółowe raporty techniczne HTML dla brokera (decyzje bidowania, scoring, koszty, ryzyka) na podstawie wzorca i danych konkretnego lotu.

ZASADY:
1. Zachowaj DOKŁADNIE strukturę HTML, CSS i sekcje wzorca (HEADER, STAT CARDS, PIPELINE, DANE LOTU, SCORING, KOSZTY, CZERWONE FLAGI, RAW COPART/IAAI, ZDJĘCIA, CHECKLIST, STRATEGIA LICYTACJI, NOTATKI STRATEGICZNE)
2. Zamień dane BMW M550i na dane TEGO auta
3. Sekcja SCORING — rozpisz konkretnie wagi i punktacje (lokalizacja +/-, damage +/-, title +/-, etc.)
4. Sekcja KOSZTY — pełna kalkulacja: bid + auction fee + transport USA→port + transport oceaniczny + cło + akcyza + VAT + homologacja + transport krajowy
5. STRATEGIA LICYTACJI — konkretne progi cenowe (wejścia, ostatecznej oferty), reasoning kiedy odpuścić
6. CZERWONE FLAGI — wykorzystaj ai_red_flags z danych + dodaj własne na podstawie damage/title/odometer/seller
7. Format profesjonalny, encyklopedyczny, bez emocji marketingu (to dla brokera, nie klienta)
8. ZWRÓĆ TYLKO kompletny HTML, bez markdown, bez ```html``` tagów"""


def _strip_html_wrapper(text: str) -> str:
    """Usuwa ewentualne markdown ```html``` wrapping które LLM mógł dorzucić."""
    text = text.strip()
    if text.startswith("```html"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _call_gemini_for_html(
    system: str,
    skeleton: str,
    lot_data: str,
    skeleton_label: str,
    max_tokens: int = 8192,
) -> str:
    """Generuje HTML przez Gemini API (free tier, 15 RPM, 1500 RPD)."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Brak GEMINI_API_KEY")
    model = os.getenv("GEMINI_REPORTS_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    timeout = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "180"))

    full_system = (
        f"{system}\n\nWZORZEC HTML ({skeleton_label}, dla BMW M550i 2020):\n\n{skeleton}"
    )
    user_prompt = (
        f"Wygeneruj kompletny raport HTML dla podanego auta zachowując strukturę wzorca.\n\n"
        f"DANE LOTU (do zastąpienia BMW M550i ze wzorca):\n```json\n{lot_data}\n```\n\n"
        f"Zwróć WYŁĄCZNIE HTML, gotowy do wyświetlenia w przeglądarce."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": full_system}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7,
        },
    }

    last_err: Exception = RuntimeError("Gemini: brak odpowiedzi")
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")[:500]
            if exc.code == 429 and attempt < 2:
                wait = 30 if attempt == 0 else 60
                print(f"[LLM-Reports] Gemini 429 ({skeleton_label}), wait {wait}s...")
                time.sleep(wait)
                last_err = RuntimeError(f"Gemini 429: rate limit")
                continue
            raise RuntimeError(f"Gemini HTTP {exc.code}: {err_body}") from exc
        except urllib.error.URLError as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(5)
                continue
            raise

        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Gemini brak candidates dla {skeleton_label}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if p.get("text"))
        if not text:
            finish = candidates[0].get("finishReason")
            raise RuntimeError(f"Gemini empty (finish={finish}) dla {skeleton_label}")
        return _strip_html_wrapper(text)
    raise last_err


def _provider() -> str:
    try:
        from api.settings_db import get_ai_provider_override
        override = get_ai_provider_override("llm_reports_provider")
        if override:
            return override.lower()
    except Exception as exc:
        logger.debug("[llm_html_reports] settings_db provider override lookup failed, using .env default: %s", exc)
    return (os.getenv("LLM_REPORTS_PROVIDER", "gemini") or "gemini").lower()


def _resolve_kiro_model() -> str:
    """Model Kiro: nadpisanie z dashboardu ma pierwszeństwo przed .env KIRO_MODEL."""
    try:
        from api.settings_db import get_ai_model_override
        override = get_ai_model_override("kiro")
        if override:
            return override
    except Exception as exc:
        logger.debug("[llm_html_reports] settings_db model override lookup failed, using .env default: %s", exc)
    return os.getenv("KIRO_MODEL", "claude-haiku-4.5")


def _call_kiro_for_html(
    system: str,
    skeleton: str,
    lot_data: str,
    skeleton_label: str,
    max_tokens: int = 8192,
) -> str:
    """Generuje HTML przez kiro-cli headless (KIRO_API_KEY, ksk_...)."""
    api_key = os.getenv("KIRO_API_KEY")
    if not api_key:
        raise RuntimeError("Brak KIRO_API_KEY")
    cli_path = os.getenv("KIRO_CLI_PATH", os.path.expanduser("~/.local/bin/kiro-cli"))
    effort = os.getenv("KIRO_EFFORT", "low")
    timeout = int(os.getenv("KIRO_TIMEOUT_SECONDS", "180"))
    model = _resolve_kiro_model()

    full_system = (
        f"{system}\n\nWZORZEC HTML ({skeleton_label}, dla BMW M550i 2020):\n\n{skeleton}"
    )
    user_prompt = (
        f"Wygeneruj kompletny raport HTML dla podanego auta zachowując strukturę wzorca.\n\n"
        f"DANE LOTU (do zastąpienia BMW M550i ze wzorca):\n```json\n{lot_data}\n```\n\n"
        f"Zwróć WYŁĄCZNIE HTML, gotowy do wyświetlenia w przeglądarce."
    )
    prompt = f"{full_system}\n\n{user_prompt}"
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
        raise RuntimeError(f"Kiro CLI timeout po {timeout}s dla {skeleton_label}") from exc

    if result.returncode != 0:
        raise RuntimeError(f"Kiro CLI exit {result.returncode} dla {skeleton_label}: {result.stderr[:300]}")

    text = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", result.stdout).strip()
    if not text:
        raise RuntimeError(f"Kiro CLI pusta odpowiedź dla {skeleton_label} (stderr: {result.stderr[:300]})")
    return _strip_html_wrapper(text)


def _call_llm(
    system: str, skeleton: str, lot_data: str, skeleton_label: str, max_tokens: int = 8192
) -> str:
    """Dispatch między Gemini (free, default), Kiro i Anthropic (paid, fallback) z retry on timeout."""
    provider = _provider()
    fallback_enabled = os.getenv("LLM_REPORTS_FALLBACK_ANTHROPIC", "true").lower() == "true"
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    max_retries = int(os.getenv("LLM_REPORTS_MAX_RETRIES", "2"))

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            if provider == "gemini":
                try:
                    return _call_gemini_for_html(system, skeleton, lot_data, skeleton_label, max_tokens)
                except Exception as gemini_exc:
                    if fallback_enabled and has_anthropic:
                        print(f"[LLM-Reports] Gemini failed ({type(gemini_exc).__name__}), fallback Anthropic")
                        return _call_claude_for_html(system, skeleton, lot_data, skeleton_label, max_tokens)
                    raise
            if provider == "kiro":
                try:
                    return _call_kiro_for_html(system, skeleton, lot_data, skeleton_label, max_tokens)
                except Exception as kiro_exc:
                    if fallback_enabled and has_anthropic:
                        print(f"[LLM-Reports] Kiro failed ({type(kiro_exc).__name__}), fallback Anthropic")
                        return _call_claude_for_html(system, skeleton, lot_data, skeleton_label, max_tokens)
                    raise
            return _call_claude_for_html(system, skeleton, lot_data, skeleton_label, max_tokens)
        except Exception as exc:
            last_exc = exc
            err_msg = str(exc)
            is_timeout = "timed out" in err_msg.lower() or "timeout" in err_msg.lower()
            is_retryable = is_timeout or "503" in err_msg or "529" in err_msg
            if attempt < max_retries - 1 and is_retryable:
                print(f"[LLM-Reports] {skeleton_label} attempt {attempt + 1}/{max_retries} failed ({type(exc).__name__}: {err_msg[:80]}), retry...")
                time.sleep(5)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("LLM call failed without exception")


def _call_claude_for_html(
    system: str,
    skeleton: str,
    lot_data: str,
    skeleton_label: str,
    max_tokens: int = 16000,
) -> str:
    client = _build_anthropic_client()
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[
            {"type": "text", "text": system},
            # Skeleton jako cached block — pierwsze wywołanie pełen koszt,
            # kolejne loty czytają z cache (5 min default, 1h gdy >5min między requestami)
            {
                "type": "text",
                "text": f"WZORZEC HTML ({skeleton_label}, dla BMW M550i 2020):\n\n{skeleton}",
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Wygeneruj kompletny raport HTML dla podanego auta zachowując strukturę wzorca.\n\n"
                    f"DANE LOTU (do zastąpienia BMW M550i ze wzorca):\n```json\n{lot_data}\n```\n\n"
                    f"Zwróć WYŁĄCZNIE HTML, gotowy do wyświetlenia w przeglądarce."
                ),
            }
        ],
    )

    chunks = [block.text for block in response.content if block.type == "text"]
    if not chunks:
        raise RuntimeError(f"Claude zwrócił pustą odpowiedź dla {skeleton_label}")
    return _strip_html_wrapper("".join(chunks))


def _fingerprint_payload(item: AnalyzedLot) -> dict:
    """Pola wpływające na output LLM — używane jako fingerprint dla cache."""
    lot = item.lot
    ai = item.analysis
    return {
        "ai_score": ai.score,
        "ai_recommendation": ai.recommendation,
        "current_bid_usd": lot.current_bid_usd,
        "buy_now_price_usd": lot.buy_now_price_usd,
        "ai_estimated_repair_usd": ai.estimated_repair_usd,
        "damage_primary": lot.damage_primary,
        "damage_secondary": lot.damage_secondary,
        "title_type": lot.title_type,
        "odometer_mi": lot.odometer_mi,
        "year": lot.year,
        "make": lot.make,
        "model": lot.model,
    }


def render_client_report_llm(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None) -> str:
    """Generuje raport HTML dla klienta przez LLM (Gemini default, Anthropic opcjonalnie).

    Cache (24h TTL): drugi klik dla tego samego lota = 0 ms, $0.
    """
    lot = item.lot
    fingerprint = llm_cache.make_fingerprint(_fingerprint_payload(item))

    cached = llm_cache.get_cached(
        lot_id=lot.lot_id, source=lot.source or "", kind="client_llm", fingerprint=fingerprint,
    )
    if cached:
        return cached

    # Gemini Flash ma cap 8192, Anthropic 16000+
    default_max = "8192" if _provider() == "gemini" else "16000"
    html = _call_llm(
        system=_system_prompt_client(),
        skeleton=_client_skeleton(),
        lot_data=_lot_data_for_prompt(item, criteria),
        skeleton_label="raport klienta",
        max_tokens=int(os.getenv("LLM_REPORT_MAX_TOKENS", default_max)),
    )
    llm_cache.store(
        lot_id=lot.lot_id, source=lot.source or "", kind="client_llm", fingerprint=fingerprint,
        html=html, provider=_provider(),
    )
    return html


def render_broker_report_llm(
    item: AnalyzedLot,
    criteria: Optional[ClientCriteria] = None,
    lots_scanned: int = 0,
) -> str:
    """Generuje raport brokerski HTML przez LLM (Gemini default, Anthropic opcjonalnie).

    Cache (24h TTL): drugi klik dla tego samego lota = 0 ms, $0.
    """
    lot = item.lot
    fingerprint = llm_cache.make_fingerprint(_fingerprint_payload(item))

    cached = llm_cache.get_cached(
        lot_id=lot.lot_id, source=lot.source or "", kind="broker_llm", fingerprint=fingerprint,
    )
    if cached:
        return cached

    lot_data = _lot_data_for_prompt(item, criteria)
    if lots_scanned:
        lot_data = lot_data.rstrip().rstrip("}") + f',\n  "lots_scanned": {lots_scanned}\n}}'
    default_max = "8192" if _provider() == "gemini" else "16000"
    html = _call_llm(
        system=_system_prompt_broker(),
        skeleton=_broker_skeleton(),
        lot_data=lot_data,
        skeleton_label="raport brokerski",
        max_tokens=int(os.getenv("LLM_REPORT_MAX_TOKENS", default_max)),
    )
    llm_cache.store(
        lot_id=lot.lot_id, source=lot.source or "", kind="broker_llm", fingerprint=fingerprint,
        html=html, provider=_provider(),
    )
    return html
