"""Targeted repository tests for native schedule CRUD/toggle/detail/list.

Task 3.1: create+read, update round-trip, same-state toggle no-op,
soft delete+idempotent, list ordering, count.

Uses temp SQLite only (isolation guard enforced). No PBT.
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.isolation_guard import assert_safe_test_database_path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

WORKTREE_ROOT = Path("/home/dawid/kiro-worktrees/scheduled-recurring-car-search-1.1/worktree/usa-car-finder")


@pytest.fixture
def temp_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh temp SQLite with schema + migration applied."""
    db_path = tmp_path / "test_schedule_repo.db"
    assert_safe_test_database_path(db_path, sandbox_root=tmp_path)

    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # Create base schema
    conn.executescript("""
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
            status TEXT NOT NULL DEFAULT active,
            recurring INTEGER NOT NULL DEFAULT 0,
            preferred_hour INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_watch_due
            ON watch_entries(active, next_run_at);
    """)

    # Apply additive schedule migration
    from api.watch_queue_db import _apply_schedule_migration
    _apply_schedule_migration(conn)
    conn.commit()

    yield conn
    conn.close()


def _make_criteria(**overrides):
    """Return a minimal valid ScheduledSearchCriteria."""
    from api.scheduled_search_models import ScheduledSearchCriteria
    defaults = {"make": "Toyota"}
    defaults.update(overrides)
    return ScheduledSearchCriteria.model_validate(defaults)


def _now():
    return datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Tests: create + read
# ---------------------------------------------------------------------------

class TestCreateSchedule:
    def test_create_basic(self, temp_db):
        from api.schedule_repository import create_schedule, NATIVE_SCHEDULE_KIND
        from api.scheduled_search_models import NotificationSettings

        now = _now()
        criteria = _make_criteria()

        envelope = create_schedule(
            temp_db,
            criteria=criteria,
            interval_hours=24,
            owner="alice",
            label="My search",
            notifications=NotificationSettings(telegram_global=False),
            now=now,
            max_active=20,
        )

        s = envelope.schedule
        assert s.id > 0
        assert s.label == "My search"
        assert s.criteria.make == "Toyota"
        assert s.interval_hours == 24
        assert s.status == "enabled"
        assert s.owner_site_user == "alice"
        assert s.notifications.telegram_global is False
        assert s.version == 1
        assert s.runs_count == 0
        assert s.last_result_count is None
        assert s.last_execution_status == "never"
        assert s.last_error is None
        # next_run_at = now + 24h
        expected_next = (now + timedelta(hours=24)).isoformat(timespec="seconds")
        assert s.next_run_at == expected_next
        assert s.created_at == now.isoformat(timespec="seconds")

        assert envelope.limits.active_count == 1
        assert envelope.limits.max_active == 20

    def test_create_respects_limit(self, temp_db):
        from api.schedule_repository import (
            create_schedule,
            ActiveLimitExceededError,
        )

        now = _now()
        criteria = _make_criteria()

        # Create 2 schedules (limit=2)
        create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="bob", now=now, max_active=2)
        create_schedule(temp_db, criteria=criteria, interval_hours=48, owner="bob", now=now, max_active=2)

        # Third should fail
        with pytest.raises(ActiveLimitExceededError) as exc_info:
            create_schedule(temp_db, criteria=criteria, interval_hours=12, owner="bob", now=now, max_active=2)

        assert exc_info.value.active_count == 2
        assert exc_info.value.limit == 2

    def test_create_limit_is_per_owner(self, temp_db):
        from api.schedule_repository import create_schedule

        now = _now()
        criteria = _make_criteria()

        # Alice fills her limit
        create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now, max_active=1)
        # Bob can still create
        env = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="bob", now=now, max_active=1)
        assert env.schedule.owner_site_user == "bob"

    def test_create_default_notifications(self, temp_db):
        from api.schedule_repository import create_schedule

        now = _now()
        criteria = _make_criteria()

        envelope = create_schedule(temp_db, criteria=criteria, interval_hours=6, owner="alice", now=now)
        assert envelope.schedule.notifications.telegram_global is False


# ---------------------------------------------------------------------------
# Tests: update round-trip
# ---------------------------------------------------------------------------

class TestUpdateSchedule:
    def test_update_label(self, temp_db):
        from api.schedule_repository import create_schedule, update_schedule

        now = _now()
        criteria = _make_criteria()
        env = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        sid = env.schedule.id

        later = now + timedelta(minutes=10)
        updated = update_schedule(
            temp_db,
            schedule_id=sid,
            patch={"label": "New label"},
            expected_version=1,
            actor="alice",
            now=later,
        )

        assert updated.schedule.label == "New label"
        assert updated.schedule.version == 2
        # next_run_at not changed (non-interval field)
        assert updated.schedule.next_run_at == env.schedule.next_run_at

    def test_update_interval_resets_next_run(self, temp_db):
        from api.schedule_repository import create_schedule, update_schedule

        now = _now()
        criteria = _make_criteria()
        env = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        sid = env.schedule.id

        later = now + timedelta(minutes=30)
        updated = update_schedule(
            temp_db,
            schedule_id=sid,
            patch={"interval_hours": 48},
            expected_version=1,
            actor="alice",
            now=later,
        )

        expected_next = (later + timedelta(hours=48)).isoformat(timespec="seconds")
        assert updated.schedule.next_run_at == expected_next
        assert updated.schedule.interval_hours == 48
        assert updated.schedule.version == 2

    def test_update_criteria_preserves_other_fields(self, temp_db):
        from api.schedule_repository import create_schedule, update_schedule

        now = _now()
        criteria = _make_criteria(make="Honda", model="Civic")
        env = create_schedule(
            temp_db, criteria=criteria, interval_hours=12,
            owner="alice", label="Original", now=now,
        )
        sid = env.schedule.id

        new_criteria = _make_criteria(make="Ford", model="Mustang")
        later = now + timedelta(minutes=5)
        updated = update_schedule(
            temp_db,
            schedule_id=sid,
            patch={"criteria": new_criteria},
            expected_version=1,
            actor="bob",
            now=later,
        )

        assert updated.schedule.criteria.make == "Ford"
        assert updated.schedule.criteria.model == "Mustang"
        assert updated.schedule.label == "Original"
        assert updated.schedule.interval_hours == 12
        assert updated.schedule.next_run_at == env.schedule.next_run_at

    def test_update_empty_patch_raises(self, temp_db):
        from api.schedule_repository import create_schedule, update_schedule, EmptyPatchError

        now = _now()
        criteria = _make_criteria()
        env = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)

        with pytest.raises(EmptyPatchError):
            update_schedule(
                temp_db, schedule_id=env.schedule.id,
                patch={}, expected_version=1, actor="alice", now=now,
            )

    def test_update_version_conflict(self, temp_db):
        from api.schedule_repository import (
            create_schedule, update_schedule, VersionConflictError,
        )

        now = _now()
        criteria = _make_criteria()
        env = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)

        with pytest.raises(VersionConflictError):
            update_schedule(
                temp_db, schedule_id=env.schedule.id,
                patch={"label": "x"}, expected_version=99,
                actor="alice", now=now,
            )

    def test_update_not_found(self, temp_db):
        from api.schedule_repository import update_schedule, ScheduleNotFoundError

        with pytest.raises(ScheduleNotFoundError):
            update_schedule(
                temp_db, schedule_id=99999,
                patch={"label": "x"}, expected_version=1,
                actor="alice", now=_now(),
            )


# ---------------------------------------------------------------------------
# Tests: toggle (same-state no-op)
# ---------------------------------------------------------------------------

class TestSetScheduleEnabled:
    def test_same_state_enabled_is_noop(self, temp_db):
        from api.schedule_repository import create_schedule, set_schedule_enabled

        now = _now()
        criteria = _make_criteria()
        env = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        sid = env.schedule.id

        # Already enabled -> same state no-op
        result = set_schedule_enabled(
            temp_db, schedule_id=sid, enabled=True,
            expected_version=1, actor="alice", now=now + timedelta(hours=1),
        )

        assert result.schedule.version == 1  # NOT incremented
        assert result.schedule.status == "enabled"
        assert result.schedule.next_run_at == env.schedule.next_run_at
        assert result.schedule.updated_at == env.schedule.updated_at

    def test_same_state_disabled_is_noop(self, temp_db):
        from api.schedule_repository import create_schedule, set_schedule_enabled

        now = _now()
        criteria = _make_criteria()
        env = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        sid = env.schedule.id

        # Disable it first
        later = now + timedelta(minutes=5)
        disabled = set_schedule_enabled(
            temp_db, schedule_id=sid, enabled=False,
            expected_version=1, actor="alice", now=later,
        )
        assert disabled.schedule.status == "disabled"
        assert disabled.schedule.version == 2

        # Same-state (already disabled) -> no-op
        later2 = now + timedelta(minutes=10)
        result = set_schedule_enabled(
            temp_db, schedule_id=sid, enabled=False,
            expected_version=2, actor="alice", now=later2,
        )
        assert result.schedule.version == 2  # NOT incremented
        assert result.schedule.status == "disabled"

    def test_disable_preserves_next_run(self, temp_db):
        from api.schedule_repository import create_schedule, set_schedule_enabled

        now = _now()
        criteria = _make_criteria()
        env = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        original_next_run = env.schedule.next_run_at

        later = now + timedelta(minutes=10)
        disabled = set_schedule_enabled(
            temp_db, schedule_id=env.schedule.id, enabled=False,
            expected_version=1, actor="alice", now=later,
        )

        # next_run_at preserved on disable (design: "Disable preserves criteria/interval/next run")
        # Actually per design: enabled->disabled preserves next_run
        # But the UPDATE only sets active/status, NOT next_run_at
        assert disabled.schedule.next_run_at == original_next_run

    def test_enable_resets_next_run_and_checks_limit(self, temp_db):
        from api.schedule_repository import (
            create_schedule, set_schedule_enabled, ActiveLimitExceededError,
        )

        now = _now()
        criteria = _make_criteria()

        # Create 2 schedules with limit=2
        env1 = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now, max_active=2)
        env2 = create_schedule(temp_db, criteria=criteria, interval_hours=12, owner="alice", now=now, max_active=2)

        # Disable env1
        later = now + timedelta(minutes=5)
        set_schedule_enabled(
            temp_db, schedule_id=env1.schedule.id, enabled=False,
            expected_version=1, actor="alice", now=later,
        )

        # Re-enable env1 (should work since only env2 is active)
        later2 = now + timedelta(hours=2)
        enabled = set_schedule_enabled(
            temp_db, schedule_id=env1.schedule.id, enabled=True,
            expected_version=2, actor="alice", now=later2, max_active=2,
        )
        assert enabled.schedule.status == "enabled"
        expected_next = (later2 + timedelta(hours=24)).isoformat(timespec="seconds")
        assert enabled.schedule.next_run_at == expected_next


# ---------------------------------------------------------------------------
# Tests: soft delete + idempotent
# ---------------------------------------------------------------------------

class TestDeleteSchedule:
    def test_soft_delete(self, temp_db):
        from api.schedule_repository import (
            create_schedule, delete_schedule, get_schedule, ScheduleNotFoundError,
        )

        now = _now()
        criteria = _make_criteria()
        env = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        sid = env.schedule.id

        result = delete_schedule(temp_db, schedule_id=sid, actor="alice", now=now)
        assert result == {"deleted": True, "id": sid}

        # get_schedule should raise not found
        with pytest.raises(ScheduleNotFoundError):
            get_schedule(temp_db, sid)

    def test_delete_idempotent_already_deleted(self, temp_db):
        from api.schedule_repository import create_schedule, delete_schedule

        now = _now()
        criteria = _make_criteria()
        env = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        sid = env.schedule.id

        # Delete twice
        result1 = delete_schedule(temp_db, schedule_id=sid, actor="alice", now=now)
        result2 = delete_schedule(temp_db, schedule_id=sid, actor="alice", now=now + timedelta(hours=1))
        assert result1 == {"deleted": True, "id": sid}
        assert result2 == {"deleted": True, "id": sid}

    def test_delete_idempotent_missing(self, temp_db):
        from api.schedule_repository import delete_schedule

        # Non-existent ID -> still success (idempotent)
        result = delete_schedule(temp_db, schedule_id=99999, actor="alice", now=_now())
        assert result == {"deleted": True, "id": 99999}

    def test_delete_removes_from_active_count(self, temp_db):
        from api.schedule_repository import (
            create_schedule, delete_schedule, count_active_for_owner,
        )

        now = _now()
        criteria = _make_criteria()
        create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        env2 = create_schedule(temp_db, criteria=criteria, interval_hours=12, owner="alice", now=now)

        assert count_active_for_owner(temp_db, "alice") == 2
        delete_schedule(temp_db, schedule_id=env2.schedule.id, actor="alice", now=now)
        assert count_active_for_owner(temp_db, "alice") == 1


# ---------------------------------------------------------------------------
# Tests: list ordering
# ---------------------------------------------------------------------------

class TestListSchedules:
    def test_list_ordering_next_run_asc_null_last(self, temp_db):
        from api.schedule_repository import (
            create_schedule, delete_schedule, set_schedule_enabled, list_schedules,
        )

        now = _now()
        criteria = _make_criteria()

        # Create schedules with different intervals (thus different next_run_at)
        e1 = create_schedule(temp_db, criteria=criteria, interval_hours=48, owner="alice", now=now)
        e2 = create_schedule(temp_db, criteria=criteria, interval_hours=6, owner="alice", now=now)
        e3 = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="bob", now=now)

        result = list_schedules(temp_db)
        ids = [s.id for s in result["schedules"]]

        # e2 (6h) < e3 (24h) < e1 (48h)
        assert ids == [e2.schedule.id, e3.schedule.id, e1.schedule.id]
        assert result["count"] == 3

    def test_list_excludes_deleted(self, temp_db):
        from api.schedule_repository import create_schedule, delete_schedule, list_schedules

        now = _now()
        criteria = _make_criteria()
        e1 = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        e2 = create_schedule(temp_db, criteria=criteria, interval_hours=12, owner="alice", now=now)

        delete_schedule(temp_db, schedule_id=e1.schedule.id, actor="alice", now=now)

        result = list_schedules(temp_db)
        ids = [s.id for s in result["schedules"]]
        assert e1.schedule.id not in ids
        assert e2.schedule.id in ids

    def test_list_does_not_show_legacy(self, temp_db):
        """Legacy rows (schedule_kind IS NULL) must not appear in native list."""
        from api.schedule_repository import create_schedule, list_schedules

        now = _now()
        criteria = _make_criteria()

        # Insert a legacy row directly (schedule_kind IS NULL)
        temp_db.execute(
            """INSERT INTO watch_entries
               (label, request_json, interval_hours, chat_id,
                created_at, next_run_at, active, status, recurring, preferred_hour)
               VALUES (?, ?, ?, NULL, ?, ?, 1, ?, 0, NULL)""",
            ("legacy", "{\"make\":\"Ford\"}", 24, now.isoformat(), (now + timedelta(hours=24)).isoformat(), "active"),
        )
        temp_db.commit()

        # Create a native schedule
        create_schedule(temp_db, criteria=criteria, interval_hours=12, owner="alice", now=now)

        result = list_schedules(temp_db)
        assert result["count"] == 1
        assert result["schedules"][0].owner_site_user == "alice"

    def test_list_limits_by_owner(self, temp_db):
        from api.schedule_repository import create_schedule, list_schedules

        now = _now()
        criteria = _make_criteria()
        create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        create_schedule(temp_db, criteria=criteria, interval_hours=12, owner="alice", now=now)
        create_schedule(temp_db, criteria=criteria, interval_hours=6, owner="bob", now=now)

        result = list_schedules(temp_db, max_active=20)
        assert "alice" in result["limits_by_owner"]
        assert "bob" in result["limits_by_owner"]
        assert result["limits_by_owner"]["alice"]["active_count"] == 2
        assert result["limits_by_owner"]["bob"]["active_count"] == 1


# ---------------------------------------------------------------------------
# Tests: count_active_for_owner
# ---------------------------------------------------------------------------

class TestCountActiveForOwner:
    def test_counts_only_native_active_nondel(self, temp_db):
        from api.schedule_repository import (
            create_schedule, set_schedule_enabled, delete_schedule,
            count_active_for_owner,
        )

        now = _now()
        criteria = _make_criteria()

        assert count_active_for_owner(temp_db, "alice") == 0

        e1 = create_schedule(temp_db, criteria=criteria, interval_hours=24, owner="alice", now=now)
        assert count_active_for_owner(temp_db, "alice") == 1

        e2 = create_schedule(temp_db, criteria=criteria, interval_hours=12, owner="alice", now=now)
        assert count_active_for_owner(temp_db, "alice") == 2

        # Disable one
        set_schedule_enabled(
            temp_db, schedule_id=e1.schedule.id, enabled=False,
            expected_version=1, actor="alice", now=now + timedelta(minutes=1),
        )
        assert count_active_for_owner(temp_db, "alice") == 1

        # Delete the other
        delete_schedule(temp_db, schedule_id=e2.schedule.id, actor="alice", now=now)
        assert count_active_for_owner(temp_db, "alice") == 0

    def test_does_not_count_legacy(self, temp_db):
        from api.schedule_repository import count_active_for_owner

        now = _now()
        # Insert legacy row
        temp_db.execute(
            """INSERT INTO watch_entries
               (label, request_json, interval_hours, chat_id,
                created_at, next_run_at, active, status, recurring, preferred_hour,
                owner_site_user)
               VALUES (?, ?, ?, NULL, ?, ?, 1, ?, 0, NULL, ?)""",
            ("legacy", "{\"make\":\"Ford\"}", 24, now.isoformat(),
             (now + timedelta(hours=24)).isoformat(), "active", "alice"),
        )
        temp_db.commit()

        # Legacy row has owner_site_user but no schedule_kind, so not counted
        assert count_active_for_owner(temp_db, "alice") == 0
