import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(os.getenv("APP_DATABASE_PATH", "./data/app.db"))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                phone TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_clients_email ON clients(email);
            CREATE INDEX IF NOT EXISTS idx_clients_phone ON clients(phone);

            CREATE TABLE IF NOT EXISTS search_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                notes TEXT,
                criteria_json TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                artifact_urls_json TEXT NOT NULL DEFAULT '{}',
                collected_count INTEGER NOT NULL DEFAULT 0,
                analysis_notice TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (client_id) REFERENCES clients(id)
            );

            CREATE INDEX IF NOT EXISTS idx_search_records_client_id ON search_records(client_id);
            CREATE INDEX IF NOT EXISTS idx_search_records_created_at ON search_records(created_at);
            """
        )


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def upsert_client(client: Optional[dict[str, Any]]) -> Optional[int]:
    client = client or {}
    name = _clean_text(client.get("name"))
    email = _clean_text(client.get("email"))
    phone = _clean_text(client.get("phone"))
    notes = _clean_text(client.get("notes"))

    if not any([name, email, phone, notes]):
        return None

    now = _now()
    with _connect() as conn:
        existing = None
        if email:
            existing = conn.execute(
                "SELECT * FROM clients WHERE lower(email) = lower(?) LIMIT 1",
                (email,),
            ).fetchone()
        if existing is None and phone:
            existing = conn.execute(
                "SELECT * FROM clients WHERE phone = ? LIMIT 1",
                (phone,),
            ).fetchone()

        if existing:
            client_id = int(existing["id"])
            conn.execute(
                """
                UPDATE clients
                SET
                    name = COALESCE(?, name),
                    email = COALESCE(?, email),
                    phone = COALESCE(?, phone),
                    notes = COALESCE(?, notes),
                    updated_at = ?
                WHERE id = ?
                """,
                (name, email, phone, notes, now, client_id),
            )
            return client_id

        cursor = conn.execute(
            """
            INSERT INTO clients (name, email, phone, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, email, phone, notes, now, now),
        )
        return int(cursor.lastrowid)


def save_search_record(
    *,
    client_id: Optional[int],
    title: str,
    criteria: dict[str, Any],
    request_data: dict[str, Any],
    response_data: dict[str, Any],
    artifact_urls: dict[str, str],
    collected_count: int,
    analysis_notice: Optional[str],
    notes: Optional[str] = None,
) -> int:
    now = _now()
    with _connect() as conn:
        response_data = dict(response_data or {})
        cursor = conn.execute(
            """
            INSERT INTO search_records (
                client_id, title, notes, criteria_json, request_json, response_json,
                artifact_urls_json, collected_count, analysis_notice, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                title,
                _clean_text(notes),
                json.dumps(criteria, ensure_ascii=False),
                json.dumps(request_data, ensure_ascii=False),
                json.dumps(response_data, ensure_ascii=False),
                json.dumps(artifact_urls or {}, ensure_ascii=False),
                int(collected_count or 0),
                analysis_notice,
                now,
                now,
            ),
        )
        record_id = int(cursor.lastrowid)
        response_data["record_id"] = record_id
        response_data["client_id"] = client_id
        conn.execute(
            "UPDATE search_records SET response_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(response_data, ensure_ascii=False), now, record_id),
        )
        return record_id


def _client_from_row(row: sqlite3.Row) -> Optional[dict[str, Any]]:
    if row["client_id"] is None:
        return None
    return {
        "id": row["client_id"],
        "name": row["client_name"],
        "email": row["client_email"],
        "phone": row["client_phone"],
        "notes": row["client_notes"],
    }


def list_records(query: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    limit = max(1, min(int(limit or 50), 200))
    params: list[Any] = []
    where = ""
    if query:
        like = f"%{query.strip()}%"
        where = """
        WHERE sr.title LIKE ?
           OR c.name LIKE ?
           OR c.email LIKE ?
           OR c.phone LIKE ?
           OR sr.criteria_json LIKE ?
        """
        params.extend([like, like, like, like, like])

    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                sr.id, sr.client_id, sr.title, sr.status, sr.notes,
                sr.collected_count, sr.analysis_notice, sr.artifact_urls_json,
                sr.created_at, sr.updated_at,
                c.name AS client_name, c.email AS client_email,
                c.phone AS client_phone, c.notes AS client_notes
            FROM search_records sr
            LEFT JOIN clients c ON c.id = sr.client_id
            {where}
            ORDER BY sr.created_at DESC, sr.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    records = []
    for row in rows:
        records.append(
            {
                "id": row["id"],
                "title": row["title"],
                "status": row["status"],
                "notes": row["notes"],
                "client": _client_from_row(row),
                "collected_count": row["collected_count"],
                "analysis_notice": row["analysis_notice"],
                "artifact_urls": json.loads(row["artifact_urls_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return records


def get_record(record_id: int) -> Optional[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                sr.*,
                c.name AS client_name, c.email AS client_email,
                c.phone AS client_phone, c.notes AS client_notes
            FROM search_records sr
            LEFT JOIN clients c ON c.id = sr.client_id
            WHERE sr.id = ?
            """,
            (record_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "notes": row["notes"],
        "client": _client_from_row(row),
        "criteria": json.loads(row["criteria_json"]),
        "request": json.loads(row["request_json"]),
        "response": json.loads(row["response_json"]),
        "artifact_urls": json.loads(row["artifact_urls_json"] or "{}"),
        "collected_count": row["collected_count"],
        "analysis_notice": row["analysis_notice"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
