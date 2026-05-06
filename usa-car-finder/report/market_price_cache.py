"""SQLite cache dla wyszukiwań cen rynkowych z Otomoto.pl.

Klucz: {make}::{model}::{year_from}-{year_to}::{damaged_only}.
TTL: 7 dni (ceny rynku wtórnego zmieniają się powoli).

Cel: wielokrotne scrape'y dla tego samego make/model/rok = 1 zapytanie do Otomoto.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("report.market_price_cache")

_db_path: Optional[Path] = None
_lock = threading.Lock()
_initialized = False


def _default_db_path() -> Path:
    return Path(os.getenv("MARKET_PRICE_CACHE_DB_PATH", "./data/market_price_cache.db"))


def _ttl_seconds() -> int:
    days = float(os.getenv("MARKET_PRICE_CACHE_TTL_DAYS", "7"))
    return int(days * 86400)


def _enabled() -> bool:
    return os.getenv("MARKET_PRICE_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")


def init_db(db_path: Optional[Path] = None) -> None:
    global _db_path, _initialized
    with _lock:
        _db_path = (db_path or _default_db_path()).resolve()
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS otomoto_lookups (
                    cache_key TEXT PRIMARY KEY,
                    make TEXT NOT NULL,
                    model TEXT,
                    year_from INTEGER,
                    year_to INTEGER,
                    damaged_only INTEGER NOT NULL DEFAULT 0,
                    low_pln INTEGER,
                    high_pln INTEGER,
                    mean_pln INTEGER,
                    median_pln INTEGER,
                    sample_size INTEGER,
                    query_url TEXT,
                    scraped_at TEXT NOT NULL,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_otomoto_make_model
                    ON otomoto_lookups(make, model, scraped_at);
                """
            )
        _initialized = True
        logger.info("[market_price_cache] Zainicjalizowano %s", _db_path)


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("market_price_cache.init_db() must be called first")
    conn = sqlite3.connect(str(_db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_init() -> bool:
    if _initialized:
        return True
    try:
        init_db()
        return _initialized
    except Exception:
        logger.exception("[market_price_cache] lazy init failed")
        return False


def _cache_key(make: str, model: Optional[str], year_from: Optional[int],
               year_to: Optional[int], damaged_only: bool) -> str:
    m = (make or "").strip().lower()
    md = (model or "").strip().lower()
    yf = year_from or 0
    yt = year_to or 0
    d = "1" if damaged_only else "0"
    return f"{m}::{md}::{yf}-{yt}::{d}"


def get_cached(
    make: str,
    model: Optional[str],
    year_from: Optional[int],
    year_to: Optional[int],
    damaged_only: bool = False,
) -> Optional[dict]:
    """Zwraca dict z cache jeśli świeży (w TTL), inaczej None."""
    if not _enabled() or (not _initialized and not _ensure_init()):
        return None

    key = _cache_key(make, model, year_from, year_to, damaged_only)
    cutoff = (datetime.utcnow() - timedelta(seconds=_ttl_seconds())).isoformat(timespec="seconds")

    try:
        with _lock, _connect() as conn:
            row = conn.execute(
                "SELECT * FROM otomoto_lookups WHERE cache_key = ? AND scraped_at >= ?",
                (key, cutoff),
            ).fetchone()
    except Exception:
        logger.exception("[market_price_cache] get_cached failed")
        return None

    if not row:
        return None
    if row["error"]:
        # Negatywny cache (Otomoto blocked) — zwróć None ale loguj
        logger.info("[market_price_cache] negative HIT %s (error: %s)", key, row["error"])
        return None
    logger.info("[market_price_cache] HIT %s (sample %s)", key, row["sample_size"])
    return {
        "low_pln": row["low_pln"],
        "high_pln": row["high_pln"],
        "mean_pln": row["mean_pln"],
        "median_pln": row["median_pln"],
        "sample_size": row["sample_size"],
        "query_url": row["query_url"],
        "scraped_at": row["scraped_at"],
        "cached": True,
    }


def store(
    make: str,
    model: Optional[str],
    year_from: Optional[int],
    year_to: Optional[int],
    damaged_only: bool = False,
    *,
    low_pln: Optional[int] = None,
    high_pln: Optional[int] = None,
    mean_pln: Optional[int] = None,
    median_pln: Optional[int] = None,
    sample_size: Optional[int] = None,
    query_url: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Upsert wpisu (pozytywny lub negatywny — error gdy Otomoto blocked)."""
    if not _enabled() or (not _initialized and not _ensure_init()):
        return

    key = _cache_key(make, model, year_from, year_to, damaged_only)
    now = datetime.utcnow().isoformat(timespec="seconds")

    try:
        with _lock, _connect() as conn:
            conn.execute(
                """
                INSERT INTO otomoto_lookups
                  (cache_key, make, model, year_from, year_to, damaged_only,
                   low_pln, high_pln, mean_pln, median_pln, sample_size,
                   query_url, scraped_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                  low_pln = excluded.low_pln,
                  high_pln = excluded.high_pln,
                  mean_pln = excluded.mean_pln,
                  median_pln = excluded.median_pln,
                  sample_size = excluded.sample_size,
                  query_url = excluded.query_url,
                  scraped_at = excluded.scraped_at,
                  error = excluded.error
                """,
                (
                    key, (make or "").strip(), (model or "").strip() if model else None,
                    year_from, year_to, 1 if damaged_only else 0,
                    low_pln, high_pln, mean_pln, median_pln, sample_size,
                    query_url, now, error,
                ),
            )
        if error:
            logger.info("[market_price_cache] STORE negative %s: %s", key, error)
        else:
            logger.info("[market_price_cache] STORE %s (sample %s, mean %s PLN)", key, sample_size, mean_pln)
    except Exception:
        logger.exception("[market_price_cache] store failed")


def stats() -> dict:
    if not _initialized and not _ensure_init():
        return {"enabled": _enabled(), "initialized": False}
    cutoff = (datetime.utcnow() - timedelta(seconds=_ttl_seconds())).isoformat(timespec="seconds")
    try:
        with _lock, _connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM otomoto_lookups").fetchone()["c"]
            fresh = conn.execute(
                "SELECT COUNT(*) AS c FROM otomoto_lookups WHERE scraped_at >= ?", (cutoff,)
            ).fetchone()["c"]
            negative = conn.execute(
                "SELECT COUNT(*) AS c FROM otomoto_lookups WHERE error IS NOT NULL"
            ).fetchone()["c"]
        return {
            "enabled": _enabled(),
            "initialized": True,
            "ttl_days": _ttl_seconds() / 86400,
            "total": total,
            "fresh": fresh,
            "negative_entries": negative,
        }
    except Exception:
        logger.exception("[market_price_cache] stats failed")
        return {"enabled": _enabled(), "initialized": True, "error": "stats_failed"}


def purge_expired() -> int:
    if not _initialized and not _ensure_init():
        return 0
    cutoff = (datetime.utcnow() - timedelta(seconds=_ttl_seconds())).isoformat(timespec="seconds")
    try:
        with _lock, _connect() as conn:
            cur = conn.execute("DELETE FROM otomoto_lookups WHERE scraped_at < ?", (cutoff,))
            return cur.rowcount or 0
    except Exception:
        logger.exception("[market_price_cache] purge_expired failed")
        return 0
