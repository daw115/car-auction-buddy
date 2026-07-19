"""Vision-based detection uszkodzenia belki (frame rail / structural beam) z fotografii lota.

Trigger:
  - lot.damage_primary zawiera 'FRONT' lub 'REAR' (czyli kandydat do POLECAM/RYZYKO,
    ale belka konstrukcyjna może go zdyskwalifikować)
  - lot ma co najmniej 2 zdjęcia (lot.images)

Strategia:
  1. Wybierz max 4 zdjęcia (oszczędność tokenów Claude vision)
  2. Wyślij do Claude z explicit prompt o belkę
  3. Parsuj JSON: {frame_damaged: bool, confidence: float, reason: str}
  4. Cache wynik per VIN w data/frame_damage_cache.json (TTL 60 dni)
     — ten sam VIN nie wymaga re-analizy przy następnym scrape

Side-effect: ustawia lot.raw_data['frame_damage_check'] = {
    'frame_damaged': bool,
    'confidence': float (0.0-1.0),
    'reason': str,
    'checked_via': 'vision' | 'cache',
}

Koszt: ~$0.02 per lot z 4 zdjęciami (Claude Sonnet vision input ~6k tokens + 200 out).
Per scrape z 5 FRONT/REAR kandydatami = ~$0.10.

Opt-in via env: FRAME_DAMAGE_VISION_ENABLED=true (default true gdy ANTHROPIC_API_KEY).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import anthropic

from parser.models import CarLot

logger = logging.getLogger("ai.frame_damage_vision")

CACHE_PATH = Path(os.getenv("FRAME_DAMAGE_CACHE_PATH", "data/frame_damage_cache.json"))
CACHE_TTL_DAYS = int(os.getenv("FRAME_DAMAGE_CACHE_TTL_DAYS", "60"))
MAX_IMAGES = int(os.getenv("FRAME_DAMAGE_MAX_IMAGES", "4"))

# Trigger keywords w damage_primary (case-insensitive)
TRIGGER_KEYWORDS = ("FRONT", "REAR", "PRZÓD", "TYŁ")


SYSTEM_PROMPT = """You are a vehicle structural damage assessor specialized in salvage car imports. Reply with raw JSON only, no prose."""


USER_TEMPLATE = """Oceń uszkodzenia konstrukcyjne (belka rama / frame rail / structural beam) na zdjęciach pojazdu.

Pojazd: {year} {make} {model}
Uszkodzenie zgłoszone w aukcji: {damage_primary}

ZADANIE:
Sprawdź czy widoczne na zdjęciach uszkodzenie obejmuje belkę konstrukcyjną (rama, lonżeryny, przedłużenia ram, podszybie, słupki). Belka uszkodzona = pojazd wymaga prostowania na ramie / spawania konstrukcji nośnej, co zwykle dyskwalifikuje przy imporcie do Polski (homologacja, ryzyko niezgodności z VIN).

CO LICZY SIĘ JAKO USZKODZENIE BELKI:
- Skręcona/zgięta belka przednia lub tylna (frame rail bend)
- Widoczne złamania / rozerwania konstrukcji nośnej
- Deformacja słupków A/B/C
- Wgnioty/falowanie podłogi/podsufitki (sugeruje przesunięcie ramy)
- Zerwane mocowania zawieszenia od konstrukcji
- Crush zone głębsze niż zderzak/kompozyt (tj. ramowo zerwane)

CO NIE JEST USZKODZENIEM BELKI (akceptowalne):
- Tylko zderzak/maska/plastik (panel damage)
- Krzywe drzwi (paneliarka)
- Stłuczone reflektory/lampy
- Lekkie wgniecenia karoserii
- Brak zderzaka (kosmetyka)

ZWRÓĆ RAW JSON (pierwszy znak `{{`, ostatni `}}`, bez markdown/prozy):
{{
  "frame_damaged": true,
  "confidence": 0.85,
  "reason": "Wyraźnie wygięta belka przednia lewa, sugeruje wymaganie prostowania ramy"
}}

ZASADY:
- `frame_damaged`: true gdy belka uszkodzona/podejrzana; false gdy tylko panel damage; true przy unclear/wysokiej niepewności (safety bias dla broker'a importowego — lepiej odrzucić niewyraźne).
- `confidence`: 0.0-1.0; im wyżej tym pewniejsza decyzja na podstawie zdjęć.
- `reason`: 1 zdanie po polsku z konkretami (np. "widoczne wygięcie ramy przedniej prawej").
- Gdy zdjęcia są niedostateczne (brak crucial view) → `frame_damaged=true, confidence<0.5, reason="Brak zdjęć diagnostycznych — recommend skip"`.
"""


def _load_cache() -> dict:
    """Loaduj cache z JSON file. Cleanup expired entries inline."""
    if not CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    now = time.time()
    ttl_seconds = CACHE_TTL_DAYS * 86400
    cleaned = {
        vin: entry
        for vin, entry in data.items()
        if isinstance(entry, dict) and (now - entry.get("checked_at", 0)) < ttl_seconds
    }
    return cleaned


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("[frame_damage] cache save failed: %s", exc)


def should_check_frame(lot: CarLot) -> bool:
    """True gdy lot kwalifikuje się do vision check (FRONT/REAR damage + zdjęcia)."""
    if not lot.images or len(lot.images) < 2:
        return False
    dmg = (lot.damage_primary or "").upper()
    return any(kw in dmg for kw in TRIGGER_KEYWORDS)


def _resolve_frame_damage_provider() -> str:
    """Nadpisanie z dashboardu (settings_db) ma pierwszeństwo przed .env."""
    try:
        from api.settings_db import get_ai_provider_override
        override = get_ai_provider_override("frame_damage_ai_provider")
        if override:
            return override.lower()
    except Exception:
        pass
    return (os.getenv("FRAME_DAMAGE_AI_PROVIDER", "gemini") or "gemini").lower()


def _parse_frame_damage_json(raw: str, cache_key: str) -> Optional[dict]:
    raw = (raw or "").strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()

    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: wyciąga JSON z prozy
        match = re.search(r'\{[^{}]*"frame_damaged"[^{}]*\}', raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    if not data or "frame_damaged" not in data:
        logger.warning("[frame_damage] JSON parse failed for %s; raw=%r", cache_key, raw[:200])
        return None
    return data


def _call_vision_anthropic(images: list[str], user_text: str, cache_key: str) -> Optional[dict]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("[frame_damage] Brak ANTHROPIC_API_KEY — pomijam vision check")
        return None

    base_url = os.getenv("ANTHROPIC_BASE_URL") or None
    timeout = int(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "120"))
    model_name = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    kwargs = {"api_key": api_key, "timeout": timeout, "max_retries": 1}
    if base_url:
        kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**kwargs)

    # Anthropic vision API wspiera URL images (source.type='url') — fetch'uje sam.
    # Niektóre Copart/IAAI obrazy mogą być za auth wall — wtedy LLM dostanie 403.
    content_blocks = [{"type": "image", "source": {"type": "url", "url": url}} for url in images]
    content_blocks.append({"type": "text", "text": user_text})

    try:
        resp = client.messages.create(
            model=model_name,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content_blocks}],
        )
    except Exception as exc:
        logger.warning("[frame_damage] Anthropic vision call failed for %s: %s", cache_key, exc)
        return None

    raw = "".join(b.text for b in resp.content if b.type == "text")
    return _parse_frame_damage_json(raw, cache_key)


def _download_image_b64(url: str, timeout: int) -> Optional[tuple[str, str]]:
    """Pobiera obraz spod URL i zwraca (mime_type, base64_data), albo None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            data = resp.read()
        return content_type, base64.b64encode(data).decode("ascii")
    except Exception as exc:
        logger.info("[frame_damage] Pobranie zdjęcia nieudane (%s): %s", url[:80], exc)
        return None


def _call_vision_gemini(images: list[str], user_text: str, cache_key: str) -> Optional[dict]:
    """Gemini generateContent wymaga inline base64 (nie fetch'uje zewnętrznych
    URLi tak jak Anthropic) — pobieramy zdjęcia sami i wysyłamy jako inline_data.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("[frame_damage] Brak GEMINI_API_KEY — pomijam vision check")
        return None

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    timeout = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "60"))

    parts: list[dict] = []
    for url in images:
        downloaded = _download_image_b64(url, timeout)
        if downloaded is None:
            continue
        mime_type, b64_data = downloaded
        parts.append({"inline_data": {"mime_type": mime_type, "data": b64_data}})

    if not parts:
        logger.info("[frame_damage] %s: żadne zdjęcie nie pobrało się dla Gemini — pomijam", cache_key)
        return None

    parts.append({"text": user_text})
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": 400,
            "temperature": 0.2,
            "responseMimeType": "application/json",
            # thinkingBudget=0: bez tego "thinking" tokens zjadają cały maxOutputTokens
            # budget -> finishReason=MAX_TOKENS -> ucięty/pusty JSON (patrz hybrid_reports.py).
            "thinkingConfig": {"thinkingBudget": int(os.getenv("GEMINI_THINKING_BUDGET", "0"))},
        },
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("[frame_damage] Gemini vision call failed for %s: %s", cache_key, exc)
        return None

    candidates = data.get("candidates") or []
    if not candidates:
        logger.warning("[frame_damage] Gemini brak candidates dla %s", cache_key)
        return None
    resp_parts = (candidates[0].get("content") or {}).get("parts") or []
    raw = "".join(p.get("text", "") for p in resp_parts if p.get("text"))
    return _parse_frame_damage_json(raw, cache_key)


def check_frame_damage(lot: CarLot, *, force: bool = False) -> Optional[dict]:
    """Sprawdza zdjęcia lota pod kątem uszkodzenia belki.

    Args:
        lot: CarLot z `images` (list URL) i `damage_primary`.
        force: pomiń cache, zawsze wywołaj LLM.

    Returns:
        dict {frame_damaged, confidence, reason, checked_via} albo None gdy
        check pominięty (brak kwalifikacji, brak API key, etc.).
    """
    if os.getenv("FRAME_DAMAGE_VISION_ENABLED", "true").lower() != "true":
        return None
    if not should_check_frame(lot):
        return None

    vin = (lot.full_vin or lot.vin or "").strip().upper()
    cache_key = vin if vin and len(vin) == 17 else f"{lot.source}::{lot.lot_id}"

    cache = _load_cache()
    if not force and cache_key in cache:
        cached = cache[cache_key]
        logger.info("[frame_damage] CACHE HIT %s: frame_damaged=%s", cache_key, cached.get("frame_damaged"))
        return {**cached, "checked_via": "cache"}

    # Wybierz max N zdjęć (uniknięcie token explosion)
    images = (lot.images or [])[:MAX_IMAGES]
    if not images:
        return None

    user_text = USER_TEMPLATE.format(
        year=lot.year or "?",
        make=lot.make or "?",
        model=lot.model or "?",
        damage_primary=lot.damage_primary or "?",
    )

    provider = _resolve_frame_damage_provider()
    if provider == "kiro":
        # Kiro CLI to subprocess tekstowy (kiro-cli chat --no-interactive "prompt") —
        # nie ma potwierdzonego mechanizmu za łączenia obrazów do promptu (brak
        # udokumentowanej flagi --image/--file w headless mode). Zamiast zgadywać
        # i ryzykować cichy błąd, jawnie logujemy i spadamy do Gemini (vision-native).
        logger.info(
            "[frame_damage] FRAME_DAMAGE_AI_PROVIDER=kiro nieobsługiwane dla zadania "
            "wizyjnego (kiro-cli nie ma potwierdzonego wejścia obrazkowego) — używam Gemini"
        )
        provider = "gemini"

    if provider == "anthropic":
        data = _call_vision_anthropic(images, user_text, cache_key)
    else:
        data = _call_vision_gemini(images, user_text, cache_key)
        if data is None and os.getenv("ANTHROPIC_API_KEY"):
            logger.info("[frame_damage] %s nie zwrócił wyniku — fallback Anthropic", provider)
            data = _call_vision_anthropic(images, user_text, cache_key)

    if not data or "frame_damaged" not in data:
        return None

    raw_reason = str(data.get("reason", "") or "")[:300]
    raw_confidence = float(data.get("confidence", 0.5) or 0.5)
    raw_frame_damaged = bool(data.get("frame_damaged"))

    # KRYTYCZNY FIX: Anthropic vision API nie ma dostępu do Copart/IAAI image URLs
    # (cookies-protected CDN). Gdy LLM zgłasza "zdjęcia niedostępne" / "brak access"
    # — to NIE jest sygnał o frame damage, tylko o niemożności weryfikacji.
    # Wtedy zwracamy frame_damaged=False (przepuść lot, AI scoringu zdecyduje
    # na podstawie text damage_primary). Inaczej dyskwalifikujemy wszystko
    # z FRONT/REAR damage automatycznie — co broker'a nie satysfakcjonuje.
    reason_lower = raw_reason.lower()
    inaccessible_keywords = (
        "niedostępne", "niedostepne", "niedostateczne", "brak zdjęć",
        "brak zdjec", "błąd ładow", "blad ladow", "błąd konwer", "blad konwer",
        "obrazy niedostępne", "obrazy niedostepne", "no access", "cannot access",
        "unable to access", "not accessible", "no visible", "brak dostępu",
        "brak dostepu", "image not", "could not retrieve", "nieczytel", "blurry",
        "brak czytelnych",
    )
    images_inaccessible = any(kw in reason_lower for kw in inaccessible_keywords)
    if images_inaccessible:
        logger.info(
            "[frame_damage] %s: vision returned inaccessible (reason=%r) → traktuj jako frame_damaged=False (no veto)",
            cache_key,
            raw_reason[:80],
        )
        raw_frame_damaged = False
        raw_confidence = 0.0  # Zero confidence — wynik nieinformacyjny

    result = {
        "frame_damaged": raw_frame_damaged,
        "confidence": raw_confidence,
        "reason": raw_reason,
        "images_inaccessible": images_inaccessible,
        "checked_via": "vision",
        "checked_at": time.time(),
    }

    # Save to cache
    cache[cache_key] = result
    _save_cache(cache)

    logger.info(
        "[frame_damage] %s: frame_damaged=%s confidence=%.2f reason=%r",
        cache_key,
        result["frame_damaged"],
        result["confidence"],
        result["reason"][:80],
    )
    return result


def enrich_lots_with_frame_check(lots: list[CarLot]) -> None:
    """Wzbogaca lot.raw_data['frame_damage_check'] dla wszystkich kwalifikujących się lotów.

    Opt-in via FRAME_DAMAGE_VISION_ENABLED=true (default true). Bez flagi — no-op.
    Synchroniczne (sekwencyjne calls do Claude); typowo 5 lotów × ~5s = 25s overhead.
    """
    if os.getenv("FRAME_DAMAGE_VISION_ENABLED", "true").lower() != "true":
        return

    candidates = [lot for lot in lots if should_check_frame(lot)]
    if not candidates:
        return

    logger.info("[frame_damage] Sprawdzam %d/%d lotów (FRONT/REAR damage)", len(candidates), len(lots))
    for lot in candidates:
        try:
            result = check_frame_damage(lot)
            if result:
                lot.raw_data["frame_damage_check"] = result
        except Exception as exc:
            logger.exception("[frame_damage] Unexpected error for lot %s: %s", lot.lot_id, exc)
