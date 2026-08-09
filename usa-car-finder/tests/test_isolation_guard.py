from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.isolation_guard import (
    IsolationViolation,
    assert_safe_test_checkout,
    assert_safe_test_database_path,
)


class IsolationGuardTests(unittest.TestCase):
    def test_current_checkout_is_isolated(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        guarded = assert_safe_test_checkout(repo_root)
        self.assertNotEqual(guarded, Path("/home/dawid/usacar"))
        self.assertNotEqual(guarded, Path("/opt/usacar"))

    def test_active_and_release_checkouts_are_rejected(self) -> None:
        forbidden = (
            "/home/dawid/usacar",
            "/home/dawid/usacar/usa-car-finder",
            "/opt/usacar/releases/ebf176d-caf6b6e596ec",
        )
        for candidate in forbidden:
            with self.subTest(candidate=candidate), self.assertRaises(IsolationViolation):
                assert_safe_test_checkout(candidate)

    def test_only_sqlite_inside_test_sandbox_is_allowed(self) -> None:
        with TemporaryDirectory(prefix="scheduled-search-") as directory:
            sandbox = Path(directory)
            expected = (sandbox / "watch_queue.db").resolve()
            self.assertEqual(
                assert_safe_test_database_path(expected, sandbox_root=sandbox), expected
            )
            with self.assertRaises(IsolationViolation):
                assert_safe_test_database_path(sandbox.parent / "escaped.db", sandbox_root=sandbox)
            with self.assertRaises(IsolationViolation):
                assert_safe_test_database_path(sandbox / "not-a-db.json", sandbox_root=sandbox)

    def test_production_sqlite_paths_are_rejected_before_open(self) -> None:
        production_paths = (
            "/home/dawid/usacar/usa-car-finder/data/watch_queue.db",
            "/home/dawid/usacar/usa-car-finder/data/app.db",
            "/opt/usacar/releases/current/usa-car-finder/data/watch_queue.db",
        )
        for candidate in production_paths:
            with self.subTest(candidate=candidate), self.assertRaises(IsolationViolation):
                assert_safe_test_database_path(candidate, sandbox_root=Path(candidate).parent)


if __name__ == "__main__":
    unittest.main()
