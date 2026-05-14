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

import json
import logging
import os
import re
import time
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

    # Składanie content: image blocks + text. Anthropic vision API wspiera
    # URL images (przez source.type='url'). Niektóre Copart/IAAI obrazy mogą
    # być za auth wall — wtedy LLM dostanie 403 i trzeba fallback do None.
    content_blocks = []
    for url in images:
        content_blocks.append({
            "type": "image",
            "source": {"type": "url", "url": url},
        })
    content_blocks.append({"type": "text", "text": user_text})

    try:
        resp = client.messages.create(
            model=model_name,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content_blocks}],
        )
    except Exception as exc:
        logger.warning("[frame_damage] Vision call failed for %s: %s", cache_key, exc)
        return None

    raw = "".join(b.text for b in resp.content if b.type == "text").strip()
    # Strip markdown fences (na wszelki wypadek)
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

    result = {
        "frame_damaged": bool(data.get("frame_damaged")),
        "confidence": float(data.get("confidence", 0.5) or 0.5),
        "reason": str(data.get("reason", "") or "")[:300],
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
