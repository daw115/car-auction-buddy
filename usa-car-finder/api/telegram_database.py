"""SQLite store dla subskrybentów Telegrama (multi-user broadcast).

Każdy broker rejestruje się komendą `/start <CODE>` u bota. Po rejestracji
otrzymuje powiadomienia o KAŻDYM zakończonym jobie scrape (broadcast model).

Domyślnie wysyłamy 3 zbiorcze HTML bundle:
- klient_short_bundle (POLECAM, template)
- client_bundle (POLECAM, hybrid LLM)
- broker_bundle (wszystkie + Otomoto)
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from api._time_utils import utc_now_iso

DB_PATH = Path(os.getenv("APP_DATABASE_PATH", "./data/app.db"))


def _now() -> str:
    """Aware UTC ISO (z '+00:00') — patrz api/client_database._now()."""
    return utc_now_iso()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS telegram_subscribers (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                notify_done INTEGER NOT NULL DEFAULT 1,
                notify_error INTEGER NOT NULL DEFAULT 1,
                notify_cancelled INTEGER NOT NULL DEFAULT 0,
                send_bundles INTEGER NOT NULL DEFAULT 1,
                total_received INTEGER NOT NULL DEFAULT 0,
                last_received_at TEXT,
                last_seen_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_telegram_subscribers_active
                ON telegram_subscribers(active);

            CREATE TABLE IF NOT EXISTS telegram_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )


def register(
    chat_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> bool:
    """Rejestruje subskrybenta lub reaktywuje istniejącego.

    Zwraca True gdy NOWY rekord, False gdy reaktywacja istniejącego.
    """
    init_db()
    now = _now()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT chat_id, active FROM telegram_subscribers WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        if existing is not None:
            conn.execute(
                """
                UPDATE telegram_subscribers
                SET active = 1,
                    username = COALESCE(?, username),
                    first_name = COALESCE(?, first_name),
                    last_name = COALESCE(?, last_name),
                    last_seen_at = ?
                WHERE chat_id = ?
                """,
                (username, first_name, last_name, now, chat_id),
            )
            return False
        conn.execute(
            """
            INSERT INTO telegram_subscribers
                (chat_id, username, first_name, last_name, registered_at,
                 active, notify_done, notify_error, notify_cancelled,
                 send_bundles, total_received, last_seen_at)
            VALUES (?, ?, ?, ?, ?, 1, 1, 1, 0, 1, 0, ?)
            """,
            (chat_id, username, first_name, last_name, now, now),
        )
        return True


def deactivate(chat_id: int) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE telegram_subscribers SET active = 0 WHERE chat_id = ?",
            (chat_id,),
        )
        return cur.rowcount > 0


def get_subscriber(chat_id: int) -> Optional[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM telegram_subscribers WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return dict(row) if row else None


def list_active_subscribers(
    *,
    notify_done: Optional[bool] = None,
    notify_error: Optional[bool] = None,
    notify_cancelled: Optional[bool] = None,
) -> list[dict[str, Any]]:
    """Zwraca aktywnych subskrybentów. Opcjonalnie filtruje po preferencjach."""
    init_db()
    where = ["active = 1"]
    if notify_done is True:
        where.append("notify_done = 1")
    if notify_error is True:
        where.append("notify_error = 1")
    if notify_cancelled is True:
        where.append("notify_cancelled = 1")
    sql = f"SELECT * FROM telegram_subscribers WHERE {' AND '.join(where)}"
    with _connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def list_all_subscribers() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM telegram_subscribers ORDER BY registered_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_preferences(
    chat_id: int,
    *,
    notify_done: Optional[bool] = None,
    notify_error: Optional[bool] = None,
    notify_cancelled: Optional[bool] = None,
    send_bundles: Optional[bool] = None,
) -> bool:
    init_db()
    fields = []
    values: list[Any] = []
    if notify_done is not None:
        fields.append("notify_done = ?")
        values.append(1 if notify_done else 0)
    if notify_error is not None:
        fields.append("notify_error = ?")
        values.append(1 if notify_error else 0)
    if notify_cancelled is not None:
        fields.append("notify_cancelled = ?")
        values.append(1 if notify_cancelled else 0)
    if send_bundles is not None:
        fields.append("send_bundles = ?")
        values.append(1 if send_bundles else 0)
    if not fields:
        return False
    values.append(chat_id)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE telegram_subscribers SET {', '.join(fields)} WHERE chat_id = ?",
            values,
        )
        return cur.rowcount > 0


def record_delivery(chat_id: int) -> None:
    """Zwiększa licznik odebranych powiadomień."""
    init_db()
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE telegram_subscribers
            SET total_received = total_received + 1,
                last_received_at = ?
            WHERE chat_id = ?
            """,
            (now, chat_id),
        )


def get_state(key: str) -> Optional[str]:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM telegram_state WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO telegram_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def stats() -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM telegram_subscribers").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM telegram_subscribers WHERE active = 1"
        ).fetchone()[0]
        deliveries = conn.execute(
            "SELECT COALESCE(SUM(total_received), 0) FROM telegram_subscribers"
        ).fetchone()[0]
    return {
        "total": int(total),
        "active": int(active),
        "total_deliveries": int(deliveries),
    }
