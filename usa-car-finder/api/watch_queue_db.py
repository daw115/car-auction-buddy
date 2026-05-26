"""SQLite store dla kolejki ponownego sprawdzania ("watch queue").

Gdy wyszukiwanie nie znajdzie lotów, user może dodać je do kolejki —
worker w tle (api.main._watch_queue_loop) re-runuje search co `interval_hours`
i powiadamia (Telegram) gdy w końcu pojawią się wyniki.

Wzorzec mirrorowany z api/job_db.py i api/telegram_database.py:
thread-lock + sqlite3.Row + CREATE TABLE IF NOT EXISTS + proste CRUD.
Browser-free, synchroniczne (wołane z to_thread lub bezpośrednio).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

_lock = threading.Lock()
_db_path: Optional[Path] = None
_initialized = False


def _default_db_path() -> Path:
    return Path(os.getenv("WATCH_QUEUE_DB_PATH", "data/watch_queue.db"))


def _connect() -> sqlite3.Connection:
    path = _db_path or _default_db_path()
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    global _db_path, _initialized
    with _lock:
        _db_path = (db_path or _default_db_path()).resolve()
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS watch_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT,
                    request_json TEXT NOT NULL,
                    interval_hours INTEGER NOT NULL,
                    chat_id INTEGER,
                    created_at TEXT NOT NULL,
                    last_run_at TEXT,
                    next_run_at TEXT NOT NULL,
                    runs_count INTEGER NOT NULL DEFAULT 0,
                    last_result_count INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'active'
                );
                CREATE INDEX IF NOT EXISTS idx_watch_due
                    ON watch_entries(active, next_run_at);
                """
            )
        _initialized = True


def add_watch(
    *,
    request_json: str,
    label: Optional[str],
    interval_hours: int,
    chat_id: Optional[int],
    created_at: str,
    next_run_at: str,
) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            """INSERT INTO watch_entries
               (label, request_json, interval_hours, chat_id, created_at, next_run_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (label, request_json, int(interval_hours), chat_id, created_at, next_run_at),
        )
        return int(cur.lastrowid)


def list_active() -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watch_entries WHERE active = 1 ORDER BY next_run_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_due(now_iso: str) -> list[dict]:
    """Aktywne wpisy których next_run_at już minął."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watch_entries WHERE active = 1 AND next_run_at <= ? "
            "ORDER BY next_run_at ASC",
            (now_iso,),
        ).fetchall()
    return [dict(r) for r in rows]


def get(watch_id: int) -> Optional[dict]:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM watch_entries WHERE id = ?", (watch_id,)
        ).fetchone()
    return dict(row) if row else None


def mark_run(watch_id: int, *, last_run_at: str, next_run_at: str, result_count: int) -> None:
    """Po re-runie bez wyników — przesuń next_run_at, zwiększ licznik."""
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE watch_entries
               SET last_run_at = ?, next_run_at = ?, runs_count = runs_count + 1,
                   last_result_count = ?
               WHERE id = ?""",
            (last_run_at, next_run_at, int(result_count), watch_id),
        )


def mark_found(watch_id: int, *, last_run_at: str, result_count: int) -> None:
    """Re-run znalazł loty — dezaktywuj (spełnione)."""
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE watch_entries
               SET last_run_at = ?, runs_count = runs_count + 1,
                   last_result_count = ?, active = 0, status = 'found'
               WHERE id = ?""",
            (last_run_at, int(result_count), watch_id),
        )


def deactivate(watch_id: int) -> bool:
    """Ręczne anulowanie wpisu przez usera."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE watch_entries SET active = 0, status = 'cancelled' "
            "WHERE id = ? AND active = 1",
            (watch_id,),
        )
        return cur.rowcount > 0


def count_active() -> int:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM watch_entries WHERE active = 1"
        ).fetchone()
    return int(row["n"]) if row else 0
