"""
Magazyn próbek z rozszerzenia manheim-collector.

Dlaczego push z przeglądarki, a nie scrape: sesję Manheima utrzymuje wtyczka
BidWise przez chrome.debugger, a Chrome dopuszcza jednego klienta debuggera na
kartę. Zmierzone: samo podpięcie Playwrighta do takiej karty kończy się jej
zamknięciem w ciągu 5 sekund. Kolektor działa w kontekście strony, więc niczego
nikomu nie odbiera — a backend dostaje te same dane, tylko drugą stroną.

Trzymamy dwie rzeczy: surowe partie (do diagnostyki kształtu API) oraz scalone
rekordy pojazdów z TTL — z nich korzysta źródło manheim.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from parser.manheim_records import extract_vehicles, merge_records, record_key

logger = logging.getLogger("api.manheim_ingest")

_lock = threading.Lock()
_vehicles: dict[str, dict] = {}
_seen_at: dict[str, float] = {}
_last_ingest_at: Optional[float] = None
_raw_batches = 0
_last_batch: list[dict] = []


def storage_dir() -> Path:
    return Path(os.getenv("MANHEIM_INGEST_DIR", "./data/manheim_ingest"))


def ttl_seconds() -> float:
    return max(60.0, float(os.getenv("MANHEIM_INGEST_TTL_MINUTES", "30")) * 60.0)


def _keep_raw_batches() -> int:
    """0 = nie zapisuj surowych partii. Przydają się tylko przy diagnostyce
    kształtu API, a potrafią urosnąć (pojedyncza odpowiedź to setki kB)."""
    return max(0, int(os.getenv("MANHEIM_INGEST_KEEP_RAW", "20")))


def _prune_locked() -> None:
    deadline = time.time() - ttl_seconds()
    stale = [key for key, seen in _seen_at.items() if seen < deadline]
    for key in stale:
        _vehicles.pop(key, None)
        _seen_at.pop(key, None)


def _save_raw(captures: list[dict]) -> Optional[Path]:
    keep = _keep_raw_batches()
    if keep == 0:
        return None
    directory = storage_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"capture-{int(time.time() * 1000)}.json"
    path.write_text(json.dumps(captures, ensure_ascii=False)[:4_000_000], encoding="utf-8")

    batches = sorted(directory.glob("capture-*.json"))
    for old in batches[:-keep]:
        old.unlink(missing_ok=True)
    return path


def _payloads(capture: dict) -> list[Any]:
    """Ciało odpowiedzi (a przy okazji żądania) jako JSON, gdy się parsuje."""
    payloads: list[Any] = []
    for field in ("responseBody", "requestBody"):
        raw = capture.get(field)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        payloads.append(parsed)
    return payloads


def last_batch_records() -> list[dict]:
    """Scalone pojazdy z ostatniej przyjętej paczki.

    Potrzebne, żeby wynik zleconego wyszukiwania trafił do konkretnego zadania,
    a nie tylko do wspólnego magazynu z TTL.
    """
    with _lock:
        return list(_last_batch)


def store(captures: list[dict]) -> dict:
    """Przyjmuje partię próbek, zwraca podsumowanie dla wywołującego."""
    global _last_ingest_at, _raw_batches, _last_batch

    fresh: list[dict] = []
    for capture in captures:
        if not isinstance(capture, dict):
            continue
        for payload in _payloads(capture):
            fresh.extend(extract_vehicles(payload))

    merged = merge_records(fresh)
    with _lock:
        _prune_locked()
        _last_batch = merged
        now = time.time()
        for record in merged:
            key = record_key(record)
            if not key:
                continue
            existing = _vehicles.get(key)
            _vehicles[key] = merge_records([existing, record])[0] if existing else record
            _seen_at[key] = now
        _last_ingest_at = now
        total = len(_vehicles)

    # Zapisujemy paczkę gdy coś wniosła ALBO gdy dotyczy API wyszukiwarki —
    # to drugie jest potrzebne do diagnostyki, bo odpowiedź bez rozpoznanych
    # pojazdów jest równie ciekawa jak ta z nimi (znaczy: mapowanie nie trafia).
    worth_keeping = bool(fresh) or any(
        "onesearch" in (capture.get("url") or "")
        for capture in captures
        if isinstance(capture, dict)
    )
    if worth_keeping and _save_raw(captures) is not None:
        _raw_batches += 1

    seen_urls = sorted(
        {
            (capture.get("url") or "?").split("?", 1)[0]
            for capture in captures
            if isinstance(capture, dict)
        }
    )
    logger.info(
        "[manheim-ingest] próbek=%d, rozpoznanych pojazdów=%d, w magazynie=%d | %s",
        len(captures),
        len(fresh),
        total,
        ", ".join(url.replace("https://", "")[:52] for url in seen_urls[:6]) or "brak URL",
    )
    return {"captures": len(captures), "vehicles": len(fresh), "stored": total}


def vehicles() -> list[dict]:
    """Świeże rekordy pojazdów, najnowsze pierwsze."""
    with _lock:
        _prune_locked()
        return [
            _vehicles[key]
            for key in sorted(_seen_at, key=lambda item: _seen_at[item], reverse=True)
            if key in _vehicles
        ]


def status() -> dict:
    with _lock:
        _prune_locked()
        return {
            "vehicles": len(_vehicles),
            "lastIngestAt": _last_ingest_at,
            "ttlSeconds": ttl_seconds(),
            "rawBatchesSaved": _raw_batches,
        }


def clear() -> None:
    global _last_batch
    with _lock:
        _vehicles.clear()
        _seen_at.clear()
        _last_batch = []
