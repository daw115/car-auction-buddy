"""On-disk JSON cache for bidfax lookups.

Stores {lot_or_vin: (price, vin, url)} plus a reserved `_ts` map of
{key: "YYYY-MM-DD"} write timestamps. Loads with `ttl_days` silently drop
entries older than that; legacy entries without timestamps are kept.

Browser-free, no asyncio.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

from .bidfax_parsing import IN_PROGRESS

_TIMESTAMPS_KEY = "_ts"


def _read_int_env(name: str, default: int, min_value: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return max(min_value, value)


DEFAULT_CACHE_TTL_DAYS = _read_int_env("BIDFAX_CACHE_TTL_DAYS", 60, min_value=0)


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


def load_cache(
    path: Path,
    *,
    ttl_days: int | None = None,
    today: date | None = None,
) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    cache: dict = {}
    for k, v in data.items():
        if k == _TIMESTAMPS_KEY:
            cache[k] = dict(v) if isinstance(v, dict) else {}
        elif isinstance(v, list):
            cache[k] = tuple(v)
        else:
            cache[k] = v
    if ttl_days is not None and ttl_days > 0:
        cache = _expire_old_entries(cache, ttl_days, today or date.today())
    return cache


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialisable = {
        k: (list(v) if isinstance(v, tuple) else v)
        for k, v in cache.items()
    }
    path.write_text(
        json.dumps(serialisable, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def cache_results(
    cache_path: Path,
    fetched: dict[str, tuple[str, str, str]],
    *,
    today: date | None = None,
) -> dict[str, tuple]:
    """Merge `fetched` into the cache, persisting only final (non-IN_PROGRESS)
    results. Each new entry gets today's timestamp."""
    cache = load_cache(cache_path)
    timestamps: dict = cache.setdefault(_TIMESTAMPS_KEY, {})
    today_iso = (today or date.today()).isoformat()
    for q, v in fetched.items():
        if v[0] == IN_PROGRESS:
            continue
        cache[q] = v
        timestamps[q] = today_iso
    save_cache(cache_path, cache)
    return cache
