"""Nasłuch aukcji pod konkretnego klienta — trwałe dane.

Dwie tabele w tym samym pliku SQLite co reszta aplikacji (`APP_DATABASE_PATH`),
bo nasłuch jest częścią obsługi klienta, a nie osobnym systemem.

Sens całości: klient szuka czegoś wąskiego (rocznik, wersja, stan), a takie auta
wjeżdżają na aukcje pojedynczo. Zamiast odpytywać giełdy ręcznie co rano, backend
robi to sam i odzywa się DO BROKERA, gdy wjedzie coś nowego. Do klienta nadal nic
nie wychodzi bez kliknięcia człowieka — nasłuch tylko przygotowuje materiał.

`seen_lots` jest po to, żeby broker nie dostawał tego samego auta co dobę. Klucz
to `source/lot_id`, bo numer lota jest unikalny dopiero w parze z giełdą.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(os.getenv("APP_DATABASE_PATH", "./data/app.db"))

# Ścieżka przypięta na sztywno — jak w sales/db.py. Sama zmienna środowiskowa
# nie wystarcza: kilka modułów scrapera woła `load_dotenv(override=True)`, co
# w połowie testu przywraca wartość z .env i test zaczyna pisać do produkcyjnej
# bazy, nie zgłaszając niczego. Zdarzyło się to przy pisaniu tego modułu.
_forced_path: Optional[Path] = None


def use_database(path) -> None:
    """Przypina bazę na sztywno. Do testów i skryptów jednorazowych."""
    global _forced_path
    _forced_path = Path(path) if path else None

SCHEMA = """
CREATE TABLE IF NOT EXISTS client_watches (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name       TEXT,
    client_phone      TEXT,
    criteria_json     TEXT NOT NULL,
    interval_hours    REAL NOT NULL DEFAULT 12,
    active            INTEGER NOT NULL DEFAULT 1,
    created_at        REAL NOT NULL,
    last_run_at       REAL,
    last_error        TEXT,
    runs              INTEGER NOT NULL DEFAULT 0,
    found_total       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS watch_seen_lots (
    watch_id      INTEGER NOT NULL,
    lot_key       TEXT NOT NULL,
    first_seen_at REAL NOT NULL,
    PRIMARY KEY (watch_id, lot_key)
);

CREATE TABLE IF NOT EXISTS watch_hits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id   INTEGER NOT NULL,
    found_at   REAL NOT NULL,
    lot_key    TEXT NOT NULL,
    lot_json   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hits_watch ON watch_hits(watch_id, found_at DESC);

CREATE INDEX IF NOT EXISTS idx_watches_active ON client_watches(active, last_run_at);
"""


@dataclass
class Watch:
    id: int
    client_name: Optional[str]
    client_phone: Optional[str]
    criteria: dict
    interval_hours: float
    active: bool
    created_at: float
    last_run_at: Optional[float] = None
    last_error: Optional[str] = None
    runs: int = 0
    found_total: int = 0

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "clientName": self.client_name,
            "clientPhone": self.client_phone,
            "criteria": self.criteria,
            "intervalHours": self.interval_hours,
            "active": self.active,
            "createdAt": self.created_at,
            "lastRunAt": self.last_run_at,
            "lastError": self.last_error,
            "runs": self.runs,
            "foundTotal": self.found_total,
        }

    def is_due(self, now: Optional[float] = None) -> bool:
        if not self.active:
            return False
        if self.last_run_at is None:
            return True
        return (now or time.time()) - self.last_run_at >= self.interval_hours * 3600


def _connect() -> sqlite3.Connection:
    path = _forced_path or Path(os.getenv("APP_DATABASE_PATH", str(DB_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def _row_to_watch(row: sqlite3.Row) -> Watch:
    return Watch(
        id=row["id"],
        client_name=row["client_name"],
        client_phone=row["client_phone"],
        criteria=json.loads(row["criteria_json"]),
        interval_hours=float(row["interval_hours"]),
        active=bool(row["active"]),
        created_at=float(row["created_at"]),
        last_run_at=row["last_run_at"],
        last_error=row["last_error"],
        runs=int(row["runs"] or 0),
        found_total=int(row["found_total"] or 0),
    )


def create(
    criteria: dict,
    *,
    client_name: Optional[str] = None,
    client_phone: Optional[str] = None,
    interval_hours: float = 12.0,
) -> Watch:
    """Zakłada nasłuch. Minimalny odstęp to godzina — częściej nie ma sensu,
    bo aukcje nie odświeżają się w minutach, a każdy przebieg to realny scrape."""
    interval = max(1.0, float(interval_hours))
    now = time.time()
    init_db()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO client_watches (client_name, client_phone, criteria_json, "
            "interval_hours, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (client_name, client_phone, json.dumps(criteria, ensure_ascii=False), interval, now),
        )
        watch_id = int(cursor.lastrowid)
    return get(watch_id)  # type: ignore[return-value]


def get(watch_id: int) -> Optional[Watch]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM client_watches WHERE id = ?", (watch_id,)).fetchone()
    return _row_to_watch(row) if row else None


def list_all(*, only_active: bool = False) -> list[Watch]:
    init_db()
    query = "SELECT * FROM client_watches"
    if only_active:
        query += " WHERE active = 1"
    query += " ORDER BY id DESC"
    with _connect() as conn:
        return [_row_to_watch(row) for row in conn.execute(query).fetchall()]


def due(now: Optional[float] = None) -> list[Watch]:
    return [watch for watch in list_all(only_active=True) if watch.is_due(now)]


def set_active(watch_id: int, active: bool) -> Optional[Watch]:
    init_db()
    with _connect() as conn:
        conn.execute(
            "UPDATE client_watches SET active = ? WHERE id = ?", (1 if active else 0, watch_id)
        )
    return get(watch_id)


def delete(watch_id: int) -> bool:
    init_db()
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM client_watches WHERE id = ?", (watch_id,))
        conn.execute("DELETE FROM watch_seen_lots WHERE watch_id = ?", (watch_id,))
    return cursor.rowcount > 0


def lot_key(lot: Any) -> str:
    """Tożsamość lota. Numer jest unikalny dopiero w parze z giełdą."""
    source = getattr(lot, "source", None) or (lot.get("source") if isinstance(lot, dict) else "")
    lot_id = getattr(lot, "lot_id", None) or (lot.get("lot_id") if isinstance(lot, dict) else "")
    return f"{source}/{lot_id}"


def filter_unseen(watch_id: int, lots: list) -> list:
    """Loty, których broker jeszcze nie widział w tym nasłuchu."""
    if not lots:
        return []
    init_db()
    keys = [lot_key(lot) for lot in lots]
    placeholders = ",".join("?" for _ in keys)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT lot_key FROM watch_seen_lots WHERE watch_id = ? AND lot_key IN ({placeholders})",
            (watch_id, *keys),
        ).fetchall()
    seen = {row["lot_key"] for row in rows}
    return [lot for lot, key in zip(lots, keys) if key not in seen]


def mark_seen(watch_id: int, lots: list) -> int:
    if not lots:
        return 0
    now = time.time()
    init_db()
    with _connect() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO watch_seen_lots (watch_id, lot_key, first_seen_at) VALUES (?, ?, ?)",
            [(watch_id, lot_key(lot), now) for lot in lots],
        )
    return len(lots)


def record_run(watch_id: int, *, found: int = 0, error: Optional[str] = None) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            "UPDATE client_watches SET last_run_at = ?, last_error = ?, runs = runs + 1, "
            "found_total = found_total + ? WHERE id = ?",
            (time.time(), error, max(0, found), watch_id),
        )


def record_hits(watch_id: int, lots: list) -> int:
    """Zapamiętuje ZNALEZIONE auta, nie tylko ich liczbę.

    Powiadomienie na Telegramie znika w historii czatu, a licznik „znalezionych 3"
    nie mówi czego. Bez tego broker nie ma jak wrócić do tego, co nasłuch wyłowił
    w nocy — a to jest jedyny powód, dla którego nasłuch w ogóle istnieje.
    """
    if not lots:
        return 0
    now = time.time()
    init_db()
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO watch_hits (watch_id, found_at, lot_key, lot_json) VALUES (?, ?, ?, ?)",
            [
                (
                    watch_id,
                    now,
                    lot_key(lot),
                    json.dumps(
                        lot.model_dump(mode="json") if hasattr(lot, "model_dump") else lot,
                        ensure_ascii=False,
                        default=str,
                    ),
                )
                for lot in lots
            ],
        )
    return len(lots)


def recent_hits(watch_id: Optional[int] = None, *, limit: int = 20) -> list[dict]:
    """Ostatnie znaleziska — całego nasłuchu albo wszystkich naraz."""
    init_db()
    query = "SELECT * FROM watch_hits"
    params: list = []
    if watch_id is not None:
        query += " WHERE watch_id = ?"
        params.append(watch_id)
    query += " ORDER BY found_at DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {"watchId": r["watch_id"], "foundAt": r["found_at"], "lot": json.loads(r["lot_json"])}
        for r in rows
    ]
