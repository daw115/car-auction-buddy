from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
import warnings

warnings.filterwarnings("ignore", category=ResourceWarning)

from api import watch_queue_db
from tests.isolation_guard import assert_safe_test_checkout, assert_safe_test_database_path

ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "api/main.py"
GOLDEN_PATH = ROOT / "tests/golden/legacy_queue_v1.json"
GOLDEN = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


class CapturedHTTPException(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class QuietLogger:
    def info(self, *args, **kwargs) -> None:
        pass

    def exception(self, *args, **kwargs) -> None:
        pass


class StubPhase:
    def __init__(self, **values) -> None:
        self.__dict__.update(values)


class StubSearchRequest:
    def __init__(self, **payload) -> None:
        self.payload = payload
        self.criteria = SimpleNamespace(**payload.get("criteria", {}))
        self.suppress_completion_notify = payload.get("suppress_completion_notify", False)

    def model_dump(self, mode: str = "python") -> dict:
        data = dict(self.payload)
        data["suppress_completion_notify"] = self.suppress_completion_notify
        return data


class StubJobsStore:
    Job = object

    def __init__(self) -> None:
        self.created = []

    def create_job(self, **values):
        job = SimpleNamespace(
            id=f"legacy-job-{len(self.created) + 1}",
            result=None,
            phases=[],
            status="queued",
            **values,
        )
        self.created.append(job)
        return job


class SearchPayload:
    def __init__(self, make: str = "BMW", model: str = "M5") -> None:
        self.criteria = SimpleNamespace(make=make, model=model)
        self._payload = {"criteria": {"make": make, "model": model}}

    def model_dump_json(self) -> str:
        return json.dumps(self._payload)


def _main_tree() -> ast.Module:
    return ast.parse(MAIN_PATH.read_text(encoding="utf-8"))


def _route_contract(function_name: str) -> dict:
    function = next(
        node
        for node in _main_tree().body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    decorator = next(
        item
        for item in function.decorator_list
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and isinstance(item.func.value, ast.Name)
        and item.func.value.id == "app"
    )
    result = {
        "method": decorator.func.attr.upper(),
        "path": ast.literal_eval(decorator.args[0]),
    }
    for keyword in decorator.keywords:
        if keyword.arg == "status_code":
            result["status_code"] = ast.literal_eval(keyword.value)
    return result


def _queue_request_interval_default() -> int:
    model = next(
        node
        for node in _main_tree().body
        if isinstance(node, ast.ClassDef) and node.name == "QueueWatchRequest"
    )
    field = next(
        node
        for node in model.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "interval_hours"
    )
    return ast.literal_eval(field.value)


def _legacy_namespace() -> dict:
    names = {
        "_clamp_interval_hours",
        "_compute_next_run_at",
        "_get_search_semaphore",
        "_run_job_with_queue",
        "create_watch",
        "list_watches",
        "cancel_watch",
        "_run_one_watch",
    }
    selected = []
    for node in _main_tree().body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            selected.append(node)
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *selected,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    jobs = StubJobsStore()
    namespace = {
        "asyncio": asyncio,
        "json": json,
        "datetime": datetime,
        "timedelta": timedelta,
        "Optional": object,
        "logger": QuietLogger(),
        "HTTPException": CapturedHTTPException,
        "Depends": lambda dependency: None,
        "_require_bearer": lambda: None,
        "SearchRequest": StubSearchRequest,
        "jobs_store": jobs,
        "search_title": lambda criteria: f"{criteria.make} {getattr(criteria, 'model', '')}".strip(),
        "_compute_criteria_hash": lambda request: "legacy-criteria-hash",
        "_WATCH_MIN_INTERVAL_H": GOLDEN["interval_hours"]["minimum"],
        "_WATCH_MAX_INTERVAL_H": GOLDEN["interval_hours"]["maximum"],
        "_SEARCH_MAX_CONCURRENT": 1,
        "_search_semaphore": None,
    }
    exec(compile(module, str(MAIN_PATH), "exec"), namespace)
    namespace["jobs_store"] = jobs
    return namespace


class LegacyQueueGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        assert_safe_test_checkout(ROOT.parent)
        self.tempdir = TemporaryDirectory(prefix="legacy-queue-golden-")
        self.addCleanup(self.tempdir.cleanup)
        sandbox = Path(self.tempdir.name)
        self.database = assert_safe_test_database_path(
            sandbox / "watch_queue.db", sandbox_root=sandbox
        )
        watch_queue_db.init_db(self.database)
        self.now = datetime(2026, 7, 21, 9, 30, tzinfo=timezone.utc)

        from api import _time_utils

        original_utc_now = _time_utils.utc_now
        _time_utils.utc_now = lambda: self.now
        self.addCleanup(setattr, _time_utils, "utc_now", original_utc_now)

        self.notify_calls = []
        notify_package = ModuleType("notify")
        notify_package.__path__ = []
        telegram = ModuleType("notify.telegram")
        telegram.is_configured = lambda: True
        telegram.notify_job_completion = lambda **kwargs: self.notify_calls.append(kwargs)
        notify_package.telegram = telegram
        self._replace_module("notify", notify_package)
        self._replace_module("notify.telegram", telegram)

        jobs_module = ModuleType("api.jobs")
        jobs_module.Phase = StubPhase
        self._replace_module("api.jobs", jobs_module)

    def _replace_module(self, name: str, replacement: ModuleType) -> None:
        sentinel = object()
        previous = sys.modules.get(name, sentinel)
        sys.modules[name] = replacement

        def restore() -> None:
            if previous is sentinel:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

        self.addCleanup(restore)

    def _add_watch(
        self,
        *,
        recurring: bool = False,
        chat_id: int | None = 123456,
        interval_hours: int = 12,
    ) -> int:
        return watch_queue_db.add_watch(
            request_json=SearchPayload().model_dump_json(),
            label="BMW M5 legacy",
            interval_hours=interval_hours,
            chat_id=chat_id,
            created_at=self.now.isoformat(timespec="seconds"),
            next_run_at=(self.now + timedelta(hours=interval_hours)).isoformat(
                timespec="seconds"
            ),
            recurring=recurring,
            preferred_hour=None,
        )

    def test_api_routes_match_the_legacy_golden(self) -> None:
        self.assertEqual(_route_contract("create_watch"), GOLDEN["api"]["post"])
        self.assertEqual(_route_contract("list_watches"), GOLDEN["api"]["get"])
        self.assertEqual(
            _route_contract("cancel_watch"),
            {
                "method": GOLDEN["api"]["delete"]["method"],
                "path": GOLDEN["api"]["delete"]["path"],
            },
        )

    def test_post_get_delete_and_repeated_delete_404(self) -> None:
        namespace = _legacy_namespace()
        request = SimpleNamespace(
            search=SearchPayload(),
            interval_hours=GOLDEN["interval_hours"]["default"],
            label=None,
            chat_id=777,
            recurring=False,
            preferred_hour=None,
        )
        created = asyncio.run(namespace["create_watch"](request))
        self.assertEqual(
            {key: created[key] for key in ("id", "label", "interval_hours", "recurring", "preferred_hour")},
            {"id": 1, "label": "BMW M5", "interval_hours": 12, "recurring": False, "preferred_hour": None},
        )
        self.assertEqual(
            datetime.fromisoformat(created["next_run_at"]),
            self.now + timedelta(hours=12),
        )
        listed = asyncio.run(namespace["list_watches"]())
        self.assertEqual(listed["count"], 1)
        self.assertEqual(list(listed["watches"][0]), GOLDEN["api"]["active_list_fields"])
        self.assertNotIn("request_json", listed["watches"][0])
        self.assertEqual(listed["watches"][0]["status"], "active")

        self.assertEqual(
            asyncio.run(namespace["cancel_watch"](created["id"])),
            {"id": created["id"], "status": "cancelled"},
        )
        self.assertEqual(asyncio.run(namespace["list_watches"]()), {"watches": [], "count": 0})
        with self.assertRaises(CapturedHTTPException) as raised:
            asyncio.run(namespace["cancel_watch"](created["id"]))
        self.assertEqual(
            raised.exception.status_code,
            GOLDEN["api"]["delete"]["missing_status_code"],
        )

    def test_interval_default_and_clamp_are_preserved(self) -> None:
        clamp = _legacy_namespace()["_clamp_interval_hours"]
        interval = GOLDEN["interval_hours"]
        self.assertEqual(_queue_request_interval_default(), interval["default"])
        self.assertEqual(clamp(None), interval["default"])
        self.assertEqual(clamp("invalid"), interval["default"])
        self.assertEqual(clamp(0), interval["minimum"])
        self.assertEqual(clamp(-100), interval["minimum"])
        self.assertEqual(clamp(169), interval["maximum"])
        self.assertEqual(clamp(10_000), interval["maximum"])
        self.assertEqual(clamp("24"), 24)

    def test_retry_until_found_stays_active_then_stops_and_notifies_once(self) -> None:
        watch_id = self._add_watch(recurring=False)
        namespace = _legacy_namespace()
        results = [
            {"collected_count": 0, "all_results": []},
            {"collected_count": 2, "all_results": [{"id": 1}, {"id": 2}], "record_id": 91},
        ]
        seen_requests = []

        async def fake_runner(request, job) -> None:
            seen_requests.append(request)
            job.result = results.pop(0)

        namespace["_run_job_with_queue"] = fake_runner
        asyncio.run(namespace["_run_one_watch"](watch_queue_db.get(watch_id)))
        after_empty = watch_queue_db.get(watch_id)
        self.assertEqual(
            (after_empty["active"], after_empty["runs_count"], after_empty["last_result_count"]),
            (1, 1, 0),
        )
        self.assertEqual(self.notify_calls, [])

        asyncio.run(namespace["_run_one_watch"](after_empty))
        after_found = watch_queue_db.get(watch_id)
        self.assertEqual((after_found["active"], after_found["status"]), (0, "found"))
        self.assertEqual((after_found["runs_count"], after_found["last_result_count"]), (2, 2))
        self.assertEqual(len(self.notify_calls), 1)
        self.assertEqual(self.notify_calls[0]["collected_count"], 2)
        self.assertTrue(all(request.suppress_completion_notify for request in seen_requests))

    def test_recurring_zero_result_stays_active_and_uses_global_telegram(self) -> None:
        watch_id = self._add_watch(recurring=True, chat_id=987654)
        namespace = _legacy_namespace()

        async def fake_runner(request, job) -> None:
            job.result = {"collected_count": 0, "all_results": [], "record_id": 44}

        namespace["_run_job_with_queue"] = fake_runner
        asyncio.run(namespace["_run_one_watch"](watch_queue_db.get(watch_id)))
        row = watch_queue_db.get(watch_id)
        self.assertEqual((row["active"], row["status"], row["runs_count"]), (1, "active", 1))
        self.assertEqual(row["last_result_count"], 0)
        self.assertEqual(len(self.notify_calls), 1)
        self.assertIn("brak nowych ofert", self.notify_calls[0]["title"])
        self.assertNotIn("chat_id", self.notify_calls[0])

    def test_manual_and_watch_jobs_share_the_same_search_semaphore(self) -> None:
        watch_id = self._add_watch(recurring=False)
        namespace = _legacy_namespace()
        active = 0
        peak = 0
        first_started = asyncio.Event()

        async def fake_run_job(request, job) -> None:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            first_started.set()
            try:
                await asyncio.sleep(0.03)
                job.result = {"collected_count": 0, "all_results": []}
            finally:
                active -= 1

        namespace["_run_job"] = fake_run_job

        async def exercise() -> None:
            manual_job = namespace["jobs_store"].create_job(criteria_hash="manual")
            manual = asyncio.create_task(
                namespace["_run_job_with_queue"](
                    StubSearchRequest(criteria={"make": "Audi"}), manual_job
                )
            )
            await first_started.wait()
            watch = asyncio.create_task(namespace["_run_one_watch"](watch_queue_db.get(watch_id)))
            await asyncio.gather(manual, watch)

        asyncio.run(exercise())
        self.assertEqual(peak, 1)
        self.assertEqual(len(namespace["jobs_store"].created), 2)

    def test_additive_schedule_kind_keeps_existing_rows_legacy_without_rewrite(self) -> None:
        first_id = self._add_watch(recurring=False)
        with sqlite3.connect(self.database) as connection:
            original = connection.execute(
                "SELECT label, request_json, interval_hours, chat_id, created_at, "
                "last_run_at, next_run_at, runs_count, last_result_count, active, status, "
                "recurring, preferred_hour FROM watch_entries WHERE id = ?",
                (first_id,),
            ).fetchone()
            # schedule_kind/owner_site_user are now provided by the additive
            # migration in watch_queue_db.init_db (task 2.2); no manual ALTER.

        watch_queue_db.init_db(self.database)
        second_id = self._add_watch(recurring=True)
        watch_queue_db.mark_run(
            first_id,
            last_run_at=self.now.isoformat(timespec="seconds"),
            next_run_at=(self.now + timedelta(hours=12)).isoformat(timespec="seconds"),
            result_count=0,
        )

        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            first = connection.execute("SELECT * FROM watch_entries WHERE id = ?", (first_id,)).fetchone()
            second = connection.execute("SELECT * FROM watch_entries WHERE id = ?", (second_id,)).fetchone()
            self.assertIsNone(first["schedule_kind"])
            self.assertIsNone(second["schedule_kind"])
            preserved = tuple(
                first[key]
                for key in (
                    "label", "request_json", "interval_hours", "chat_id", "created_at",
                    "next_run_at", "active", "status", "recurring", "preferred_hour",
                )
            )
            original_preserved = (
                original[0], original[1], original[2], original[3], original[4],
                original[6], original[9], original[10], original[11], original[12],
            )
            self.assertEqual(preserved, original_preserved)

            connection.execute(
                "INSERT INTO watch_entries "
                "(label, request_json, interval_hours, created_at, next_run_at, recurring, "
                "schedule_kind, owner_site_user) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "native fixture", "{}", 24, self.now.isoformat(timespec="seconds"),
                    (self.now + timedelta(hours=24)).isoformat(timespec="seconds"),
                    0, "scheduled_recurring_v1", "operator@example.com",
                ),
            )
            native_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM watch_entries "
                    "WHERE schedule_kind = 'scheduled_recurring_v1' ORDER BY id"
                )
            ]
            native_owner_count = connection.execute(
                "SELECT COUNT(*) FROM watch_entries "
                "WHERE schedule_kind = 'scheduled_recurring_v1' "
                "AND owner_site_user = ? AND active = 1",
                ("operator@example.com",),
            ).fetchone()[0]
            legacy_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM watch_entries WHERE schedule_kind IS NULL ORDER BY id"
                )
            ]

        self.assertEqual(len(native_ids), 1)
        self.assertEqual(native_owner_count, 1)
        self.assertEqual(legacy_ids, [first_id, second_id])
        self.assertTrue(set(legacy_ids).isdisjoint(native_ids))


if __name__ == "__main__":
    unittest.main()
