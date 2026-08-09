import json
from pathlib import Path
import unittest

from tests.isolation_guard import assert_safe_test_checkout

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/contracts/scheduled_searches/v1"


def load(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def assert_public(value: object) -> None:
    blocked = ("authorization", "bearer", "cf-access", "token", "db_path", "sql", "raw_body")
    if isinstance(value, dict):
        for key, nested in value.items():
            if any(marker in key.lower() for marker in blocked):
                raise AssertionError(f"sensitive contract key: {key}")
            assert_public(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_public(nested)


class ScheduledSearchContractFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert_safe_test_checkout(ROOT.parent)
        cls.manifest = load("manifest.json")

    def test_manifest_is_v1_and_covers_every_json_fixture(self) -> None:
        self.assertEqual(self.manifest["contract"], "scheduled_searches_v1")
        self.assertEqual(self.manifest["contract_version"], 1)
        declared = {item["file"] for item in self.manifest["fixtures"]}
        actual = {path.name for path in FIXTURES.glob("*.json")} - {"manifest.json"}
        self.assertEqual(declared, actual)
        self.assertEqual({item["role"] for item in self.manifest["fixtures"]},
                         {"criteria", "request", "response", "error", "capability", "history"})

    def test_routes_are_additive_schedule_routes_without_legacy_fallback(self) -> None:
        for route in self.manifest["routes"]:
            self.assertTrue(route["path"].startswith("/api/queue/schedules"))
            self.assertIn(route["method"], {"GET", "POST", "PATCH", "PUT", "DELETE"})

    def test_criteria_frequency_owner_and_zero_result_contract(self) -> None:
        criteria = load("criteria.valid.json")
        self.assertEqual(criteria["sources"], ["copart", "iaai", "manheim"])
        self.assertEqual(criteria["max_results"], 100)
        self.assertEqual(load("create-request.valid.json")["interval_hours"], 168)
        envelope = load("schedule-envelope.success.json")
        self.assertEqual(envelope["schedule"]["owner_site_user"], "operator@example.com")
        history = load("execution-history.success.json")["executions"]
        zero_result = next(item for item in history if item["status"] == "succeeded")
        self.assertEqual(zero_result["result_count"], 0)
        self.assertIsNotNone(zero_result["record_id"])

    def test_all_public_fixtures_are_sanitized_json_objects(self) -> None:
        for item in self.manifest["fixtures"]:
            payload = load(item["file"])
            self.assertIsInstance(payload, dict)
            assert_public(payload)


if __name__ == "__main__":
    unittest.main()
