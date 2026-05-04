"""LLM-driven HTML report generation.

Wykorzystuje Claude (przez Anthropic SDK + RouteAI proxy) do generowania
bogatych raportów HTML w stylu wzorca BMW M550i (z storytellingiem,
sekcjami HERO/STORY/SPEC/DAMAGE/TIMELINE/DOCS/CTA) dla konkretnego lotu.

Skeleton wzorca (z usuniętymi base64 zdjęciami) jest cachowany jako
prompt cache breakpoint — pierwsze wywołanie pełen koszt, kolejne loty
~10x tańsze (cache TTL Anthropic 5 min default, 1h jeśli włączone).
"""
import json
import os
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from parser.models import AnalyzedLot, ClientCriteria

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


def render_client_report_llm(item: AnalyzedLot, criteria: Optional[ClientCriteria] = None) -> str:
    """Generuje raport HTML dla klienta przez LLM na bazie wzorca BMW M550i."""
    return _call_claude_for_html(
        system=_system_prompt_client(),
        skeleton=_client_skeleton(),
        lot_data=_lot_data_for_prompt(item, criteria),
        skeleton_label="raport klienta",
        max_tokens=int(os.getenv("LLM_REPORT_MAX_TOKENS", "16000")),
    )


def render_broker_report_llm(
    item: AnalyzedLot,
    criteria: Optional[ClientCriteria] = None,
    lots_scanned: int = 0,
) -> str:
    """Generuje raport brokerski HTML przez LLM na bazie wzorca."""
    lot_data = _lot_data_for_prompt(item, criteria)
    if lots_scanned:
        lot_data = lot_data.rstrip().rstrip("}") + f',\n  "lots_scanned": {lots_scanned}\n}}'
    return _call_claude_for_html(
        system=_system_prompt_broker(),
        skeleton=_broker_skeleton(),
        lot_data=lot_data,
        skeleton_label="raport brokerski",
        max_tokens=int(os.getenv("LLM_REPORT_MAX_TOKENS", "16000")),
    )
