import json
import os
import time
import urllib.error
import urllib.request
import anthropic
from typing import Optional, Tuple, List
from parser.models import CarLot, ClientCriteria, AIAnalysis, AnalyzedLot
from dotenv import load_dotenv

load_dotenv(override=True)

EASTERN_STATES = {"NY", "NJ", "PA", "CT", "MA", "RI", "VT", "NH", "ME", "MD", "DE", "VA", "NC", "SC", "GA", "FL"}
WESTERN_STATES = {"CA", "OR", "WA", "NV", "AZ", "UT", "CO", "NM"}

SYSTEM_PROMPT = """Jesteś ekspertem od importu aut z USA do Polski.
Analizujesz dane z aukcji Copart i IAAI dla klienta-brokera importowego.

PRIORYTET LOKALIZACJI - WSCHODNIE WYBRZEŻE USA:
Stany wschodnie (łatwy i tani transport do Polski):
- NY, NJ, PA, CT, MA, RI, VT, NH, ME, MD, DE, VA, NC, SC, GA, FL
- Transport morski: 1400-1600 USD, czas: 3-4 tygodnie
- PREFERUJ te stany - dodaj +1.5 do score

Stany środkowe (średni transport):
- OH, MI, IN, IL, WI, MN, IA, MO, KY, TN, AL, MS, LA, AR
- Transport: 1600-1800 USD, czas: 4-5 tygodni
- Neutralne dla score

Stany zachodnie (drogi transport):
- CA, OR, WA, NV, AZ, UT, CO, NM, TX (zachodni)
- Transport: 1800-2200 USD, czas: 5-6 tygodni
- ODEJMIJ -1.0 od score (chyba że wyjątkowo dobra oferta)

KOSZTY STAŁE DO UWZGLĘDNIENIA:
- Transport USA → Polska: 1400-2200 USD (zależnie od lokalizacji)
- Cło + akcyza: ok. 800 USD ekwiwalent
- Homologacja + rejestracja: ok. 500 USD

ZASADY OCENY USZKODZEŃ:
- FLOOD / WATER DAMAGE → automatycznie ODRZUĆ (ukryta korozja, elektronika)
- FIRE → automatycznie ODRZUĆ
- DEPLOYED AIRBAGS → duże ryzyko, nalicz 1500-3000 USD do naprawy
- FRAME/STRUCTURAL DAMAGE → duże ryzyko, może nie przejść homologacji PL
- REBUILT TITLE → ryzyko, trudniej sprzedać w Polsce
- FRONT END / REAR END → standardowe szkody, szacuj 1000-4000 USD

ZASADY UŻYCIA CENY REZERWOWEJ (seller_reserve_usd):
- Jeśli aktualna oferta < rezerwa: auto prawdopodobnie nie zostanie sprzedane lub cena wzrośnie znacznie
- Jeśli oferta >= rezerwa: sprzedaż prawie pewna po tej cenie
- Uwzględnij to w szacunkach total cost

ZASADY UŻYCIA TYPU SPRZEDAWCY (seller_type):
- "insurance": ubezpieczyciel chce szybko pozbyć auta, ceny bardziej negocjowalne
- "dealer": reseller, cena zazwyczaj bliższa rynkowej, mniejszy margines

SZCZEGÓŁOWA ANALIZA - dla każdego lota MUSISZ podać:
1. Dlaczego wybrałeś ten lot (konkretne zalety)
2. Wszystkie dane techniczne (VIN, przebieg, rok, uszkodzenia, tytuł)
3. Analiza lokalizacji i kosztów transportu
4. Analiza ceny (bid, rezerwa, typ sprzedawcy)
5. Szacunek naprawy z uzasadnieniem
6. Całkowity koszt z rozbiciem
7. Czerwone flagi i ryzyka
8. Rekomendacja z uzasadnieniem

Zwróć WYŁĄCZNIE poprawny JSON array. Bez żadnego tekstu przed ani po.
"""


def parse_price_from_str(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    import re
    cleaned = re.sub(r"[^\d.]", "", str(text).replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def analyze_lots(
    lots: List[CarLot],
    criteria: ClientCriteria,
    top_n: int = 5,
    force_local: bool = False,
) -> Tuple[List[AnalyzedLot], List[AnalyzedLot]]:
    """
    Analizuje loty i zwraca (top_recommendations, all_results).

    Returns:
        tuple: (TOP N najlepszych lotów, wszystkie przeanalizowane loty)
    """
    if not lots:
        return [], []

    ai_mode = os.getenv("AI_ANALYSIS_MODE", "auto").lower()
    openai_key = os.getenv("OPENAI_API_KEY")
    has_openai_key = _has_usable_openai_key(openai_key)
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    strict_ai = os.getenv("AI_ANALYSIS_STRICT", "false").lower() == "true"

    if force_local or ai_mode == "local":
        return _analyze_lots_locally(lots, criteria, top_n=top_n)

    if ai_mode in {"openai", "gpt"}:
        if not has_openai_key:
            message = "AI_ANALYSIS_MODE=openai, ale brakuje poprawnego OPENAI_API_KEY"
            if strict_ai:
                raise RuntimeError(message)
            print(f"[AI] {message}. Używam lokalnego scoringu.")
            return _analyze_lots_locally(lots, criteria, top_n=top_n)
        try:
            return _analyze_lots_with_openai(lots, criteria, top_n=top_n)
        except Exception as exc:
            if strict_ai:
                raise
            print(f"[AI] OpenAI API niedostępne ({exc}). Używam lokalnego scoringu.")
            return _analyze_lots_locally(lots, criteria, top_n=top_n)

    if ai_mode == "anthropic":
        if not anthropic_key:
            message = "AI_ANALYSIS_MODE=anthropic, ale brakuje ANTHROPIC_API_KEY"
            if strict_ai:
                raise RuntimeError(message)
            print(f"[AI] {message}. Używam lokalnego scoringu.")
            return _analyze_lots_locally(lots, criteria, top_n=top_n)
        try:
            return _analyze_lots_with_claude(lots, criteria, top_n=top_n)
        except Exception as exc:
            if strict_ai:
                raise
            print(f"[AI] Claude API niedostępne ({exc}). Używam lokalnego scoringu.")
            return _analyze_lots_locally(lots, criteria, top_n=top_n)

    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if ai_mode == "gemini":
        if not gemini_key:
            message = "AI_ANALYSIS_MODE=gemini, ale brakuje GEMINI_API_KEY"
            if strict_ai:
                raise RuntimeError(message)
            print(f"[AI] {message}. Używam lokalnego scoringu.")
            return _analyze_lots_locally(lots, criteria, top_n=top_n)
        try:
            return _analyze_lots_with_gemini(lots, criteria, top_n=top_n)
        except Exception as exc:
            if strict_ai:
                raise
            print(f"[AI] Gemini API niedostępne ({exc}). Używam lokalnego scoringu.")
            return _analyze_lots_locally(lots, criteria, top_n=top_n)

    if has_openai_key:
        try:
            return _analyze_lots_with_openai(lots, criteria, top_n=top_n)
        except Exception as exc:
            print(f"[AI] OpenAI API niedostępne ({exc}). Próbuję Claude/Gemini/local.")

    if anthropic_key:
        try:
            return _analyze_lots_with_claude(lots, criteria, top_n=top_n)
        except Exception as exc:
            print(f"[AI] Claude API niedostępne ({exc}). Próbuję Gemini/local.")

    if gemini_key:
        try:
            return _analyze_lots_with_gemini(lots, criteria, top_n=top_n)
        except Exception as exc:
            print(f"[AI] Gemini API niedostępne ({exc}). Używam lokalnego scoringu.")

    if not has_openai_key and not anthropic_key and not gemini_key:
        print("[AI] Brak OPENAI_API_KEY, ANTHROPIC_API_KEY i GEMINI_API_KEY — używam lokalnego scoringu.")

    return _analyze_lots_locally(lots, criteria, top_n=top_n)


def _has_usable_openai_key(api_key: Optional[str]) -> bool:
    return bool(api_key and api_key.startswith("sk-"))


def _sanitize_error_text(text: str) -> str:
    import re

    text = text or ""
    text = re.sub(r"sk-[A-Za-z0-9_\\-]{8,}", "sk-***", text)
    text = re.sub(r"qua-[A-Za-z0-9_\\-]{8,}", "qua-***", text)
    return text


def _lot_payloads(lots: List[CarLot]) -> list[dict]:
    return [
        {
            "lot_id": lot.lot_id,
            "source": lot.source,
            "url": lot.url,
            "year": lot.year,
            "make": lot.make,
            "model": lot.model,
            "trim": lot.trim,
            "vin": lot.full_vin or lot.vin,
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
            "airbags_deployed": lot.airbags_deployed,
            "keys": lot.keys,
            "enriched_by_extension": lot.enriched_by_extension,
        }
        for lot in lots
    ]


def _analysis_user_prompt(lots_data: list[dict], criteria: ClientCriteria) -> str:
    return f"""
Kryteria klienta:
- Marka/model: {criteria.make} {criteria.model or '(dowolny)'}
- Rocznik: {criteria.year_from or 'dowolny'}–{criteria.year_to or 'dowolny'}
- Budżet maksymalny: {criteria.budget_usd} USD (łącznie z transportem i naprawą)
- Maksymalny przebieg: {criteria.max_odometer_mi or 'bez limitu'} mil
- Wykluczone typy uszkodzeń: {', '.join(criteria.excluded_damage_types)}

Oceń poniższe {len(lots_data)} lotów:

{json.dumps(lots_data, ensure_ascii=False, indent=2)}

Zwróć WYŁĄCZNIE poprawny JSON object w formacie:
{{
  "analyses": [
    {{
      "lot_id": "string",
      "score": 0.0,
      "recommendation": "POLECAM|RYZYKO|ODRZUĆ",
      "red_flags": ["string"],
      "estimated_repair_usd": 0,
      "estimated_total_cost_usd": 0,
      "client_description_pl": "3-5 zdań po polsku dla klienta",
      "ai_notes": "szczegółowe uwagi techniczne dla brokera po polsku"
    }}
  ]
}}

Zasady:
- Oceń każdy lot z danych wejściowych.
- Używaj dokładnie tych lot_id, które są w danych.
- Uwzględnij lokalizację, koszty transportu, uszkodzenia, przebieg, tytuł, cenę, rezerwę i seller_type.
- score: liczba w zakresie 0.0–10.0 (NIE używaj wartości ujemnych ani powyżej 10).
- Limit znaków: client_description_pl maksymalnie 280 znaków, ai_notes maksymalnie 450 znaków.
- Nie dodawaj tekstu poza JSON.
"""


def _extract_response_text(response_data: dict) -> str:
    if response_data.get("output_text"):
        return str(response_data["output_text"])

    chunks: list[str] = []
    for item in response_data.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(str(content["text"]))
    return "".join(chunks)


def _parse_analysis_json(raw: str) -> list[dict]:
    raw = (raw or "").strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        analyses = data.get("analyses") or data.get("results") or data.get("items")
        if isinstance(analyses, list):
            return analyses
    raise ValueError("AI nie zwróciło listy analiz")


def _call_anthropic_messages(model: str, system: str, user_prompt: str, max_tokens: int = 4096) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Brak ANTHROPIC_API_KEY")

    timeout = int(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "120"))
    max_retries = int(os.getenv("ANTHROPIC_MAX_RETRIES", "4"))

    client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)

    last_exc: Exception = RuntimeError("Anthropic: brak odpowiedzi")
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_prompt}],
                thinking={"type": "adaptive"},
                betas=["prompt-caching-2024-07-31"],
            )
            chunks = [block.text for block in response.content if block.type == "text"]
            if not chunks:
                raise RuntimeError("Anthropic response has no text content")
            return "".join(chunks)
        except anthropic.APIStatusError as exc:
            if exc.status_code in (429, 500, 502, 503, 520, 521, 522, 524) and attempt < max_retries - 1:
                wait = min(2 ** attempt * 2, 60)
                print(f"[AI] Anthropic HTTP {exc.status_code}, retry {attempt + 1}/{max_retries - 1} za {wait}s...")
                time.sleep(wait)
                last_exc = RuntimeError(f"Anthropic HTTP {exc.status_code}: {_sanitize_error_text(str(exc)[:500])}")
                continue
            raise RuntimeError(f"Anthropic HTTP {exc.status_code}: {_sanitize_error_text(str(exc)[:500])}") from exc
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                wait = min(2 ** attempt * 2, 60)
                print(f"[AI] Anthropic error: {exc}, retry {attempt + 1}/{max_retries - 1} za {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise last_exc


def _results_from_analysis_data(
    analyses_data: list[dict],
    lots: List[CarLot],
    top_n: int,
) -> Tuple[List[AnalyzedLot], List[AnalyzedLot]]:
    lots_by_id = {lot.lot_id: lot for lot in lots}
    results = []

    for ad in analyses_data:
        lot_id = str(ad.get("lot_id") or "")
        if not lot_id or lot_id not in lots_by_id:
            continue

        raw_score = ad.get("score", 0)
        try:
            score_clamped = max(0.0, min(10.0, float(raw_score)))
        except (TypeError, ValueError):
            score_clamped = 0.0

        analysis = AIAnalysis(
            lot_id=lot_id,
            score=score_clamped,
            recommendation=ad.get("recommendation", "RYZYKO"),
            red_flags=ad.get("red_flags", []),
            estimated_repair_usd=ad.get("estimated_repair_usd"),
            estimated_total_cost_usd=ad.get("estimated_total_cost_usd"),
            client_description_pl=ad.get("client_description_pl", ""),
            ai_notes=ad.get("ai_notes"),
        )
        results.append(AnalyzedLot(lot=lots_by_id[lot_id], analysis=analysis))

    return _rank_results(results, top_n)


def _analyze_lots_with_openai(
    lots: List[CarLot],
    criteria: ClientCriteria,
    top_n: int = 5,
) -> Tuple[List[AnalyzedLot], List[AnalyzedLot]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not _has_usable_openai_key(api_key):
        raise RuntimeError("Brak poprawnego OPENAI_API_KEY")

    model = os.getenv("OPENAI_MODEL", "gpt-5.2")
    lots_data = _lot_payloads(lots)
    user_prompt = _analysis_user_prompt(lots_data, criteria)
    print(f"[AI] Analizuję {len(lots)} lotów przez OpenAI Responses API ({model})...")

    payload = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": user_prompt,
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "12000")),
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=int(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {_sanitize_error_text(error_body[:500])}") from exc

    raw = _extract_response_text(response_data)
    analyses_data = _parse_analysis_json(raw)
    return _results_from_analysis_data(analyses_data, lots, top_n)


def _rank_results(results: List[AnalyzedLot], top_n: int) -> Tuple[List[AnalyzedLot], List[AnalyzedLot]]:
    order = {"POLECAM": 0, "RYZYKO": 1, "ODRZUĆ": 2}
    results.sort(key=lambda x: (order.get(x.analysis.recommendation, 99), -x.analysis.score))

    for item in results:
        item.is_top_recommendation = False

    top_results = results[:top_n]
    for lot in top_results:
        lot.is_top_recommendation = True

    polecam = sum(1 for r in results if r.analysis.recommendation == "POLECAM")
    ryzyko = sum(1 for r in results if r.analysis.recommendation == "RYZYKO")
    odrzuc = sum(1 for r in results if r.analysis.recommendation == "ODRZUĆ")
    print(f"[AI] Wyniki: POLECAM={polecam} | RYZYKO={ryzyko} | ODRZUĆ={odrzuc}")
    print(f"[AI] TOP {top_n}: {[f'{r.lot.lot_id} (score={r.analysis.score:.1f})' for r in top_results]}")

    return top_results, results


def _location_transport_usd(state: Optional[str]) -> int:
    if state in EASTERN_STATES:
        return 1500
    if state in WESTERN_STATES:
        return 2100
    return 1750


def _estimate_repair_cost(lot: CarLot) -> tuple[int, list[str], float]:
    damage = f"{lot.damage_primary or ''} {lot.damage_secondary or ''}".lower()
    title = (lot.title_type or "").lower()
    flags: list[str] = []
    score_delta = 0.0

    if "flood" in damage or "water" in damage or "flood" in title:
        return 9000, ["Flood/water damage", "Wysokie ryzyko elektroniki i korozji"], -5.0
    if "fire" in damage:
        return 10000, ["Fire damage"], -5.0
    if "frame" in damage or "structural" in damage:
        flags.append("Frame/structural damage")
        score_delta -= 2.5
        base = 6500
    elif "mechanical" in damage:
        flags.append("Ryzyko mechaniczne")
        score_delta -= 1.4
        base = 4500
    elif "front" in damage:
        base = 3200
        score_delta -= 0.5
    elif "rear" in damage:
        base = 2600
        score_delta -= 0.3
    elif "side" in damage:
        base = 2400
        score_delta -= 0.3
    elif "hail" in damage:
        base = 1800
        score_delta += 0.2
    elif "minor" in damage or "scratch" in damage or "dent" in damage:
        base = 1200
        score_delta += 0.6
    else:
        base = 3000
        flags.append("Nieprecyzyjny opis uszkodzeń")
        score_delta -= 0.4

    if lot.airbags_deployed:
        base += 2200
        flags.append("Odpalone poduszki")
        score_delta -= 1.2

    if "salvage" in title:
        flags.append("Salvage title")
        score_delta -= 0.5
    if "rebuilt" in title:
        flags.append("Rebuilt title")
        score_delta -= 1.0
    if "parts" in title:
        flags.append("Parts only title")
        score_delta -= 3.0
    if "clean" in title:
        score_delta += 0.5

    if lot.keys is False:
        base += 350
        flags.append("Brak kluczy")
        score_delta -= 0.4

    return base, flags, score_delta


def _analyze_lots_locally(lots: List[CarLot], criteria: ClientCriteria, top_n: int = 5) -> Tuple[List[AnalyzedLot], List[AnalyzedLot]]:
    print(f"[AI] Lokalny scoring dla {len(lots)} lotów...")
    results: list[AnalyzedLot] = []

    for lot in lots:
        score = 5.5
        red_flags: list[str] = []
        state = lot.location_state

        if state in EASTERN_STATES:
            score += 1.5
            location_note = "wschodnie wybrzeże, korzystny transport"
        elif state in WESTERN_STATES:
            score -= 1.0
            location_note = "zachód USA, droższy i dłuższy transport"
        else:
            location_note = "środkowa część USA, standardowy koszt transportu"

        repair_usd, damage_flags, damage_score_delta = _estimate_repair_cost(lot)
        score += damage_score_delta
        red_flags.extend(damage_flags)

        if lot.odometer_mi:
            if lot.odometer_mi > 100_000:
                red_flags.append("Wysoki przebieg")
                score -= 1.0
            elif lot.odometer_mi > 70_000:
                score -= 0.4
            elif lot.odometer_mi < 45_000:
                score += 0.5

        if lot.seller_type == "insurance":
            score += 0.5
        elif lot.seller_type == "dealer":
            score -= 0.3

        bid_usd = lot.current_bid_usd or lot.buy_now_price_usd or 0
        if lot.seller_reserve_usd and bid_usd and bid_usd < lot.seller_reserve_usd:
            red_flags.append("Oferta poniżej ceny rezerwowej")
            score -= 0.3

        transport_usd = lot.delivery_cost_estimate_usd or _location_transport_usd(state)
        estimated_total = int(round(bid_usd + repair_usd + transport_usd + 500))

        if estimated_total > criteria.budget_usd:
            red_flags.append("Szacunek powyżej budżetu")
            score -= 1.5

        score = max(0.0, min(10.0, score))
        severe_flags = {"Flood/water damage", "Fire damage", "Parts only title"}
        if severe_flags.intersection(red_flags) or score < 4.0:
            recommendation = "ODRZUĆ"
        elif score >= 7.0 and estimated_total <= criteria.budget_usd * 1.05:
            recommendation = "POLECAM"
        else:
            recommendation = "RYZYKO"

        price_note = f"aktualna oferta ${bid_usd:,.0f}".replace(",", " ") if bid_usd else "brak pewnej ceny ofertowej"
        reserve_note = ""
        if lot.seller_reserve_usd:
            reserve_note = f", rezerwa ${lot.seller_reserve_usd:,.0f}".replace(",", " ")

        client_description = (
            f"{lot.year or '?'} {lot.make or ''} {lot.model or ''}, przebieg "
            f"{lot.odometer_mi or 'nieznany'} mi, lokalizacja {lot.location_city or ''} {state or ''} ({location_note}). "
            f"Uszkodzenie: {lot.damage_primary or 'brak danych'}, tytuł: {lot.title_type or 'brak danych'}, "
            f"szacunek naprawy ${repair_usd:,.0f}. ".replace(",", " ")
            + f"Cena: {price_note}{reserve_note}; łączny szacunek z transportem i opłatami: ${estimated_total:,.0f}. ".replace(",", " ")
            + f"Rekomendacja: {recommendation.lower()}."
        )

        ai_notes = (
            f"Scoring lokalny: lokalizacja {state or 'brak'} ({location_note}), transport ok. ${transport_usd:,.0f}; "
            f"naprawa oszacowana na ${repair_usd:,.0f}; "
            f"sprzedawca: {lot.seller_type or 'nieznany'}; "
            f"ryzyka: {', '.join(red_flags) if red_flags else 'brak istotnych czerwonych flag'}."
        ).replace(",", " ")

        analysis = AIAnalysis(
            lot_id=lot.lot_id,
            score=round(score, 1),
            recommendation=recommendation,
            red_flags=red_flags,
            estimated_repair_usd=repair_usd,
            estimated_total_cost_usd=estimated_total,
            client_description_pl=client_description,
            ai_notes=ai_notes,
        )
        results.append(AnalyzedLot(lot=lot, analysis=analysis))

    return _rank_results(results, top_n)


def _call_gemini(model: str, system: str, user_prompt: str, max_tokens: int = 8192) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Brak GEMINI_API_KEY")

    timeout = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "120"))
    max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "4"))

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": max_tokens,
            "temperature": float(os.getenv("GEMINI_TEMPERATURE", "0.4")),
        },
    }

    last_exc: Exception = RuntimeError("Gemini: brak odpowiedzi")
    for attempt in range(max_retries):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                response_data = json.loads(body)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            sanitized = _sanitize_error_text(error_body[:500])
            if exc.code == 429 and attempt < max_retries - 1:
                # Gemini free tier 15 RPM rolling window — czekaj 30s, potem 60s
                wait = 30 if attempt == 0 else 60
                print(f"[AI] Gemini HTTP 429 (rate limit), retry {attempt + 1}/{max_retries - 1} za {wait}s...")
                time.sleep(wait)
                last_exc = RuntimeError(f"Gemini HTTP 429: rate limit")
                continue
            if exc.code in (500, 502, 503) and attempt < max_retries - 1:
                wait = min(2 ** attempt * 2, 60)
                print(f"[AI] Gemini HTTP {exc.code}, retry {attempt + 1}/{max_retries - 1} za {wait}s...")
                time.sleep(wait)
                last_exc = RuntimeError(f"Gemini HTTP {exc.code}: {sanitized}")
                continue
            raise RuntimeError(f"Gemini HTTP {exc.code}: {sanitized}") from exc
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                wait = min(2 ** attempt * 2, 60)
                print(f"[AI] Gemini network error: {exc}, retry {attempt + 1}/{max_retries - 1} za {wait}s...")
                time.sleep(wait)
                continue
            raise

        candidates = response_data.get("candidates") or []
        if not candidates:
            prompt_feedback = response_data.get("promptFeedback") or {}
            block_reason = prompt_feedback.get("blockReason")
            raise RuntimeError(f"Gemini brak candidates (blockReason={block_reason})")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text_chunks = [p.get("text", "") for p in parts if p.get("text")]
        if not text_chunks:
            finish_reason = candidates[0].get("finishReason")
            raise RuntimeError(f"Gemini pusta odpowiedź (finishReason={finish_reason})")
        return "".join(text_chunks)

    raise last_exc


def _analyze_lots_with_gemini(
    lots: List[CarLot],
    criteria: ClientCriteria,
    top_n: int = 5,
) -> Tuple[List[AnalyzedLot], List[AnalyzedLot]]:
    """Analiza Gemini z chunkingiem — gemini-2.5-flash ma hard 8k token output cap,
    co przy szczegółowym opisie per lot pozwala bezpiecznie analizować ~3 lotów per call.

    Free tier: 15 RPM, 1500 RPD. Aby zmieścić się komfortowo:
    - Pre-filtr heurystyką do GEMINI_MAX_LOTS (default 15) → max 5 chunków po 3 loty
    - 5s delay między chunki = 12 RPM safe
    """
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    chunk_size = int(os.getenv("GEMINI_CHUNK_SIZE", "3"))
    chunk_delay_ms = int(os.getenv("GEMINI_CHUNK_DELAY_MS", "5000"))
    max_tokens = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8192"))
    max_lots_for_ai = int(os.getenv("GEMINI_MAX_LOTS", "15"))

    if len(lots) > max_lots_for_ai:
        print(f"[AI] Pre-filtr heurystyczny: {len(lots)} → top {max_lots_for_ai} (oszczędność free tier RPM)")
        _, all_local = _analyze_lots_locally(lots, criteria, top_n=max_lots_for_ai)
        lots = [r.lot for r in all_local[:max_lots_for_ai]]

    n_chunks = (len(lots) + chunk_size - 1) // chunk_size
    print(f"[AI] Analizuję {len(lots)} lotów przez Gemini API ({model}, chunki po {chunk_size}, total {n_chunks} call, delay {chunk_delay_ms}ms)...")

    all_analyses: list[dict] = []
    for chunk_idx in range(n_chunks):
        if chunk_idx > 0 and chunk_delay_ms > 0:
            time.sleep(chunk_delay_ms / 1000.0)
        start = chunk_idx * chunk_size
        chunk_lots = lots[start:start + chunk_size]
        chunk_data = _lot_payloads(chunk_lots)
        chunk_prompt = _analysis_user_prompt(chunk_data, criteria)

        try:
            raw = _call_gemini(
                model=model,
                system=SYSTEM_PROMPT,
                user_prompt=chunk_prompt,
                max_tokens=max_tokens,
            ).strip()
            chunk_analyses = _parse_analysis_json(raw)
            all_analyses.extend(chunk_analyses)
            print(f"[AI] Chunk {chunk_idx + 1}/{n_chunks}: zwrócono {len(chunk_analyses)} analiz")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[AI] Chunk {chunk_idx + 1}/{n_chunks}: parse error ({e}), retry z połową ({len(chunk_lots)//2 or 1} lotów)...")
            shrunk = chunk_lots[:max(1, len(chunk_lots) // 2)]
            chunk_data = _lot_payloads(shrunk)
            chunk_prompt = _analysis_user_prompt(chunk_data, criteria)
            try:
                raw = _call_gemini(
                    model=model,
                    system=SYSTEM_PROMPT,
                    user_prompt=chunk_prompt,
                    max_tokens=max_tokens,
                ).strip()
                all_analyses.extend(_parse_analysis_json(raw))
                print(f"[AI] Chunk {chunk_idx + 1}/{n_chunks} retry: OK po zmniejszeniu")
            except Exception as inner_exc:
                print(f"[AI] Chunk {chunk_idx + 1}/{n_chunks} retry też padł: {inner_exc} — pomijam ten chunk")
        except Exception as exc:
            print(f"[AI] Chunk {chunk_idx + 1}/{n_chunks}: błąd ({exc}) — pomijam")

    if not all_analyses:
        raise RuntimeError("Gemini: żaden chunk nie zwrócił poprawnych analiz")

    print(f"[AI] Łącznie zebrano {len(all_analyses)} analiz Gemini z {n_chunks} chunków")
    return _results_from_analysis_data(all_analyses, lots, top_n)


def _analyze_lots_with_claude(lots: List[CarLot], criteria: ClientCriteria, top_n: int = 5) -> Tuple[List[AnalyzedLot], List[AnalyzedLot]]:
    model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")

    lots_data = _lot_payloads(lots)
    user_prompt = _analysis_user_prompt(lots_data, criteria)
    max_tokens = max(1500, len(lots_data) * 400)
    max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", str(min(max_tokens, 8192))))
    print(f"[AI] Analizuję {len(lots)} lotów przez Claude API ({model}, max_tokens={max_tokens})...")

    raw = _call_anthropic_messages(model=model, system=SYSTEM_PROMPT, user_prompt=user_prompt, max_tokens=max_tokens).strip()

    try:
        analyses_data = _parse_analysis_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[AI] Błąd parsowania JSON: {e}")
        print(f"[AI] Surowa odpowiedź (pierwsze 500 znaków): {raw[:500]}")
        with open("/tmp/ai_response_error.txt", "w") as f:
            f.write(raw)
        print("[AI] Pełna odpowiedź zapisana do /tmp/ai_response_error.txt")

        if len(lots) > 10:
            print("[AI] Retry z mniejszą liczbą lotów...")
            lots = lots[:10]
            lots_data = _lot_payloads(lots)
            user_prompt = _analysis_user_prompt(lots_data, criteria)
            retry_max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))
            print(f"[AI] Ograniczam do {len(lots)} lotów")
            raw = _call_anthropic_messages(
                model=model,
                system=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=retry_max_tokens,
            ).strip()
            analyses_data = _parse_analysis_json(raw)
        else:
            raise Exception(f"AI zwróciło niepoprawny JSON: {e}")

    return _results_from_analysis_data(analyses_data, lots, top_n)
