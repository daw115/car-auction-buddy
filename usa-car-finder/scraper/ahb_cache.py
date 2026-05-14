"""On-disk JSON cache for AutoHelperBot per-lot enrichment data.

Stores extension data (seller_type, full_vin, seller_reserve_usd, delivery_cost,
etc.) keyed by `{source}:{lot_id}` (e.g. `copart:12345678` or `iaai:45580538`).
60-day TTL by default — same lot relisted later will get fresh fetch.

Goal: 2nd scrape of same lot within TTL = 0 AHB calls = ~10-20s/lot saved.

Browser-free, no asyncio. Threadsafe via per-process file lock (best effort).
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

_TIMESTAMPS_KEY = "_ts"
_lock = threading.Lock()


def _read_int_env(name: str, default: int, min_value: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return max(min_value, value)


DEFAULT_CACHE_TTL_DAYS = _read_int_env("AHB_CACHE_TTL_DAYS", 60, min_value=0)


def cache_enabled() -> bool:
    return os.getenv("AHB_CACHE_ENABLED", "true").lower() == "true"


def cache_path() -> Path:
    return Path(os.getenv("AHB_CACHE_PATH", "data/ahb_cache.json"))


def _normalize_lot_id(lot_id: str) -> str:
    return re.sub(r"\D+", "", str(lot_id or ""))


def _make_key(source: str, lot_id: str) -> Optional[str]:
    norm = _normalize_lot_id(lot_id)
    if not norm or not source:
        return None
    return f"{source.lower()}:{norm}"


def _expire_old_entries(cache: dict, ttl_days: int, today: date) -> dict:
    timestamps = cache.get(_TIMESTAMPS_KEY)
    if not isinstance(timestamps, dict) or not timestamps:
        return cache
    cutoff_iso = (today - timedelta(days=ttl_days)).isoformat()
    expired = [
        k for k, ts in timestamps.items()
        if isinstance(ts, str) and ts < cutoff_iso
    ]
    if not expired:
        return cache
    for k in expired:
        cache.pop(k, None)
        timestamps.pop(k, None)
    return cache


def _load_raw(path: Path, ttl_days: Optional[int], today: Optional[date]) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    if ttl_days is not None and ttl_days > 0:
        data = _expire_old_entries(data, ttl_days, today or date.today())
    return data


def get_cached(source: str, lot_id: str) -> Optional[dict]:
    """Returns cached AHB data dict for `{source}:{lot_id}` or None.

    Silent on errors — cache miss = treat as no data.
    """
    if not cache_enabled():
        return None
    key = _make_key(source, lot_id)
    if not key:
        return None
    try:
        with _lock:
            cache = _load_raw(cache_path(), DEFAULT_CACHE_TTL_DAYS, date.today())
        value = cache.get(key)
        if not isinstance(value, dict) or not value:
            return None
        return value
    except Exception:
        return None


def put_cached(source: str, lot_id: str, data: dict) -> None:
    """Persist AHB data for `{source}:{lot_id}` with today's timestamp.

    Skips empty/None data — only writes non-trivial enrichments. Errors are
    swallowed (cache is best-effort, never blocks scrape).
    """
    if not cache_enabled() or not data:
        return
    key = _make_key(source, lot_id)
    if not key:
        return
    try:
        path = cache_path()
        with _lock:
            cache = _load_raw(path, None, None)
            cache[key] = dict(data)
            timestamps = cache.setdefault(_TIMESTAMPS_KEY, {})
            if not isinstance(timestamps, dict):
                timestamps = {}
                cache[_TIMESTAMPS_KEY] = timestamps
            timestamps[key] = date.today().isoformat()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(cache, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception:
        # Best-effort cache — never block scrape on persistence errors.
        pass


def stats() -> dict:
    """Returns cache stats: total entries, expired count, file size."""
    try:
        path = cache_path()
        if not path.exists():
            return {"entries": 0, "size_bytes": 0, "exists": False}
        cache = _load_raw(path, None, None)
        entries = sum(1 for k in cache.keys() if k != _TIMESTAMPS_KEY)
        return {
            "entries": entries,
            "size_bytes": path.stat().st_size,
            "exists": True,
        }
    except Exception:
        return {"entries": 0, "size_bytes": 0, "exists": False, "error": True}
