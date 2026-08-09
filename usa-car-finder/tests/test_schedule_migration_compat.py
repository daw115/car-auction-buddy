"""Task 2.5: additive migration + schema-compatibility tests.

Extends the task 2.2 migration tests (tests/test_schedule_migration.py) with the
scope required by task 2.5:

  * the full four starting-state matrix (empty, legacy-only, partially migrated
    and current) driven through one helper that asserts the target DDL, the
    UNIQUE / CHECK / partial-index constraints and idempotent repeatability;
  * transactional rollback when a migration statement fails mid-way, proving the
    additive DDL and legacy rows are left untouched; and
  * a structural fixture record store that confirms the exactly-once UNIQUE
    non-null job_id guarantee plus insert-or-read-existing semantics, grounded
    on the confirmed record-store names (search_records.job_id from the 2.2
    discovery). The fixture DDL is built from those confirmed constants and the
    confirmation test fails if the real schema no longer exposes them, so the
    suite never guesses production schema names.

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

# Confirmed native-schedule target schema (design "Controlled additive SQLite
# migration"; mirrors the constants exercised by tests/test_schedule_migration.py).
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

# Record store names confirmed during task 2.2 discovery (api/client_database.py).
# The fixture record store is built from these constants; the confirmation test
# fails loudly if the real schema stops exposing them.
CONFIRMED_RECORD_TABLE = "search_records"
CONFIRMED_JOB_COLUMN = "job_id"

# Production-current base shape of watch_entries (includes the legacy additive
# columns recurring / preferred_hour), before the native-schedule migration.
BASE_WATCH_DDL = """
CREATE TABLE watch_entries (
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
    status TEXT NOT NULL DEFAULT 'active',
    recurring INTEGER NOT NULL DEFAULT 0,
    preferred_hour INTEGER
);
CREATE INDEX IF NOT EXISTS idx_watch_due ON watch_entries(active, next_run_at);
"""


class ScheduleMigrationCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        assert_safe_test_checkout(ROOT.parent)
        self._tempdir = TemporaryDirectory(prefix="schedule-migration-compat-")
        self.addCleanup(self._tempdir.cleanup)
        self.sandbox = Path(self._tempdir.name)
        self.now = datetime(2026, 7, 21, 9, 30, tzinfo=timezone.utc)

    # ---- helpers -----------------------------------------------------------
    def _sandbox_db(self, name: str) -> str:
        return str(
            assert_safe_test_database_path(
                self.sandbox / name, sandbox_root=self.sandbox
            )
        )

    def _create_base(self, name: str) -> str:
        db_path = self._sandbox_db(name)
        with sqlite3.connect(db_path) as conn:
            conn.executescript(BASE_WATCH_DDL)
        return db_path

    def _insert_legacy_row(self, db_path: str, *, recurring: bool) -> int:
        created = self.now.isoformat(timespec="seconds")
        nxt = (self.now + timedelta(hours=12)).isoformat(timespec="seconds")
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(
                "INSERT INTO watch_entries "
                "(label, request_json, interval_hours, chat_id, created_at, "
                "next_run_at, recurring, preferred_hour) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "legacy watch",
                    '{"criteria": {"make": "BMW"}}',
                    12,
                    123456,
                    created,
                    nxt,
                    1 if recurring else 0,
                    None,
                ),
            )
            return int(cur.lastrowid)

    def _objects(self, db_path: str, kind: str) -> set[str]:
        with sqlite3.connect(db_path) as conn:
            return {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = ?", (kind,)
                )
            }

    def _columns(self, db_path: str, table: str) -> set[str]:
        with sqlite3.connect(db_path) as conn:
            return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

    # ---- starting-state builders -------------------------------------------
    def _state_empty(self) -> str:
        # Base watch_entries only, no rows, native migration not yet applied.
        return self._create_base("empty.db")

    def _state_legacy_only(self) -> str:
        db_path = self._create_base("legacy_only.db")
        self._insert_legacy_row(db_path, recurring=False)
        self._insert_legacy_row(db_path, recurring=True)
        return db_path

    def _state_partial(self) -> str:
        # Some native columns and one ledger table already present.
        db_path = self._create_base("partial.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute("ALTER TABLE watch_entries ADD COLUMN schedule_kind TEXT")
            conn.execute("ALTER TABLE watch_entries ADD COLUMN owner_site_user TEXT")
            conn.execute(
                "CREATE TABLE schedule_notifications ("
                "execution_id TEXT NOT NULL, "
                "channel TEXT NOT NULL CHECK(channel = 'telegram_global'), "
                "enabled_snapshot INTEGER NOT NULL, "
                "status TEXT NOT NULL, "
                "attempt_count INTEGER NOT NULL DEFAULT 0 "
                "CHECK(attempt_count BETWEEN 0 AND 2), "
                "error_code TEXT, "
                "created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL, "
                "PRIMARY KEY(execution_id, channel))"
            )
        self._insert_legacy_row(db_path, recurring=False)
        return db_path

    def _state_current(self) -> str:
        # Fully migrated / current schema via the production init_db path.
        db_path = self._sandbox_db("current.db")
        watch_queue_db.init_db(Path(db_path))
        self._insert_legacy_row(db_path, recurring=True)
        return db_path

    # ---- shared assertions -------------------------------------------------
    def _assert_target_schema(self, db_path: str) -> None:
        self.assertTrue(EXPECTED_COLUMNS.issubset(self._columns(db_path, "watch_entries")))
        self.assertTrue(EXPECTED_TABLES.issubset(self._objects(db_path, "table")))
        self.assertTrue(EXPECTED_INDEXES.issubset(self._objects(db_path, "index")))

    def _assert_ledger_constraints(self, db_path: str) -> None:
        created = self.now.isoformat(timespec="seconds")
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO schedule_executions "
                "(id, schedule_id, owner_site_user, scheduled_for, "
                "criteria_snapshot_json, interval_hours_snapshot, status, "
                "job_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("exec-1", 1, "op@example.com", created, "{}", 24, "queued",
                 "schedule:exec-1", created),
            )
            # UNIQUE(schedule_id, scheduled_for)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO schedule_executions "
                    "(id, schedule_id, owner_site_user, scheduled_for, "
                    "criteria_snapshot_json, interval_hours_snapshot, status, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("exec-2", 1, "op@example.com", created, "{}", 24, "queued",
                     created),
                )
            # Partial UNIQUE index on non-null job_id
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO schedule_executions "
                    "(id, schedule_id, owner_site_user, scheduled_for, "
                    "criteria_snapshot_json, interval_hours_snapshot, status, "
                    "job_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("exec-3", 2, "op@example.com", created, "{}", 24, "queued",
                     "schedule:exec-1", created),
                )
            # CHECK interval_hours_snapshot BETWEEN 1 AND 168
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO schedule_executions "
                    "(id, schedule_id, owner_site_user, scheduled_for, "
                    "criteria_snapshot_json, interval_hours_snapshot, status, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("exec-4", 3, "op@example.com", created, "{}", 200, "queued",
                     created),
                )
            # Two null job_id rows coexist (partial index ignores NULLs).
            conn.execute(
                "INSERT INTO schedule_executions "
                "(id, schedule_id, owner_site_user, scheduled_for, "
                "criteria_snapshot_json, interval_hours_snapshot, status, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("exec-5", 4, "op@example.com", created, "{}", 24, "queued",
                 created),
            )
            conn.execute(
                "INSERT INTO schedule_executions "
                "(id, schedule_id, owner_site_user, scheduled_for, "
                "criteria_snapshot_json, interval_hours_snapshot, status, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("exec-6", 5, "op@example.com", created, "{}", 24, "queued",
                 created),
            )
            # CHECK attempt_no BETWEEN 1 AND 3 on attempts table
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO schedule_execution_attempts "
                    "(execution_id, attempt_no, status, started_at) "
                    "VALUES (?, ?, ?, ?)",
                    ("exec-1", 4, "running", created),
                )
            # CHECK channel = 'telegram_global' on notifications table
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO schedule_notifications "
                    "(execution_id, channel, enabled_snapshot, status, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    ("exec-1", "email", 1, "pending", created, created),
                )

    # ---- migration matrix --------------------------------------------------
    def test_migration_over_all_starting_states(self) -> None:
        builders = (
            ("empty", self._state_empty),
            ("legacy-only", self._state_legacy_only),
            ("partially-migrated", self._state_partial),
            ("current", self._state_current),
        )
        for state_name, builder in builders:
            with self.subTest(state=state_name):
                db_path = builder()
                watch_queue_db.apply_schedule_migration(Path(db_path))
                self._assert_target_schema(db_path)
                self._assert_ledger_constraints(db_path)

    def test_migration_is_repeatable_no_op_for_every_state(self) -> None:
        builders = (
            ("empty", self._state_empty),
            ("legacy-only", self._state_legacy_only),
            ("partially-migrated", self._state_partial),
            ("current", self._state_current),
        )
        for state_name, builder in builders:
            with self.subTest(state=state_name):
                db_path = builder()
                watch_queue_db.apply_schedule_migration(Path(db_path))
                with sqlite3.connect(db_path) as conn:
                    before = {
                        row[0]: row[1]
                        for row in conn.execute(
                            "SELECT name, sql FROM sqlite_master WHERE name IS NOT NULL"
                        )
                    }
                watch_queue_db.apply_schedule_migration(Path(db_path))
                with sqlite3.connect(db_path) as conn:
                    after = {
                        row[0]: row[1]
                        for row in conn.execute(
                            "SELECT name, sql FROM sqlite_master WHERE name IS NOT NULL"
                        )
                    }
                self.assertEqual(before, after)

    def test_legacy_rows_preserved_byte_for_byte_and_null_kind(self) -> None:
        db_path = self._state_legacy_only()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            before = [dict(r) for r in conn.execute(
                "SELECT * FROM watch_entries ORDER BY id"
            )]
        watch_queue_db.apply_schedule_migration(Path(db_path))
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            after = [dict(r) for r in conn.execute(
                "SELECT * FROM watch_entries ORDER BY id"
            )]
        for row in after:
            self.assertIsNone(row["schedule_kind"])
        # Every legacy column value is unchanged (no rewrite / backfill).
        for original, migrated in zip(before, after):
            for column, value in original.items():
                self.assertEqual(migrated[column], value)

    # ---- transactional rollback --------------------------------------------
    def test_migration_rolls_back_on_injected_error(self) -> None:
        db_path = self._state_legacy_only()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            before_rows = [dict(r) for r in conn.execute(
                "SELECT * FROM watch_entries ORDER BY id"
            )]
        before_cols = self._columns(db_path, "watch_entries")
        before_tables = self._objects(db_path, "table")

        original = watch_queue_db._SCHEDULE_LEDGER_STATEMENTS
        # Append a statement that fails only after all valid DDL has run.
        watch_queue_db._SCHEDULE_LEDGER_STATEMENTS = original + (
            "INSERT INTO __missing_table_zzz__ (x) VALUES (1)",
        )
        self.addCleanup(
            setattr, watch_queue_db, "_SCHEDULE_LEDGER_STATEMENTS", original
        )

        with self.assertRaises(sqlite3.OperationalError):
            watch_queue_db.apply_schedule_migration(Path(db_path))

        # DDL is transactional in SQLite: the failed run must leave no trace.
        self.assertEqual(before_cols, self._columns(db_path, "watch_entries"))
        self.assertEqual(before_tables, self._objects(db_path, "table"))
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            after_rows = [dict(r) for r in conn.execute(
                "SELECT * FROM watch_entries ORDER BY id"
            )]
        self.assertEqual(before_rows, after_rows)

        # A clean re-run after the injected error is restored succeeds fully.
        watch_queue_db._SCHEDULE_LEDGER_STATEMENTS = original
        watch_queue_db.apply_schedule_migration(Path(db_path))
        self._assert_target_schema(db_path)

    # ---- structural fixture record store -----------------------------------
    def test_record_store_confirms_search_records_job_id(self) -> None:
        from api import client_database

        app_db = self._sandbox_db("app.db")
        original_path = client_database.DB_PATH
        client_database.DB_PATH = Path(app_db)
        self.addCleanup(setattr, client_database, "DB_PATH", original_path)
        client_database.init_db()

        tables = self._objects(app_db, "table")
        self.assertIn(
            CONFIRMED_RECORD_TABLE,
            tables,
            "confirmed record store table search_records not present",
        )
        cols = self._columns(app_db, CONFIRMED_RECORD_TABLE)
        self.assertIn(
            CONFIRMED_JOB_COLUMN,
            cols,
            "confirmed record store column job_id not present",
        )

    def _build_fixture_record_store(self, name: str) -> str:
        db_path = self._sandbox_db(name)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                f"CREATE TABLE {CONFIRMED_RECORD_TABLE} ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                f"{CONFIRMED_JOB_COLUMN} TEXT)"
            )
            conn.execute(
                f"CREATE UNIQUE INDEX idx_fixture_record_job "
                f"ON {CONFIRMED_RECORD_TABLE}({CONFIRMED_JOB_COLUMN}) "
                f"WHERE {CONFIRMED_JOB_COLUMN} IS NOT NULL"
            )
        return db_path

    def test_fixture_record_store_enforces_unique_non_null_job_id(self) -> None:
        store = self._build_fixture_record_store("fixture_records.db")
        with sqlite3.connect(store) as conn:
            conn.execute(
                f"INSERT INTO {CONFIRMED_RECORD_TABLE} ({CONFIRMED_JOB_COLUMN}) "
                "VALUES (?)",
                ("schedule:exec-1",),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    f"INSERT INTO {CONFIRMED_RECORD_TABLE} "
                    f"({CONFIRMED_JOB_COLUMN}) VALUES (?)",
                    ("schedule:exec-1",),
                )
            # NULL job_id is exempt from the partial unique index.
            conn.execute(
                f"INSERT INTO {CONFIRMED_RECORD_TABLE} ({CONFIRMED_JOB_COLUMN}) "
                "VALUES (NULL)"
            )
            conn.execute(
                f"INSERT INTO {CONFIRMED_RECORD_TABLE} ({CONFIRMED_JOB_COLUMN}) "
                "VALUES (NULL)"
            )
            null_count = conn.execute(
                f"SELECT COUNT(*) FROM {CONFIRMED_RECORD_TABLE} "
                f"WHERE {CONFIRMED_JOB_COLUMN} IS NULL"
            ).fetchone()[0]
        self.assertEqual(null_count, 2)

    def test_fixture_record_store_insert_or_read_existing(self) -> None:
        store = self._build_fixture_record_store("fixture_records_ior.db")

        def insert_or_read_existing(conn: sqlite3.Connection, job_id: str) -> int:
            conn.execute(
                f"INSERT OR IGNORE INTO {CONFIRMED_RECORD_TABLE} "
                f"({CONFIRMED_JOB_COLUMN}) VALUES (?)",
                (job_id,),
            )
            row = conn.execute(
                f"SELECT id FROM {CONFIRMED_RECORD_TABLE} "
                f"WHERE {CONFIRMED_JOB_COLUMN} = ? LIMIT 1",
                (job_id,),
            ).fetchone()
            return int(row[0])

        with sqlite3.connect(store) as conn:
            first = insert_or_read_existing(conn, "schedule:exec-42")
            second = insert_or_read_existing(conn, "schedule:exec-42")
            self.assertEqual(first, second)
            total = conn.execute(
                f"SELECT COUNT(*) FROM {CONFIRMED_RECORD_TABLE}"
            ).fetchone()[0]
        self.assertEqual(total, 1)

class RecordStoreUniqueJobIdConstraintTests(unittest.TestCase):
    """Task 2.5 structural tests: additive UNIQUE partial index on
    search_records.job_id (WHERE job_id IS NOT NULL).

    Discovery from 2.2 confirmed:
      - table: search_records (api/client_database.py)
      - column: job_id (TEXT, nullable)
      - existing index: idx_search_records_job_id (NON-unique)

    Design requires exactly-once Search_Record linkage via a UNIQUE
    partial index on non-null job_id. Task 5.1 implements the additive
    migration; this test validates the constraint structurally and
    MUST FAIL until 5.1 is complete.

    NOTE FOR TASK 5.1: implement CREATE UNIQUE INDEX IF NOT EXISTS
    idx_search_records_job_id_unique ON search_records(job_id)
    WHERE job_id IS NOT NULL; update insert-or-read-existing to use
    INSERT ... ON CONFLICT DO NOTHING + SELECT id pattern.
    """

    def setUp(self) -> None:
        assert_safe_test_checkout(ROOT.parent)
        self._tempdir = TemporaryDirectory(prefix="record-store-constraint-")
        self.addCleanup(self._tempdir.cleanup)
        self.sandbox = Path(self._tempdir.name)

    def _sandbox_db(self, name: str) -> str:
        return str(
            assert_safe_test_database_path(
                self.sandbox / name, sandbox_root=self.sandbox
            )
        )

    @unittest.expectedFailure  # Remove after task 5.1 adds the UNIQUE partial index
    def test_real_record_store_has_unique_partial_index_on_job_id(self) -> None:
        """Confirm the actual client_database schema enforces UNIQUE
        non-null job_id. Fails until task 5.1 adds the partial unique index.

        NOTE FOR TASK 5.1: This test will pass once the additive migration
        CREATE UNIQUE INDEX ... ON search_records(job_id) WHERE job_id IS NOT NULL
        is implemented in api/client_database.py.
        """
        from api import client_database

        app_db = self._sandbox_db("app_constraint.db")
        original_path = client_database.DB_PATH
        client_database.DB_PATH = Path(app_db)
        self.addCleanup(setattr, client_database, "DB_PATH", original_path)
        client_database.init_db()

        # Check sqlite_master for a UNIQUE index on job_id with partial condition
        with sqlite3.connect(app_db) as conn:
            rows = conn.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = ? AND tbl_name = ? AND sql IS NOT NULL",
                ("index", CONFIRMED_RECORD_TABLE),
            ).fetchall()

        unique_partial_found = False
        for idx_name, idx_sql in rows:
            upper_sql = idx_sql.upper() if idx_sql else ""
            if "UNIQUE" in upper_sql and CONFIRMED_JOB_COLUMN in idx_sql:
                if "NOT NULL" in upper_sql:
                    unique_partial_found = True
                    break

        self.assertTrue(
            unique_partial_found,
            "UNIQUE partial index on {table}.{col} "
            "(WHERE job_id IS NOT NULL) not found in real record store schema. "
            "NOTE: Task 5.1 must add this constraint before enabling "
            "scheduled_searches_v1 capability. Found indexes: "
            "{idxs}".format(
                table=CONFIRMED_RECORD_TABLE,
                col=CONFIRMED_JOB_COLUMN,
                idxs=[(n, s) for n, s in rows],
            ),
        )

    @unittest.expectedFailure  # Remove after task 5.1 adds the UNIQUE partial index
    def test_real_record_store_rejects_duplicate_non_null_job_id(self) -> None:
        """Attempt to insert duplicate non-null job_id into the real record
        store schema. Fails until task 5.1 adds the UNIQUE partial index.

        NOTE FOR TASK 5.1: Once the unique partial index is added, this test
        will pass because sqlite3.IntegrityError will be raised on duplicate
        non-null job_id inserts, enabling insert-or-read-existing semantics.
        """
        from api import client_database

        app_db = self._sandbox_db("app_dup_check.db")
        original_path = client_database.DB_PATH
        client_database.DB_PATH = Path(app_db)
        self.addCleanup(setattr, client_database, "DB_PATH", original_path)
        client_database.init_db()

        with sqlite3.connect(app_db) as conn:
            conn.execute(
                "INSERT INTO {table} "
                "(title, status, criteria_json, request_json, response_json, "
                "created_at, updated_at, job_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)".format(table=CONFIRMED_RECORD_TABLE),
                ("rec1", "new", "{}", "{}", "{}", "2026-01-01T00:00:00",
                 "2026-01-01T00:00:00", "schedule:exec-dup"),
            )
            # This MUST raise IntegrityError if the UNIQUE partial index exists
            duplicate_rejected = False
            try:
                conn.execute(
                    "INSERT INTO {table} "
                    "(title, status, criteria_json, request_json, response_json, "
                    "created_at, updated_at, job_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)".format(table=CONFIRMED_RECORD_TABLE),
                    ("rec2", "new", "{}", "{}", "{}", "2026-01-01T00:00:00",
                     "2026-01-01T00:00:00", "schedule:exec-dup"),
                )
            except sqlite3.IntegrityError:
                duplicate_rejected = True

        self.assertTrue(
            duplicate_rejected,
            "Duplicate non-null job_id was accepted by the real record store. "
            "NOTE: Task 5.1 must add UNIQUE partial index on "
            "{table}.{col} "
            "(WHERE job_id IS NOT NULL) to enforce exactly-once record linkage.".format(
                table=CONFIRMED_RECORD_TABLE,
                col=CONFIRMED_JOB_COLUMN,
            ),
        )


if __name__ == "__main__":
    unittest.main()
