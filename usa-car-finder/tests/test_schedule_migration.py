"""Targeted tests for the additive, idempotent native-schedule migration.

Covers task 2.2: nullable/default-safe columns, ledger tables/indexes,
structural version check via PRAGMA table_info, transactional idempotent
repeatability (re-run is a no-op) and non-destructive legacy behaviour
(existing rows keep schedule_kind IS NULL and are not rewritten).

Runs only against isolated temp SQLite (never a production database).
"""
from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from api import watch_queue_db
from tests.isolation_guard import (
    assert_safe_test_checkout,
    assert_safe_test_database_path,
)

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_COLUMNS = {
    "schedule_kind",
    "owner_site_user",
    "notifications_enabled",
    "deleted_at",
    "updated_at",
    "updated_by_site_user",
    "version",
    "last_execution_status",
    "last_error_code",
    "last_error_message",
    "in_flight_execution_id",
}

EXPECTED_TABLES = {
    "schedule_executions",
    "schedule_execution_attempts",
    "schedule_notifications",
}

EXPECTED_INDEXES = {
    "idx_native_schedule_due",
    "idx_native_schedule_owner",
    "idx_schedule_execution_job",
    "idx_schedule_execution_record",
    "idx_schedule_execution_history",
    "idx_schedule_execution_claim",
}


class ScheduleMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        assert_safe_test_checkout(ROOT.parent)
        self.tempdir = TemporaryDirectory(prefix="schedule-migration-")
        self.addCleanup(self.tempdir.cleanup)
        sandbox = Path(self.tempdir.name)
        self.database = assert_safe_test_database_path(
            sandbox / "watch_queue.db", sandbox_root=sandbox
        )
        self.now = datetime(2026, 7, 21, 9, 30, tzinfo=timezone.utc)

    def _columns(self, connection: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}

    def _objects(self, connection: sqlite3.Connection, kind: str) -> set[str]:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = ?", (kind,)
            )
        }

    def _add_legacy_watch(self, *, recurring: bool = False) -> int:
        return watch_queue_db.add_watch(
            request_json='{"criteria": {"make": "BMW"}}',
            label="legacy watch",
            interval_hours=12,
            chat_id=123456,
            created_at=self.now.isoformat(timespec="seconds"),
            next_run_at=(self.now + timedelta(hours=12)).isoformat(timespec="seconds"),
            recurring=recurring,
            preferred_hour=None,
        )

    def test_init_db_adds_all_columns_tables_and_indexes(self) -> None:
        watch_queue_db.init_db(self.database)
        with sqlite3.connect(self.database) as connection:
            columns = self._columns(connection, "watch_entries")
            self.assertTrue(EXPECTED_COLUMNS.issubset(columns))
            self.assertTrue(EXPECTED_TABLES.issubset(self._objects(connection, "table")))
            self.assertTrue(EXPECTED_INDEXES.issubset(self._objects(connection, "index")))

    def test_defaults_are_safe_for_new_rows(self) -> None:
        watch_queue_db.init_db(self.database)
        watch_id = self._add_legacy_watch()
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM watch_entries WHERE id = ?", (watch_id,)
            ).fetchone()
        self.assertIsNone(row["schedule_kind"])
        self.assertIsNone(row["owner_site_user"])
        self.assertEqual(row["notifications_enabled"], 0)
        self.assertEqual(row["version"], 1)
        self.assertIsNone(row["deleted_at"])

    def test_migration_is_idempotent_noop_on_rerun(self) -> None:
        watch_queue_db.init_db(self.database)
        with sqlite3.connect(self.database) as connection:
            before = {
                row[0]: row[1]
                for row in connection.execute(
                    "SELECT name, sql FROM sqlite_master WHERE name IS NOT NULL"
                )
            }
        # Re-run twice; must be a pure no-op (same schema, no errors).
        watch_queue_db.init_db(self.database)
        watch_queue_db.apply_schedule_migration(self.database)
        with sqlite3.connect(self.database) as connection:
            after = {
                row[0]: row[1]
                for row in connection.execute(
                    "SELECT name, sql FROM sqlite_master WHERE name IS NOT NULL"
                )
            }
        self.assertEqual(before, after)

    def test_partially_migrated_db_is_completed_without_error(self) -> None:
        # Simulate a DB where a couple of native columns already exist.
        watch_queue_db.init_db(self.database)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "DROP INDEX IF EXISTS idx_native_schedule_owner"
            )
        # Fresh DB path with only base table + some native columns present.
        other = Path(self.tempdir.name) / "partial.db"
        with sqlite3.connect(other) as connection:
            connection.executescript(
                """
                CREATE TABLE watch_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_json TEXT NOT NULL,
                    interval_hours INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'active'
                );
                ALTER TABLE watch_entries ADD COLUMN schedule_kind TEXT;
                ALTER TABLE watch_entries ADD COLUMN owner_site_user TEXT;
                """
            )
        watch_queue_db.apply_schedule_migration(other)
        with sqlite3.connect(other) as connection:
            columns = self._columns(connection, "watch_entries")
            self.assertTrue(EXPECTED_COLUMNS.issubset(columns))
            self.assertTrue(EXPECTED_TABLES.issubset(self._objects(connection, "table")))

    def test_legacy_rows_stay_null_kind_and_are_not_rewritten(self) -> None:
        watch_queue_db.init_db(self.database)
        legacy_id = self._add_legacy_watch(recurring=True)
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            original = dict(
                connection.execute(
                    "SELECT * FROM watch_entries WHERE id = ?", (legacy_id,)
                ).fetchone()
            )
        # Re-apply migration; legacy row must be byte-for-byte unchanged.
        watch_queue_db.apply_schedule_migration(self.database)
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            after = dict(
                connection.execute(
                    "SELECT * FROM watch_entries WHERE id = ?", (legacy_id,)
                ).fetchone()
            )
        self.assertIsNone(after["schedule_kind"])
        self.assertEqual(original, after)

    def test_ledger_unique_and_check_constraints_are_enforced(self) -> None:
        watch_queue_db.init_db(self.database)
        created = self.now.isoformat(timespec="seconds")
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO schedule_executions "
                "(id, schedule_id, owner_site_user, scheduled_for, "
                "criteria_snapshot_json, interval_hours_snapshot, status, "
                "job_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("exec-1", 1, "op@example.com", created, "{}", 24, "queued",
                 "schedule:exec-1", created),
            )
            # Duplicate (schedule_id, scheduled_for) is rejected.
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO schedule_executions "
                    "(id, schedule_id, owner_site_user, scheduled_for, "
                    "criteria_snapshot_json, interval_hours_snapshot, status, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("exec-2", 1, "op@example.com", created, "{}", 24, "queued", created),
                )
            # Duplicate non-null job_id is rejected by the partial unique index.
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO schedule_executions "
                    "(id, schedule_id, owner_site_user, scheduled_for, "
                    "criteria_snapshot_json, interval_hours_snapshot, status, "
                    "job_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("exec-3", 2, "op@example.com", created, "{}", 24, "queued",
                     "schedule:exec-1", created),
                )
            # interval snapshot out of 1..168 is rejected by CHECK.
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO schedule_executions "
                    "(id, schedule_id, owner_site_user, scheduled_for, "
                    "criteria_snapshot_json, interval_hours_snapshot, status, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("exec-4", 3, "op@example.com", created, "{}", 200, "queued", created),
                )


if __name__ == "__main__":
    unittest.main()
