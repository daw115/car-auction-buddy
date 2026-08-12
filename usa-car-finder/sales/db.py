"""
Baza agenta sprzedażowego — leady, wiadomości i drafty czekające na zgodę.

Trzy tabele w tym samym pliku SQLite, co reszta aplikacji (`APP_DATABASE_PATH`), bo
lead prędzej czy później staje się klientem z `api/client_database.py` i dwie osobne
bazy oznaczałyby łączenie ich w Pythonie przy każdym wyświetleniu skrzynki.

DLACZEGO DRAFTY MAJĄ WŁASNĄ TABELĘ, A NIE FLAGĘ W WIADOMOŚCIACH

Draft to nie jest wiadomość bez daty wysłania. Draft ma uzasadnienie, ma stan
zatwierdzenia i ma wersję poprawioną przez brokera obok wersji zaproponowanej przez
agenta. Odrzucone drafty zostają — to jedyny materiał, z którego da się kiedykolwiek
zobaczyć, w czym agent się myli. Wiadomość powstaje dopiero z zatwierdzonego draftu.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from sales.models import Author, Channel, Draft, Lead, Message, Stage

DB_PATH = Path(os.getenv("APP_DATABASE_PATH", "./data/app.db"))

# Ścieżka wymuszona jawnie, ważniejsza od zmiennej środowiskowej.
#
# POWÓD JEST KONKRETNY, NIE ESTETYCZNY. Kilka modułów scrapera woła
# `load_dotenv(override=True)` na poziomie modułu, a importują się leniwie, w środku
# obsługi żądania. Zmienna `APP_DATABASE_PATH` ustawiona przez test wraca wtedy do
# wartości z `.env` w połowie testu — i test zaczyna pisać do produkcyjnej bazy
# aplikacji, nie zgłaszając niczego. Zdarzyło się to przy pisaniu tego modułu.
_forced_path: Optional[Path] = None


def use_database(path) -> None:
    """Przypina bazę na sztywno. Do testów i skryptów jednorazowych."""
    global _forced_path
    _forced_path = Path(path) if path else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _connect() -> sqlite3.Connection:
    path = _forced_path or Path(os.getenv("APP_DATABASE_PATH", str(DB_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Kolumny dodane po tym, jak tabela `leads` już istniała w produkcji.
# `CREATE TABLE IF NOT EXISTS` ich nie doda, a brak choćby jednej wywraca odczyt
# każdego leada — stąd jawna migracja przy każdym starcie.
_DOKLADANE_KOLUMNY = (
    ("blocked_by", "TEXT"),
    ("trade_in_model", "TEXT"),
    ("trade_in_year", "INTEGER"),
    ("trade_in_value_pln", "REAL"),
    ("trade_in_sold", "INTEGER NOT NULL DEFAULT 0"),
    ("engine_hint", "TEXT"),
    ("trim_hint", "TEXT"),
)


def _migrate_leads(conn) -> None:
    istniejace = {row["name"] for row in conn.execute("PRAGMA table_info(leads)")}
    for nazwa, typ in _DOKLADANE_KOLUMNY:
        if nazwa not in istniejace:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {nazwa} {typ}")


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                phone TEXT,
                email TEXT,
                channel TEXT NOT NULL DEFAULT 'formularz',
                stage TEXT NOT NULL DEFAULT 'nowy',
                raw_request TEXT NOT NULL DEFAULT '',
                make TEXT,
                model TEXT,
                year_from INTEGER,
                year_to INTEGER,
                budget_pln REAL,
                settlement TEXT NOT NULL DEFAULT 'private',
                max_odometer_mi INTEGER,
                timeline_days INTEGER,
                blocked_by TEXT,
                trade_in_model TEXT,
                trade_in_year INTEGER,
                trade_in_value_pln REAL,
                trade_in_sold INTEGER NOT NULL DEFAULT 0,
                engine_hint TEXT,
                trim_hint TEXT,
                damage_ok INTEGER,
                bought_before INTEGER NOT NULL DEFAULT 0,
                referred_by TEXT,
                notes TEXT NOT NULL DEFAULT '',
                client_id INTEGER,
                last_client_message_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);
            CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
            CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);

            CREATE TABLE IF NOT EXISTS lead_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                author TEXT NOT NULL,
                text TEXT NOT NULL,
                channel TEXT,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                sent_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_msg_lead ON lead_messages(lead_id, created_at);

            CREATE TABLE IF NOT EXISTS lead_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                edited_text TEXT,
                channel TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                stage_after TEXT,
                created_at TEXT NOT NULL,
                approved_at TEXT,
                rejected_at TEXT,
                sent_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_draft_lead ON lead_drafts(lead_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_draft_pending
                ON lead_drafts(approved_at, rejected_at);

            -- Wyszukiwania uruchomione z leada. Osobna tabela, a nie kolumny przy
            -- leadzie, bo dla jednego klienta puszcza się scrape wielokrotnie:
            -- po korekcie budżetu, po zmianie rocznika, po przegranej licytacji.
            -- Nadpisywanie poprzedniego wyniku kasowałoby historię tego, co już
            -- klientowi pokazaliśmy.
            CREATE TABLE IF NOT EXISTS lead_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                job_id TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                criteria_json TEXT NOT NULL DEFAULT '{}',
                candidates_json TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_lead_searches
                ON lead_searches(lead_id, created_at DESC);
            """
        )
        _migrate_leads(conn)


# ─────────────────────────────────────────────────────────────────────── leady

_LEAD_COLUMNS = (
    "name", "phone", "email", "channel", "stage", "raw_request", "make", "model",
    "year_from", "year_to", "budget_pln", "settlement", "max_odometer_mi",
    "timeline_days", "blocked_by", "trade_in_model", "trade_in_year",
    "trade_in_value_pln", "trade_in_sold", "engine_hint", "trim_hint",
    "damage_ok", "bought_before", "referred_by", "notes",
    "client_id", "last_client_message_at",
)


def _row_to_lead(row: sqlite3.Row) -> Lead:
    return Lead(
        id=row["id"],
        name=row["name"],
        phone=row["phone"],
        email=row["email"],
        channel=Channel(row["channel"]),
        stage=Stage(row["stage"]),
        raw_request=row["raw_request"] or "",
        make=row["make"],
        model=row["model"],
        year_from=row["year_from"],
        year_to=row["year_to"],
        budget_pln=row["budget_pln"],
        settlement=row["settlement"] or "private",
        max_odometer_mi=row["max_odometer_mi"],
        timeline_days=row["timeline_days"],
        blocked_by=row["blocked_by"],
        trade_in_model=row["trade_in_model"],
        trade_in_year=row["trade_in_year"],
        trade_in_value_pln=row["trade_in_value_pln"],
        trade_in_sold=bool(row["trade_in_sold"]),
        engine_hint=row["engine_hint"],
        trim_hint=row["trim_hint"],
        # SQLite nie ma boola: 0/1 to odpowiedź, NULL to "jeszcze nie pytaliśmy".
        # Te trzy stany są tu istotne, bo od nich zależy waga składowej w ocenie.
        damage_ok=None if row["damage_ok"] is None else bool(row["damage_ok"]),
        bought_before=bool(row["bought_before"]),
        referred_by=row["referred_by"],
        notes=row["notes"] or "",
        client_id=row["client_id"],
        last_client_message_at=_parse_dt(row["last_client_message_at"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


def _lead_values(lead: Lead) -> dict[str, Any]:
    return {
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "channel": lead.channel.value,
        "stage": lead.stage.value,
        "raw_request": lead.raw_request,
        "make": lead.make,
        "model": lead.model,
        "year_from": lead.year_from,
        "year_to": lead.year_to,
        "budget_pln": lead.budget_pln,
        "settlement": lead.settlement,
        "max_odometer_mi": lead.max_odometer_mi,
        "timeline_days": lead.timeline_days,
        "blocked_by": lead.blocked_by,
        "trade_in_model": lead.trade_in_model,
        "trade_in_year": lead.trade_in_year,
        "trade_in_value_pln": lead.trade_in_value_pln,
        "trade_in_sold": 1 if lead.trade_in_sold else 0,
        "engine_hint": lead.engine_hint,
        "trim_hint": lead.trim_hint,
        "damage_ok": None if lead.damage_ok is None else int(lead.damage_ok),
        "bought_before": int(lead.bought_before),
        "referred_by": lead.referred_by,
        "notes": lead.notes,
        "client_id": lead.client_id,
        "last_client_message_at": (
            lead.last_client_message_at.isoformat(timespec="seconds")
            if lead.last_client_message_at
            else None
        ),
    }


def create_lead(lead: Lead) -> Lead:
    init_db()
    values = _lead_values(lead)
    now = _now_iso()
    columns = ", ".join(_LEAD_COLUMNS) + ", created_at, updated_at"
    holders = ", ".join("?" for _ in _LEAD_COLUMNS) + ", ?, ?"
    with _connect() as conn:
        cursor = conn.execute(
            f"INSERT INTO leads ({columns}) VALUES ({holders})",
            [values[c] for c in _LEAD_COLUMNS] + [now, now],
        )
        lead.id = cursor.lastrowid
    lead.created_at = _parse_dt(now)
    lead.updated_at = lead.created_at
    return lead


def update_lead(lead: Lead) -> None:
    if lead.id is None:
        raise ValueError("lead bez id — użyj create_lead")
    init_db()
    values = _lead_values(lead)
    assignments = ", ".join(f"{c} = ?" for c in _LEAD_COLUMNS)
    with _connect() as conn:
        conn.execute(
            f"UPDATE leads SET {assignments}, updated_at = ? WHERE id = ?",
            [values[c] for c in _LEAD_COLUMNS] + [_now_iso(), lead.id],
        )


def get_lead(lead_id: int) -> Optional[Lead]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return _row_to_lead(row) if row else None


def find_lead_by_contact(*, phone: Optional[str] = None, email: Optional[str] = None) -> Optional[Lead]:
    """Ten sam człowiek pisze drugi raz — nie zakładamy mu drugiej kartoteki."""
    if not phone and not email:
        return None
    init_db()
    with _connect() as conn:
        if phone:
            row = conn.execute(
                "SELECT * FROM leads WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,)
            ).fetchone()
            if row:
                return _row_to_lead(row)
        if email:
            row = conn.execute(
                "SELECT * FROM leads WHERE lower(email) = lower(?) ORDER BY id DESC LIMIT 1",
                (email,),
            ).fetchone()
            if row:
                return _row_to_lead(row)
    return None


def list_leads(*, only_open: bool = True) -> list[Lead]:
    init_db()
    closed = (Stage.WYGRANA.value, Stage.STRACONY.value)
    query = "SELECT * FROM leads"
    params: tuple = ()
    if only_open:
        query += " WHERE stage NOT IN (?, ?)"
        params = closed
    query += " ORDER BY updated_at DESC"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_lead(r) for r in rows]


# ─────────────────────────────────────────────────────────────────── wiadomości


def _row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        author=Author(row["author"]),
        text=row["text"],
        channel=Channel(row["channel"]) if row["channel"] else None,
        meta=json.loads(row["meta_json"] or "{}"),
        created_at=_parse_dt(row["created_at"]),
        sent_at=_parse_dt(row["sent_at"]),
    )


def add_message(
    lead_id: int,
    *,
    author: Author,
    text: str,
    channel: Optional[Channel] = None,
    sent: bool = True,
    meta: Optional[dict] = None,
) -> Message:
    """Dopisuje wiadomość do wątku.

    Wiadomość od klienta przesuwa `last_client_message_at`, bo od tego pola zależy
    składowa "zaangażowanie" w ocenie leada — a ocena ma się starzeć sama, bez
    codziennego przeliczania czegokolwiek w tle.
    """
    init_db()
    now = _now_iso()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO lead_messages (lead_id, author, text, channel, meta_json, created_at, sent_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                lead_id,
                author.value,
                text,
                channel.value if channel else None,
                json.dumps(meta or {}, ensure_ascii=False),
                now,
                now if sent else None,
            ),
        )
        if author is Author.KLIENT:
            conn.execute(
                "UPDATE leads SET last_client_message_at = ?, updated_at = ? WHERE id = ?",
                (now, now, lead_id),
            )
        else:
            conn.execute("UPDATE leads SET updated_at = ? WHERE id = ?", (now, lead_id))
        message_id = cursor.lastrowid

    return Message(
        id=message_id,
        author=author,
        text=text,
        channel=channel,
        meta=meta or {},
        created_at=_parse_dt(now),
        sent_at=_parse_dt(now) if sent else None,
    )


def messages(lead_id: int, *, limit: int = 50) -> list[Message]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM lead_messages WHERE lead_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (lead_id, limit),
        ).fetchall()
    return [_row_to_message(r) for r in reversed(rows)]


# ─────────────────────────────────────────────────────────────────────── drafty


def _row_to_draft(row: sqlite3.Row) -> Draft:
    return Draft(
        id=row["id"],
        lead_id=row["lead_id"],
        text=row["text"],
        edited_text=row["edited_text"],
        channel=Channel(row["channel"]),
        rationale=row["rationale"] or "",
        stage_after=Stage(row["stage_after"]) if row["stage_after"] else None,
        created_at=_parse_dt(row["created_at"]),
        approved_at=_parse_dt(row["approved_at"]),
        rejected_at=_parse_dt(row["rejected_at"]),
        sent_at=_parse_dt(row["sent_at"]),
    )


def save_draft(draft: Draft) -> Draft:
    init_db()
    now = _now_iso()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO lead_drafts (lead_id, text, channel, rationale, stage_after, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                draft.lead_id,
                draft.text,
                draft.channel.value,
                draft.rationale,
                draft.stage_after.value if draft.stage_after else None,
                now,
            ),
        )
        draft.id = cursor.lastrowid
    draft.created_at = _parse_dt(now)
    return draft


def get_draft(draft_id: int) -> Optional[Draft]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM lead_drafts WHERE id = ?", (draft_id,)).fetchone()
    return _row_to_draft(row) if row else None


def pending_drafts() -> list[Draft]:
    """Wszystko, co czeka na zgodę brokera — to jest treść skrzynki."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM lead_drafts WHERE approved_at IS NULL AND rejected_at IS NULL"
            " ORDER BY created_at ASC"
        ).fetchall()
    return [_row_to_draft(r) for r in rows]


def reject_draft(draft_id: int, *, reason: str = "") -> bool:
    """Broker odrzucił propozycję. Draft zostaje — to materiał na poprawę agenta."""
    init_db()
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE lead_drafts SET rejected_at = ?, rationale = rationale || ?"
            " WHERE id = ? AND approved_at IS NULL AND rejected_at IS NULL",
            (_now_iso(), f"\n[odrzucone] {reason}" if reason else "\n[odrzucone]", draft_id),
        )
        return cursor.rowcount > 0


def approve_and_send(draft_id: int, *, edited_text: Optional[str] = None) -> Optional[Message]:
    """Zgoda brokera zamienia draft w wysłaną wiadomość.

    "Wysłana" znaczy tu: zapisana w wątku jako wiadomość od brokera i gotowa do
    skopiowania albo otwarcia w WhatsAppie. Ten moduł nie ma żadnego kanału wyjścia
    i mieć nie będzie — treść idzie do klienta z telefonu brokera, pod jego nazwiskiem.

    Zwraca None, gdy draft już zatwierdzono albo odrzucono. Dwa kliknięcia w panelu
    nie mogą wysłać tej samej wiadomości dwa razy.
    """
    init_db()
    now = _now_iso()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM lead_drafts WHERE id = ? AND approved_at IS NULL AND rejected_at IS NULL",
            (draft_id,),
        ).fetchone()
        if row is None:
            return None

        text = edited_text if edited_text is not None else row["text"]
        conn.execute(
            "UPDATE lead_drafts SET approved_at = ?, sent_at = ?, edited_text = ? WHERE id = ?",
            (now, now, edited_text, draft_id),
        )
        cursor = conn.execute(
            "INSERT INTO lead_messages (lead_id, author, text, channel, meta_json, created_at, sent_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["lead_id"],
                Author.BROKER.value,
                text,
                row["channel"],
                json.dumps({"from_draft": draft_id}, ensure_ascii=False),
                now,
                now,
            ),
        )
        if row["stage_after"]:
            conn.execute(
                "UPDATE leads SET stage = ?, updated_at = ? WHERE id = ?",
                (row["stage_after"], now, row["lead_id"]),
            )
        else:
            conn.execute("UPDATE leads SET updated_at = ? WHERE id = ?", (now, row["lead_id"]))

        return Message(
            id=cursor.lastrowid,
            author=Author.BROKER,
            text=text,
            channel=Channel(row["channel"]),
            meta={"from_draft": draft_id},
            created_at=_parse_dt(now),
            sent_at=_parse_dt(now),
        )


# ────────────────────────────────────────────────── wyszukiwania z leada


def start_lead_search(lead_id: int, criteria: dict) -> int:
    """Otwiera wyszukiwanie dla leada. Zwraca jego id.

    Wiersz powstaje ZANIM scrape ruszy, ze statusem 'running'. Dzięki temu broker
    widzi w panelu, że coś się dzieje, zamiast patrzeć na pustą listę przez kilka
    minut i uruchamiać wyszukiwanie drugi raz.
    """
    init_db()
    now = _now_iso()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO lead_searches (lead_id, status, criteria_json, created_at)"
            " VALUES (?, 'running', ?, ?)",
            (lead_id, json.dumps(criteria, ensure_ascii=False), now),
        )
        conn.execute("UPDATE leads SET updated_at = ? WHERE id = ?", (now, lead_id))
        return int(cursor.lastrowid)


def finish_lead_search(search_id: int, *, job_id: Optional[str], candidates: list) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            "UPDATE lead_searches SET status = 'done', job_id = ?, candidates_json = ?,"
            " finished_at = ? WHERE id = ?",
            (job_id, json.dumps(candidates, ensure_ascii=False, default=str), _now_iso(), search_id),
        )


def fail_lead_search(search_id: int, error: str) -> None:
    """Zapisuje błąd zamiast go gubić.

    Wyszukiwanie leci w tle, więc wyjątek nie ma komu wypłynąć. Bez tego wiersza
    lead zostawałby na zawsze w stanie 'running' i wyglądał jak trwające zadanie.
    """
    init_db()
    with _connect() as conn:
        conn.execute(
            "UPDATE lead_searches SET status = 'error', error = ?, finished_at = ? WHERE id = ?",
            (error[:500], _now_iso(), search_id),
        )


def _row_to_search(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "lead_id": row["lead_id"],
        "job_id": row["job_id"],
        "status": row["status"],
        "criteria": json.loads(row["criteria_json"] or "{}"),
        "candidates": json.loads(row["candidates_json"] or "[]"),
        "error": row["error"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


def latest_lead_search(lead_id: int) -> Optional[dict[str, Any]]:
    """Ostatnie wyszukiwanie dla leada — to, które broker właśnie ogląda."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM lead_searches WHERE lead_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (lead_id,),
        ).fetchone()
    return _row_to_search(row) if row else None


def lead_searches(lead_id: int, *, limit: int = 10) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM lead_searches WHERE lead_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (lead_id, limit),
        ).fetchall()
    return [_row_to_search(r) for r in rows]


def running_search(lead_id: int) -> bool:
    """Czy dla tego leada już coś leci — żeby nie puszczać drugiego scrape'u."""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM lead_searches WHERE lead_id = ? AND status = 'running' LIMIT 1",
            (lead_id,),
        ).fetchone()
    return row is not None
