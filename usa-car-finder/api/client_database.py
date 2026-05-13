import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from api._time_utils import utc_now_iso

DB_PATH = Path(os.getenv("APP_DATABASE_PATH", "./data/app.db"))


def _now() -> str:
    """Aware UTC ISO string (z '+00:00') dla wszystkich created_at/updated_at.

    Wcześniej `datetime.now().isoformat()` = naive LOCAL — psuło duration calc
    (mieszanie z naive UTC stringami z jobs.py daje offset 7200s w CEST/CET).
    """
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

        # Migration: dodaj kolumnę job_id jeśli nie istnieje (do idempotent zapisywania
        # rekordów dla tego samego joba bez duplikacji).
        cols = {row[1] for row in conn.execute("PRAGMA table_info(search_records)").fetchall()}
        if "job_id" not in cols:
            conn.execute("ALTER TABLE search_records ADD COLUMN job_id TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_search_records_job_id ON search_records(job_id)")
        # Migration: duration_seconds (czas trwania scrape, sec)
        if "duration_seconds" not in cols:
            conn.execute("ALTER TABLE search_records ADD COLUMN duration_seconds REAL")

        # Lot feedback — kciuki w górę/dół per lot dla doskonalenia kryteriów
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lot_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                lot_id TEXT NOT NULL,
                source TEXT NOT NULL,
                vote TEXT NOT NULL,
                reason TEXT,
                lot_snapshot TEXT NOT NULL,
                criteria_snapshot TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(record_id, lot_id, source)
            );
            CREATE INDEX IF NOT EXISTS idx_lot_feedback_record ON lot_feedback(record_id);
            CREATE INDEX IF NOT EXISTS idx_lot_feedback_lot ON lot_feedback(lot_id, source);
            CREATE INDEX IF NOT EXISTS idx_lot_feedback_vote ON lot_feedback(vote);
            """
        )


def update_artifact_urls(record_id: int, new_urls: dict) -> bool:
    """Aktualizuje artifact_urls_json dla rekordu (merge z istniejącymi)."""
    init_db()
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT artifact_urls_json FROM search_records WHERE id = ?", (record_id,)
        ).fetchone()
        if not row:
            return False
        existing = json.loads(row["artifact_urls_json"] or "{}")
        merged = {**existing, **{k: v for k, v in new_urls.items() if v}}
        conn.execute(
            "UPDATE search_records SET artifact_urls_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged, ensure_ascii=False), now, record_id),
        )
        return True


def search_record_exists_for_job(job_id: str) -> bool:
    """Sprawdza czy istnieje już search_record dla danego job_id (deduplikacja)."""
    if not job_id:
        return False
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM search_records WHERE job_id = ? LIMIT 1", (job_id,)
        ).fetchone()
    return row is not None


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
    status: str = "new",
    job_id: Optional[str] = None,
    duration_seconds: Optional[float] = None,
) -> int:
    """Zapisuje rekord wyszukiwania.

    status: 'new' (default — DONE z wynikami), 'cancelled', 'error', 'interrupted'.
    job_id: ID powiązanego joba (jeśli pochodzi z queue) — dla traceability.
    duration_seconds: czas trwania scrape w sekundach (od job.created_at do now).
    """
    now = _now()
    with _connect() as conn:
        response_data = dict(response_data or {})
        if job_id and "job_id" not in response_data:
            response_data["job_id"] = job_id
        if duration_seconds is not None and "duration_seconds" not in response_data:
            response_data["duration_seconds"] = float(duration_seconds)
        cursor = conn.execute(
            """
            INSERT INTO search_records (
                client_id, title, status, notes, criteria_json, request_json, response_json,
                artifact_urls_json, collected_count, analysis_notice, job_id,
                duration_seconds, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                title,
                status,
                _clean_text(notes),
                json.dumps(criteria, ensure_ascii=False),
                json.dumps(request_data, ensure_ascii=False),
                json.dumps(response_data, ensure_ascii=False),
                json.dumps(artifact_urls or {}, ensure_ascii=False),
                int(collected_count or 0),
                analysis_notice,
                job_id,
                float(duration_seconds) if duration_seconds is not None else None,
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
                sr.duration_seconds, sr.created_at, sr.updated_at,
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
                "duration_seconds": row["duration_seconds"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return records


def delete_record(record_id: int) -> Optional[dict[str, Any]]:
    """Usuwa rekord z DB. Zwraca artifact_urls + response (do cleanup plików) lub None."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT artifact_urls_json, response_json, criteria_json, title FROM search_records WHERE id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            artifact_urls = json.loads(row["artifact_urls_json"] or "{}")
        except Exception:
            artifact_urls = {}
        try:
            response = json.loads(row["response_json"] or "{}")
        except Exception:
            response = {}
        try:
            criteria = json.loads(row["criteria_json"] or "{}")
        except Exception:
            criteria = {}
        title = row["title"]
        conn.execute("DELETE FROM search_records WHERE id = ?", (record_id,))
    return {
        "artifact_urls": artifact_urls,
        "response": response,
        "criteria": criteria,
        "title": title,
    }


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
        "duration_seconds": row["duration_seconds"] if "duration_seconds" in row.keys() else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Lot feedback (kciuki w górę/dół) — uczenie kryteriów wyszukiwania
# ─────────────────────────────────────────────────────────────────────────────

def save_feedback(
    *,
    record_id: int,
    lot_id: str,
    source: str,
    vote: str,
    reason: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Zapisuje feedback (vote 'up'/'down') dla konkretnego lota z rekordu wyszukiwania.

    Idempotent: drugi vote na ten sam (record_id, lot_id, source) nadpisuje (UPSERT).

    Tworzy snapshoty: lot data + analysis (z response.all_results) i criteria
    z search_records. Pozwala później AI agregować feedback nawet gdy lot/record
    zostanie usunięty.

    Returns: dict z feedback row lub None jeśli rekord/lot nie istnieje.
    """
    init_db()
    if vote not in ("up", "down"):
        raise ValueError("vote must be 'up' or 'down'")
    if not lot_id or not source:
        raise ValueError("lot_id and source required")

    now = _now()
    with _connect() as conn:
        # Pobierz response.all_results z search_records żeby zrobić snapshot lot data
        sr_row = conn.execute(
            "SELECT response_json, criteria_json FROM search_records WHERE id = ?",
            (record_id,),
        ).fetchone()
        if sr_row is None:
            return None

        try:
            response = json.loads(sr_row["response_json"] or "{}")
            criteria = json.loads(sr_row["criteria_json"] or "{}")
        except Exception:
            response = {}
            criteria = {}

        all_results = response.get("all_results") or []
        lot_snapshot = None
        for al in all_results:
            lot = (al.get("lot") or {})
            if str(lot.get("lot_id")) == str(lot_id) and (lot.get("source") or "") == source:
                lot_snapshot = al
                break
        if lot_snapshot is None:
            return None  # lot nie należy do tego rekordu

        # UPSERT: ON CONFLICT na (record_id, lot_id, source) → update vote/reason/snapshot
        conn.execute(
            """
            INSERT INTO lot_feedback
                (record_id, lot_id, source, vote, reason, lot_snapshot, criteria_snapshot,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id, lot_id, source) DO UPDATE SET
                vote = excluded.vote,
                reason = excluded.reason,
                lot_snapshot = excluded.lot_snapshot,
                criteria_snapshot = excluded.criteria_snapshot,
                updated_at = excluded.updated_at
            """,
            (
                record_id, lot_id, source, vote, reason,
                json.dumps(lot_snapshot, ensure_ascii=False),
                json.dumps(criteria, ensure_ascii=False),
                now, now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM lot_feedback WHERE record_id = ? AND lot_id = ? AND source = ?",
            (record_id, lot_id, source),
        ).fetchone()

    return {
        "id": row["id"],
        "record_id": row["record_id"],
        "lot_id": row["lot_id"],
        "source": row["source"],
        "vote": row["vote"],
        "reason": row["reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def delete_feedback(record_id: int, lot_id: str, source: str) -> bool:
    """Usuwa feedback (user wycofuje vote)."""
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM lot_feedback WHERE record_id = ? AND lot_id = ? AND source = ?",
            (record_id, lot_id, source),
        )
        return (cur.rowcount or 0) > 0


def list_feedback_for_record(record_id: int) -> list[dict[str, Any]]:
    """Zwraca listę vote'ów dla danego rekordu (do wyświetlenia w UI)."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, lot_id, source, vote, reason, created_at, updated_at "
            "FROM lot_feedback WHERE record_id = ? ORDER BY created_at",
            (record_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_all_feedback(vote_filter: Optional[str] = None, limit: int = 1000) -> list[dict[str, Any]]:
    """Lista wszystkich feedbacków (admin/analyze). Z snapshotami lot + criteria."""
    init_db()
    where = ""
    params: list[Any] = []
    if vote_filter in ("up", "down"):
        where = "WHERE vote = ?"
        params.append(vote_filter)
    params.append(int(max(1, min(limit, 5000))))

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM lot_feedback
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    result = []
    for r in rows:
        try:
            lot_snap = json.loads(r["lot_snapshot"] or "{}")
        except Exception:
            lot_snap = {}
        try:
            crit_snap = json.loads(r["criteria_snapshot"] or "{}")
        except Exception:
            crit_snap = {}
        result.append({
            "id": r["id"],
            "record_id": r["record_id"],
            "lot_id": r["lot_id"],
            "source": r["source"],
            "vote": r["vote"],
            "reason": r["reason"],
            "lot": lot_snap,
            "criteria": crit_snap,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return result


def feedback_stats() -> dict[str, Any]:
    """Zwraca podsumowanie agregatów feedback (do dashboardu)."""
    init_db()
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM lot_feedback").fetchone()["n"]
        ups = conn.execute("SELECT COUNT(*) AS n FROM lot_feedback WHERE vote = 'up'").fetchone()["n"]
        downs = conn.execute("SELECT COUNT(*) AS n FROM lot_feedback WHERE vote = 'down'").fetchone()["n"]
        with_reason = conn.execute(
            "SELECT COUNT(*) AS n FROM lot_feedback WHERE vote = 'down' AND reason IS NOT NULL AND reason != ''"
        ).fetchone()["n"]
    return {
        "total": total,
        "up": ups,
        "down": downs,
        "down_with_reason": with_reason,
    }
