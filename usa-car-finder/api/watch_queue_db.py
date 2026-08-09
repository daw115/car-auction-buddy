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

# --- Native scheduled-search additive migration ---------------------------
# Value written into watch_entries.schedule_kind for native scheduled searches.
# Existing (legacy retry-until-found) rows keep schedule_kind IS NULL and are
# never backfilled, reclassified or rewritten by the migration below.
SCHEDULE_KIND = "scheduled_recurring_v1"

# Nullable / default-safe columns added to watch_entries. Each entry is
# (column_name, column_ddl). Added only when structurally absent
# (PRAGMA table_info), so re-running the migration is a no-op.
_NATIVE_SCHEDULE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("schedule_kind", "schedule_kind TEXT"),
    ("owner_site_user", "owner_site_user TEXT"),
    ("notifications_enabled", "notifications_enabled INTEGER NOT NULL DEFAULT 0"),
    ("deleted_at", "deleted_at TEXT"),
    ("updated_at", "updated_at TEXT"),
    ("updated_by_site_user", "updated_by_site_user TEXT"),
    ("version", "version INTEGER NOT NULL DEFAULT 1"),
    ("last_execution_status", "last_execution_status TEXT"),
    ("last_error_code", "last_error_code TEXT"),
    ("last_error_message", "last_error_message TEXT"),
    ("in_flight_execution_id", "in_flight_execution_id TEXT"),
)

# Ledger tables + indexes. Every statement is individually idempotent
# (IF NOT EXISTS), so the whole migration can be re-applied as a no-op.
# NOTE on Search_Record job_id uniqueness (design "Controlled additive SQLite
# migration"): exactly-once record linkage also needs a UNIQUE non-null job_id
# guarantee in the *record* store. That store lives in a separate database
# (api/client_database.py -> search_records) and today only has a NON-unique
# index (idx_search_records_job_id). Adding that unique index requires the
# structurally confirmed fixture/staging record schema and is intentionally
# deferred to task 5.1; this watch_queue.db migration does not touch it and
# does not guess production schema names.
_SCHEDULE_LEDGER_STATEMENTS: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_native_schedule_due "
    "ON watch_entries(schedule_kind, active, deleted_at, next_run_at)",
    "CREATE INDEX IF NOT EXISTS idx_native_schedule_owner "
    "ON watch_entries(schedule_kind, owner_site_user, active, deleted_at)",
    """CREATE TABLE IF NOT EXISTS schedule_executions (
        id TEXT PRIMARY KEY,
        schedule_id INTEGER NOT NULL,
        owner_site_user TEXT NOT NULL,
        scheduled_for TEXT NOT NULL,
        criteria_snapshot_json TEXT NOT NULL,
        interval_hours_snapshot INTEGER NOT NULL
            CHECK(interval_hours_snapshot BETWEEN 1 AND 168),
        status TEXT NOT NULL,
        lease_token_hash TEXT,
        lease_generation INTEGER NOT NULL DEFAULT 0,
        lease_expires_at TEXT,
        heartbeat_at TEXT,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        job_id TEXT,
        record_id INTEGER,
        result_count INTEGER,
        error_code TEXT,
        error_message TEXT,
        error_retryable INTEGER,
        notification_status TEXT NOT NULL DEFAULT 'not_requested',
        notification_attempts INTEGER NOT NULL DEFAULT 0,
        started_at TEXT,
        finished_at TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(schedule_id, scheduled_for)
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_schedule_execution_job "
    "ON schedule_executions(job_id) WHERE job_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_schedule_execution_record "
    "ON schedule_executions(record_id) WHERE record_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_schedule_execution_history "
    "ON schedule_executions(schedule_id, created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_execution_claim "
    "ON schedule_executions(status, lease_expires_at, scheduled_for)",
    """CREATE TABLE IF NOT EXISTS schedule_execution_attempts (
        execution_id TEXT NOT NULL,
        attempt_no INTEGER NOT NULL CHECK(attempt_no BETWEEN 1 AND 3),
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        error_code TEXT,
        error_message TEXT,
        PRIMARY KEY(execution_id, attempt_no)
    )""",
    """CREATE TABLE IF NOT EXISTS schedule_notifications (
        execution_id TEXT NOT NULL,
        channel TEXT NOT NULL CHECK(channel = 'telegram_global'),
        enabled_snapshot INTEGER NOT NULL,
        status TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0
            CHECK(attempt_count BETWEEN 0 AND 2),
        error_code TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(execution_id, channel)
    )""",
)


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
            # Migracja dla istniejących baz (ALTER TABLE nie jest IF NOT EXISTS w SQLite).
            existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(watch_entries)")}
            if "recurring" not in existing_cols:
                conn.execute("ALTER TABLE watch_entries ADD COLUMN recurring INTEGER NOT NULL DEFAULT 0")
            if "preferred_hour" not in existing_cols:
                conn.execute("ALTER TABLE watch_entries ADD COLUMN preferred_hour INTEGER")
            _apply_schedule_migration(conn)
        _initialized = True


def add_watch(
    *,
    request_json: str,
    label: Optional[str],
    interval_hours: int,
    chat_id: Optional[int],
    created_at: str,
    next_run_at: str,
    recurring: bool = False,
    preferred_hour: Optional[int] = None,
) -> int:
    with _lock, _connect() as conn:
        cur = conn.execute(
            """INSERT INTO watch_entries
               (label, request_json, interval_hours, chat_id, created_at, next_run_at,
                recurring, preferred_hour)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                label, request_json, int(interval_hours), chat_id, created_at, next_run_at,
                1 if recurring else 0, preferred_hour,
            ),
        )
        return int(cur.lastrowid)


def list_active() -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watch_entries WHERE active = 1 AND schedule_kind IS NULL ORDER BY next_run_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_due(now_iso: str) -> list[dict]:
    """Aktywne wpisy których next_run_at już minął."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watch_entries WHERE active = 1 AND schedule_kind IS NULL AND next_run_at <= ? "
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
    """Re-run znalazł loty — dezaktywuj (spełnione). Tylko dla watchy jednorazowych
    (recurring=0) — 'powiadom mnie jak coś się pojawi, potem przestań'."""
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE watch_entries
               SET last_run_at = ?, runs_count = runs_count + 1,
                   last_result_count = ?, active = 0, status = 'found'
               WHERE id = ?""",
            (last_run_at, int(result_count), watch_id),
        )


def mark_run_recurring(watch_id: int, *, last_run_at: str, next_run_at: str, result_count: int) -> None:
    """Re-run wpisu recurring=1 — NIE dezaktywuje, zawsze planuje kolejne
    uruchomienie (niezależnie czy znaleziono loty czy nie). 'sprawdzaj codziennie'."""
    with _lock, _connect() as conn:
        conn.execute(
            """UPDATE watch_entries
               SET last_run_at = ?, next_run_at = ?, runs_count = runs_count + 1,
                   last_result_count = ?, status = 'active'
               WHERE id = ?""",
            (last_run_at, next_run_at, int(result_count), watch_id),
        )


def deactivate(watch_id: int) -> bool:
    """Ręczne anulowanie wpisu przez usera."""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE watch_entries SET active = 0, status = 'cancelled' "
            "WHERE id = ? AND active = 1 AND schedule_kind IS NULL",
            (watch_id,),
        )
        return cur.rowcount > 0


def count_active() -> int:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM watch_entries WHERE active = 1 AND schedule_kind IS NULL"
        ).fetchone()
    return int(row["n"]) if row else 0


def _apply_schedule_migration(conn: sqlite3.Connection) -> None:
    """Apply the additive native-schedule migration on an OPEN connection.

    Adds nullable/default-safe columns to ``watch_entries`` plus the ledger
    tables (``schedule_executions``, ``schedule_execution_attempts``,
    ``schedule_notifications``) and their indexes, per the design section
    "Controlled additive SQLite migration".

    Idempotency: columns are added only when structurally absent (checked via
    ``PRAGMA table_info``) and every table/index uses ``IF NOT EXISTS``, so a
    second run is a no-op. The work runs inside a single transaction when this
    function opens it, so a failure rolls back cleanly.

    This migration NEVER backfills, reclassifies, rewrites, selects or prints
    existing rows: pre-existing (legacy) rows keep ``schedule_kind IS NULL``.
    """
    manage_txn = not conn.in_transaction
    if manage_txn:
        conn.execute("BEGIN")
    try:
        existing_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(watch_entries)")
        }
        for name, column_ddl in _NATIVE_SCHEDULE_COLUMNS:
            if name not in existing_cols:
                conn.execute(f"ALTER TABLE watch_entries ADD COLUMN {column_ddl}")
        for statement in _SCHEDULE_LEDGER_STATEMENTS:
            conn.execute(statement)
        if manage_txn:
            conn.execute("COMMIT")
    except Exception:
        if manage_txn:
            conn.execute("ROLLBACK")
        raise


def apply_schedule_migration(db_path: Optional[Path] = None) -> None:
    """Run the additive native-schedule migration against a fixture/temp DB.

    Intended for tests and controlled deployment tooling operating on a
    structural copy. It opens its own connection and commits on success. It
    does not read or write any production database; callers are responsible for
    supplying an isolated ``db_path`` (see tests/isolation_guard.py).
    """
    path = (db_path or _db_path or _default_db_path())
    with _lock, sqlite3.connect(str(path), timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        _apply_schedule_migration(conn)
