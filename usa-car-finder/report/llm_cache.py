"""SQLite cache dla wygenerowanych raportów LLM.

Klucz: (lot_id, source, kind) — np. ("12345678", "copart", "client_llm").
TTL: 24h domyślnie, override przez env LLM_REPORT_CACHE_TTL_HOURS.

Cel: drugi klik tego samego "Rich klient" dla tego samego lota = $0 i 0ms.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("report.llm_cache")

_db_path: Optional[Path] = None
_lock = threading.Lock()
_initialized = False


def _default_db_path() -> Path:
    return Path(os.getenv("LLM_CACHE_DB_PATH", "./data/llm_cache.db"))


def _ttl_seconds() -> int:
    hours = float(os.getenv("LLM_REPORT_CACHE_TTL_HOURS", "24"))
    return int(hours * 3600)


def _enabled() -> bool:
    return os.getenv("LLM_REPORT_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")


def init_db(db_path: Optional[Path] = None) -> None:
    """Tworzy plik DB + tabelę jeśli nie istnieje. Idempotentne."""
    global _db_path, _initialized
    with _lock:
        _db_path = (db_path or _default_db_path()).resolve()
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS llm_reports (
                    cache_key TEXT PRIMARY KEY,
                    lot_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    html TEXT NOT NULL,
                    provider TEXT,
                    model TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    generated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_llm_reports_lot
                    ON llm_reports(lot_id, source, kind, generated_at);
                """
            )
        _initialized = True
        logger.info("[llm_cache] Zainicjalizowano %s", _db_path)


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("llm_cache.init_db() must be called first")
    conn = sqlite3.connect(str(_db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def make_fingerprint(payload: dict) -> str:
    """Stabilny hash istotnych pól wpływających na output (bid, score, damage, repair_estimate).

    Drobne zmiany jak nowe zdjęcie czy whitespace nie powinny inwalidować cache.
    """
    import json as _json
    keys = (
        "ai_score", "ai_recommendation", "current_bid_usd",
        "buy_now_price_usd", "ai_estimated_repair_usd",
        "damage_primary", "damage_secondary", "title_type",
        "odometer_mi", "year", "make", "model",
    )
    subset = {k: payload.get(k) for k in keys if k in payload}
    blob = _json.dumps(subset, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _cache_key(lot_id: str, source: str, kind: str, fingerprint: str) -> str:
    return f"{source}::{lot_id}::{kind}::{fingerprint}"


def _ensure_init() -> bool:
    """Lazy init dla użytku poza API lifespan (CLI skrypty, testy)."""
    if _initialized:
        return True
    try:
        init_db()
        return _initialized
    except Exception:
        logger.exception("[llm_cache] lazy init failed")
        return False


def get_cached(
    lot_id: str,
    source: str,
    kind: str,
    fingerprint: str,
) -> Optional[str]:
    """Zwraca HTML z cache jeśli świeży (w TTL), inaczej None."""
    if not _enabled():
        return None
    if not _initialized and not _ensure_init():
        return None
    if not lot_id or not kind:
        return None

    cache_key = _cache_key(lot_id, source or "", kind, fingerprint)
    cutoff = (datetime.utcnow() - timedelta(seconds=_ttl_seconds())).isoformat(timespec="seconds")

    try:
        with _lock, _connect() as conn:
            row = conn.execute(
                "SELECT html, generated_at FROM llm_reports "
                "WHERE cache_key = ? AND generated_at >= ?",
                (cache_key, cutoff),
            ).fetchone()
    except Exception:
        logger.exception("[llm_cache] get_cached failed")
        return None

    if not row:
        return None
    logger.info("[llm_cache] HIT %s::%s::%s (gen %s)", source, lot_id, kind, row["generated_at"])
    return row["html"]


def store(
    lot_id: str,
    source: str,
    kind: str,
    fingerprint: str,
    html: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
) -> None:
    """Zapisuje (upsert) wygenerowany HTML do cache."""
    if not _enabled():
        return
    if not _initialized and not _ensure_init():
        return
    if not lot_id or not kind or not html:
        return

    cache_key = _cache_key(lot_id, source or "", kind, fingerprint)
    now = datetime.utcnow().isoformat(timespec="seconds")

    try:
        with _lock, _connect() as conn:
            conn.execute(
                """
                INSERT INTO llm_reports
                  (cache_key, lot_id, source, kind, fingerprint, html,
                   provider, model, input_tokens, output_tokens, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                  html = excluded.html,
                  provider = excluded.provider,
                  model = excluded.model,
                  input_tokens = excluded.input_tokens,
                  output_tokens = excluded.output_tokens,
                  generated_at = excluded.generated_at
                """,
                (
                    cache_key, lot_id, source or "", kind, fingerprint, html,
                    provider, model, input_tokens, output_tokens, now,
                ),
            )
        logger.info("[llm_cache] STORE %s::%s::%s (%d chars)", source, lot_id, kind, len(html))
    except Exception:
        logger.exception("[llm_cache] store failed")


def stats() -> dict:
    """Statystyki dla diagnostyki."""
    if not _initialized:
        return {"enabled": _enabled(), "initialized": False}
    cutoff = (datetime.utcnow() - timedelta(seconds=_ttl_seconds())).isoformat(timespec="seconds")
    try:
        with _lock, _connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM llm_reports").fetchone()["c"]
            fresh = conn.execute(
                "SELECT COUNT(*) AS c FROM llm_reports WHERE generated_at >= ?", (cutoff,)
            ).fetchone()["c"]
            by_kind = {
                r["kind"]: r["c"]
                for r in conn.execute(
                    "SELECT kind, COUNT(*) AS c FROM llm_reports GROUP BY kind"
                ).fetchall()
            }
        return {
            "enabled": _enabled(),
            "initialized": True,
            "ttl_hours": _ttl_seconds() / 3600,
            "total": total,
            "fresh": fresh,
            "by_kind": by_kind,
        }
    except Exception:
        logger.exception("[llm_cache] stats failed")
        return {"enabled": _enabled(), "initialized": True, "error": "stats_failed"}


def clear_all() -> int:
    """Usuwa wszystkie wpisy. Zwraca ile usunięto."""
    if not _initialized:
        return 0
    try:
        with _lock, _connect() as conn:
            cur = conn.execute("DELETE FROM llm_reports")
            return cur.rowcount or 0
    except Exception:
        logger.exception("[llm_cache] clear_all failed")
        return 0


def purge_expired() -> int:
    """Usuwa wpisy starsze niż TTL. Zwraca ile usunięto."""
    if not _initialized:
        return 0
    cutoff = (datetime.utcnow() - timedelta(seconds=_ttl_seconds())).isoformat(timespec="seconds")
    try:
        with _lock, _connect() as conn:
            cur = conn.execute("DELETE FROM llm_reports WHERE generated_at < ?", (cutoff,))
            return cur.rowcount or 0
    except Exception:
        logger.exception("[llm_cache] purge_expired failed")
        return 0
