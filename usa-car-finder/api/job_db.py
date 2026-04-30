"""SQLite-backed persistence dla job store.

Trzymamy minimalny snapshot Job + listy faz w jednej tabeli (faz nie ma dużo,
JSON wystarczy). Wszystkie operacje są synchroniczne — wołane z asyncio przez
asyncio.to_thread, żeby nie blokować event loopa.

Zapisywane są wyłącznie zmiany stanu (status / phases / result / error).
Kolejka SSE (asyncio.Queue) NIE jest persystowana — to runtime-only.

Idempotency: criteria_hash jest indeksem; find_reusable_job zwraca:
  * job o statusie "running" z tym hashem (zawsze reużywalny — tę samą pracę robimy raz)
  * job o statusie "done" z finished_at w oknie TTL
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("api.job_db")

_db_path: Optional[Path] = None
_lock = threading.Lock()
_initialized = False


def _default_db_path() -> Path:
    return Path(os.getenv("JOB_DB_PATH", "./data/jobs.db"))


def init_db(db_path: Optional[Path] = None) -> None:
    """Tworzy plik DB + tabelę jeśli nie istnieje. Idempotentne."""
    global _db_path, _initialized
    with _lock:
        _db_path = (db_path or _default_db_path()).resolve()
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    phases_json TEXT NOT NULL DEFAULT '[]',
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    criteria_hash TEXT,
                    request_json TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_hash_status
                    ON jobs(criteria_hash, status, finished_at);
                """
            )
        _initialized = True
        logger.info("[job_db] Zainicjalizowano %s", _db_path)


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("job_db.init_db() must be called first")
    conn = sqlite3.connect(str(_db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def persist_job(job_row: dict) -> None:
    """Upsert jobu. job_row to dict z polami zgodnymi z kolumnami tabeli."""
    if not _initialized:
        return
    cols = (
        "id", "status", "phases_json", "result_json", "error",
        "created_at", "finished_at", "cancel_requested", "criteria_hash", "request_json",
    )
    values = tuple(job_row.get(c) for c in cols)
    placeholders = ",".join(["?"] * len(cols))
    update_clause = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    sql = (
        f"INSERT INTO jobs ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {update_clause}"
    )
    with _lock, _connect() as conn:
        conn.execute(sql, values)


def load_all_rows() -> list[dict]:
    if not _initialized:
        return []
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def find_reusable_row(criteria_hash: str, ttl_seconds: int) -> Optional[dict]:
    """Zwraca wiersz nadającego się do re-use lub None.

    Reguły:
    - status='running' z tym hashem -> zawsze re-use (ta sama praca trwa już)
    - status='done' z finished_at >= (now - ttl_seconds) -> re-use
    - error/cancelled/interrupted -> nigdy
    """
    if not _initialized or not criteria_hash:
        return None

    cutoff = (datetime.utcnow() - timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
    with _lock, _connect() as conn:
        # Najpierw running (najświeższy)
        row = conn.execute(
            "SELECT * FROM jobs WHERE criteria_hash=? AND status='running' "
            "ORDER BY created_at DESC LIMIT 1",
            (criteria_hash,),
        ).fetchone()
        if row:
            return dict(row)

        # Potem done w oknie TTL
        row = conn.execute(
            "SELECT * FROM jobs WHERE criteria_hash=? AND status='done' "
            "AND finished_at IS NOT NULL AND finished_at >= ? "
            "ORDER BY finished_at DESC LIMIT 1",
            (criteria_hash, cutoff),
        ).fetchone()
        return dict(row) if row else None


def mark_orphaned_running_as_interrupted() -> int:
    """Po restarcie: każdy job 'running' w DB nie ma już swojego asyncio.Task.
    Oznaczamy taki job jako 'interrupted'. Zwraca ile rekordów zaktualizowano.
    """
    if not _initialized:
        return 0
    finished = datetime.utcnow().isoformat(timespec="seconds")
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='interrupted', finished_at=COALESCE(finished_at, ?), "
            "error=COALESCE(error, 'API restart przerwał job') "
            "WHERE status IN ('queued','running')",
            (finished,),
        )
        return cur.rowcount
