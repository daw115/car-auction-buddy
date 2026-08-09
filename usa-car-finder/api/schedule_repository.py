"""Native scheduled-search repository operations (v1).

CRUD, toggle, detail, ordered-list and active counts for rows with
schedule_kind='scheduled_recurring_v1'. Operates exclusively on
watch_queue.db via a caller-supplied sqlite3.Connection.

Legacy rows (schedule_kind IS NULL) are never touched, selected or counted
by functions in this module. Cross-kind isolation is enforced at the SQL
level in every query.

Design contract (task 3.1):
- create_schedule: INSERT with BEGIN IMMEDIATE, owner count check, limit guard.
- update_schedule: strict atomic patch, optimistic version, interval change resets next_run_at.
- set_schedule_enabled: same-state no-op, disabled->enabled checks limit.
- delete_schedule: soft delete, idempotent.
- get_schedule: detail; 404 for missing/deleted.
- list_schedules: all native non-deleted; ASC next_run_at (NULL last), id tie-break.
- count_active_for_owner: count enabled native non-deleted for owner.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from api.scheduled_search_config import DEFAULT_MAX_ACTIVE_SCHEDULES
from api.watch_queue_db import SCHEDULE_KIND
from api.scheduled_search_models import (
    NotificationSettings,
    ScheduledSearch,
    ScheduledSearchCriteria,
    ScheduledSearchEnvelope,
    ScheduleLimits,
)

# Re-export for external callers referencing the kind constant.
NATIVE_SCHEDULE_KIND = SCHEDULE_KIND  # "scheduled_recurring_v1"


class ScheduleNotFoundError(Exception):
    """Raised when schedule_id does not exist or is deleted."""
    pass


class VersionConflictError(Exception):
    """Raised on expected_version mismatch (optimistic locking)."""
    pass


class ActiveLimitExceededError(Exception):
    """Raised when creating/enabling would exceed owner active limit."""

    def __init__(self, active_count: int, limit: int) -> None:
        super().__init__(
            f"Limit aktywnych zaplanowanych wyszukiwan przekroczony: "
            f"{active_count}/{limit}"
        )
        self.active_count = active_count
        self.limit = limit


class EmptyPatchError(Exception):
    """Raised when update_schedule receives no mutable fields."""
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_iso(dt: datetime) -> str:
    """Format aware UTC datetime as ISO 8601 with +00:00."""
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _row_to_scheduled_search(row: sqlite3.Row) -> ScheduledSearch:
    """Map a watch_entries row (native schedule) to the public model."""
    criteria_raw = json.loads(row["request_json"])
    criteria = ScheduledSearchCriteria.model_validate(criteria_raw)

    notifications = NotificationSettings(
        telegram_global=bool(row["notifications_enabled"])
    )

    last_error = None
    if row["last_error_code"]:
        from api.scheduled_search_models import ScheduledSearchErrorInfo
        last_error = ScheduledSearchErrorInfo(
            code=row["last_error_code"],
            message=row["last_error_message"] or "",
        )

    return ScheduledSearch(
        id=row["id"],
        label=row["label"] or "",
        criteria=criteria,
        interval_hours=row["interval_hours"],
        status="enabled" if row["active"] else "disabled",
        owner_site_user=row["owner_site_user"] or "",
        notifications=notifications,
        next_run_at=row["next_run_at"] or "",
        last_run_at=row["last_run_at"],
        runs_count=row["runs_count"],
        last_result_count=row["last_result_count"],
        last_execution_status=row["last_execution_status"] or "never",
        last_error=last_error,
        in_flight_execution_id=row["in_flight_execution_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"] or row["created_at"],
        version=row["version"],
    )


# ---------------------------------------------------------------------------
# Repository operations
# ---------------------------------------------------------------------------


def create_schedule(
    conn: sqlite3.Connection,
    *,
    criteria: ScheduledSearchCriteria,
    interval_hours: int,
    owner: str,
    label: Optional[str] = None,
    notifications: Optional[NotificationSettings] = None,
    now: Optional[datetime] = None,
    max_active: int = DEFAULT_MAX_ACTIVE_SCHEDULES,
) -> ScheduledSearchEnvelope:
    """Insert a new native schedule within a single BEGIN IMMEDIATE transaction.

    Counts the owner's enabled schedules and checks against max_active before
    inserting. Raises ActiveLimitExceededError if the limit would be exceeded.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if notifications is None:
        notifications = NotificationSettings(telegram_global=False)

    created_at = _utc_iso(now)
    next_run_at = _utc_iso(now + timedelta(hours=interval_hours))
    criteria_json = criteria.model_dump_json()
    effective_label = label or ""

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Count active native schedules for this owner
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM watch_entries "
            "WHERE schedule_kind = ? AND owner_site_user = ? "
            "AND active = 1 AND deleted_at IS NULL",
            (NATIVE_SCHEDULE_KIND, owner),
        ).fetchone()
        active_count = row["n"] if row else 0

        if active_count >= max_active:
            conn.execute("ROLLBACK")
            raise ActiveLimitExceededError(active_count, max_active)

        cur = conn.execute(
            """INSERT INTO watch_entries
               (label, request_json, interval_hours, chat_id,
                created_at, next_run_at, runs_count, last_result_count,
                active, status, recurring, preferred_hour,
                schedule_kind, owner_site_user, notifications_enabled,
                deleted_at, updated_at, updated_by_site_user, version,
                last_execution_status, last_error_code, last_error_message,
                in_flight_execution_id)
               VALUES (?, ?, ?, NULL,
                       ?, ?, 0, NULL,
                       1, ?, 0, NULL,
                       ?, ?, ?,
                       NULL, ?, ?, 1,
                       NULL, NULL, NULL,
                       NULL)""",
            (
                effective_label,
                criteria_json,
                interval_hours,
                created_at,
                next_run_at,
                "active",
                NATIVE_SCHEDULE_KIND,
                owner,
                1 if notifications.telegram_global else 0,
                created_at,
                owner,
            ),
        )
        schedule_id = cur.lastrowid
        conn.execute("COMMIT")
    except ActiveLimitExceededError:
        raise
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise

    # Read-after-write
    return get_schedule(conn, schedule_id=schedule_id, max_active=max_active)


def update_schedule(
    conn: sqlite3.Connection,
    *,
    schedule_id: int,
    patch: dict[str, Any],
    expected_version: int,
    actor: str,
    now: Optional[datetime] = None,
    max_active: int = DEFAULT_MAX_ACTIVE_SCHEDULES,
) -> ScheduledSearchEnvelope:
    """Strict atomic patch with optimistic version.

    patch may contain: label, criteria, interval_hours, notifications.
    - interval_hours change resets next_run_at = now + new_interval.
    - Other fields do not change next_run_at.
    - Empty patch raises EmptyPatchError.
    - Missing/deleted schedule raises ScheduleNotFoundError.
    - Version mismatch raises VersionConflictError.
    """
    if not patch:
        raise EmptyPatchError()

    if now is None:
        now = datetime.now(timezone.utc)

    # Read current row
    row = conn.execute(
        "SELECT * FROM watch_entries WHERE id = ? AND schedule_kind = ? AND deleted_at IS NULL",
        (schedule_id, NATIVE_SCHEDULE_KIND),
    ).fetchone()

    if row is None:
        raise ScheduleNotFoundError()

    if row["version"] != expected_version:
        raise VersionConflictError()

    # Build SET clause
    sets: list[str] = []
    params: list[Any] = []

    if "label" in patch:
        sets.append("label = ?")
        params.append(patch["label"] or "")

    if "criteria" in patch:
        criteria_obj = patch["criteria"]
        if isinstance(criteria_obj, ScheduledSearchCriteria):
            sets.append("request_json = ?")
            params.append(criteria_obj.model_dump_json())
        else:
            c = ScheduledSearchCriteria.model_validate(criteria_obj)
            sets.append("request_json = ?")
            params.append(c.model_dump_json())

    if "interval_hours" in patch:
        new_interval = patch["interval_hours"]
        sets.append("interval_hours = ?")
        params.append(new_interval)
        # Interval change resets next_run_at from edit time
        new_next_run = _utc_iso(now + timedelta(hours=new_interval))
        sets.append("next_run_at = ?")
        params.append(new_next_run)

    if "notifications" in patch:
        notif_obj = patch["notifications"]
        if isinstance(notif_obj, NotificationSettings):
            sets.append("notifications_enabled = ?")
            params.append(1 if notif_obj.telegram_global else 0)
        else:
            n = NotificationSettings.model_validate(notif_obj)
            sets.append("notifications_enabled = ?")
            params.append(1 if n.telegram_global else 0)

    # Always bump version and updated_at/by
    sets.append("version = version + 1")
    sets.append("updated_at = ?")
    params.append(_utc_iso(now))
    sets.append("updated_by_site_user = ?")
    params.append(actor)

    # WHERE clause
    params.append(schedule_id)
    params.append(expected_version)
    params.append(NATIVE_SCHEDULE_KIND)

    set_clause = ", ".join(sets)
    sql = (
        "UPDATE watch_entries SET " + set_clause + " "
        f"WHERE id = ? AND version = ? AND schedule_kind = ? AND deleted_at IS NULL"
    )
    cur = conn.execute(sql, params)
    if cur.rowcount == 0:
        # Re-check: could be version conflict or deleted after our read
        raise VersionConflictError()

    conn.commit()

    # Read-after-write returns updated row
    return get_schedule(conn, schedule_id=schedule_id, max_active=max_active)


def set_schedule_enabled(
    conn: sqlite3.Connection,
    *,
    schedule_id: int,
    enabled: bool,
    expected_version: int,
    actor: str,
    now: Optional[datetime] = None,
    max_active: int = DEFAULT_MAX_ACTIVE_SCHEDULES,
) -> ScheduledSearchEnvelope:
    """Toggle schedule enabled/disabled state.

    Same-state = full no-op (no version/timestamp/next_run change).
    disabled->enabled: count check, set next_run=now+interval.
    enabled->disabled: preserve criteria/interval/next_run.
    Executed in a single BEGIN IMMEDIATE for create/enable path.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    row = conn.execute(
        "SELECT * FROM watch_entries WHERE id = ? AND schedule_kind = ? AND deleted_at IS NULL",
        (schedule_id, NATIVE_SCHEDULE_KIND),
    ).fetchone()

    if row is None:
        raise ScheduleNotFoundError()

    if row["version"] != expected_version:
        raise VersionConflictError()

    current_active = bool(row["active"])

    # Same-state: full no-op
    if current_active == enabled:
        return _build_envelope(row, max_active=max_active, conn=conn)

    if enabled:
        # disabled -> enabled: need limit check in BEGIN IMMEDIATE
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Re-read under exclusive lock
            row2 = conn.execute(
                "SELECT * FROM watch_entries WHERE id = ? AND schedule_kind = ? AND deleted_at IS NULL",
                (schedule_id, NATIVE_SCHEDULE_KIND),
            ).fetchone()

            if row2 is None:
                conn.execute("ROLLBACK")
                raise ScheduleNotFoundError()

            if row2["version"] != expected_version:
                conn.execute("ROLLBACK")
                raise VersionConflictError()

            owner = row2["owner_site_user"]
            count_row = conn.execute(
                "SELECT COUNT(*) AS n FROM watch_entries "
                "WHERE schedule_kind = ? AND owner_site_user = ? "
                "AND active = 1 AND deleted_at IS NULL",
                (NATIVE_SCHEDULE_KIND, owner),
            ).fetchone()
            active_count = count_row["n"] if count_row else 0

            if active_count >= max_active:
                conn.execute("ROLLBACK")
                raise ActiveLimitExceededError(active_count, max_active)

            interval = row2["interval_hours"]
            new_next_run = _utc_iso(now + timedelta(hours=interval))
            updated_at = _utc_iso(now)

            conn.execute(
                """UPDATE watch_entries
                   SET active = 1, status = ?, next_run_at = ?,
                       version = version + 1, updated_at = ?,
                       updated_by_site_user = ?
                   WHERE id = ? AND version = ? AND schedule_kind = ?
                   AND deleted_at IS NULL""",
                ("active", new_next_run, updated_at, actor,
                 schedule_id, expected_version, NATIVE_SCHEDULE_KIND),
            )
            conn.execute("COMMIT")
        except (ActiveLimitExceededError, ScheduleNotFoundError, VersionConflictError):
            raise
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
    else:
        # enabled -> disabled: preserve criteria/interval/next_run
        updated_at = _utc_iso(now)
        conn.execute(
            """UPDATE watch_entries
               SET active = 0, status = ?,
                   version = version + 1, updated_at = ?,
                   updated_by_site_user = ?
               WHERE id = ? AND version = ? AND schedule_kind = ?
               AND deleted_at IS NULL""",
            ("disabled", updated_at, actor,
             schedule_id, expected_version, NATIVE_SCHEDULE_KIND),
        )
        conn.commit()

    return get_schedule(conn, schedule_id=schedule_id, max_active=max_active)


def delete_schedule(
    conn: sqlite3.Connection,
    *,
    schedule_id: int,
    actor: str,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Soft delete: set deleted_at, active=0, next_run_at=NULL.

    Idempotent: missing or already-deleted returns success.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    deleted_at = _utc_iso(now)

    cur = conn.execute(
        """UPDATE watch_entries
           SET deleted_at = ?, active = 0,
               updated_at = ?, updated_by_site_user = ?,
               version = version + 1
           WHERE id = ? AND schedule_kind = ? AND deleted_at IS NULL""",
        (deleted_at, deleted_at, actor, schedule_id, NATIVE_SCHEDULE_KIND),
    )
    conn.commit()

    # Idempotent: missing/already-deleted -> success
    return {"deleted": True, "id": schedule_id}


def get_schedule(
    conn: sqlite3.Connection,
    schedule_id: int,
    *,
    max_active: int = DEFAULT_MAX_ACTIVE_SCHEDULES,
) -> ScheduledSearchEnvelope:
    """Get schedule detail. Raises ScheduleNotFoundError for missing/deleted."""
    row = conn.execute(
        "SELECT * FROM watch_entries WHERE id = ? AND schedule_kind = ? AND deleted_at IS NULL",
        (schedule_id, NATIVE_SCHEDULE_KIND),
    ).fetchone()

    if row is None:
        raise ScheduleNotFoundError()

    return _build_envelope(row, max_active=max_active, conn=conn)


def list_schedules(
    conn: sqlite3.Connection,
    *,
    max_active: int = DEFAULT_MAX_ACTIVE_SCHEDULES,
) -> dict[str, Any]:
    """All native non-deleted schedules, sorted ASC next_run_at (NULL last), id tie-break."""
    rows = conn.execute(
        """SELECT * FROM watch_entries
           WHERE schedule_kind = ? AND deleted_at IS NULL
           ORDER BY
             CASE WHEN next_run_at IS NULL THEN 1 ELSE 0 END ASC,
             next_run_at ASC,
             id ASC""",
        (NATIVE_SCHEDULE_KIND,),
    ).fetchall()

    schedules = [_row_to_scheduled_search(r) for r in rows]

    # Build per-owner limits
    limits_by_owner: dict[str, dict[str, int]] = {}
    for s in schedules:
        owner = s.owner_site_user
        if owner not in limits_by_owner:
            count = count_active_for_owner(conn, owner)
            limits_by_owner[owner] = {
                "active_count": count,
                "max_active": max_active,
            }

    return {
        "schedules": schedules,
        "count": len(schedules),
        "limits_by_owner": limits_by_owner,
    }


def count_active_for_owner(conn: sqlite3.Connection, owner: str) -> int:
    """Count enabled native non-deleted schedules for an owner."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM watch_entries "
        "WHERE schedule_kind = ? AND owner_site_user = ? "
        "AND active = 1 AND deleted_at IS NULL",
        (NATIVE_SCHEDULE_KIND, owner),
    ).fetchone()
    return row["n"] if row else 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_envelope(
    row: sqlite3.Row,
    *,
    max_active: int,
    conn: sqlite3.Connection,
) -> ScheduledSearchEnvelope:
    """Build an envelope from a DB row with current limits."""
    schedule = _row_to_scheduled_search(row)
    owner = schedule.owner_site_user
    active_count = count_active_for_owner(conn, owner)
    return ScheduledSearchEnvelope(
        schedule=schedule,
        limits=ScheduleLimits(active_count=active_count, max_active=max_active),
    )


__all__ = [
    "NATIVE_SCHEDULE_KIND",
    "ScheduleNotFoundError",
    "VersionConflictError",
    "ActiveLimitExceededError",
    "EmptyPatchError",
    "create_schedule",
    "update_schedule",
    "set_schedule_enabled",
    "delete_schedule",
    "get_schedule",
    "list_schedules",
    "count_active_for_owner",
]
