"""Unit tests for the strict scheduled-search domain models (task 2.1).

Validates Requirements 1.1, 1.2, 2.1, 2.3, 5.1, 5.2, 7.3, 10.5, 11.3:
strict request/response/error/capability/history models, unknown-key rejection,
client-controlled attribution rejection, explicit-default normalization
(sources -> [copart, iaai]; notifications off) and NO clamping of
interval_hours / max_results / sources.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from tests.isolation_guard import assert_safe_test_checkout

from api.scheduled_search_models import (
    ALLOWED_SOURCES,
    DEFAULT_SOURCES,
    CreateScheduledSearchRequest,
    NotificationSettings,
    PublicErrorEnvelope,
    ScheduledSearchCapability,
    ScheduledSearchCriteria,
    ScheduledSearchEnvelope,
    ScheduledSearchList,
    ScheduleExecutionList,
    SetScheduledSearchStateRequest,
    UpdateScheduledSearchRequest,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/contracts/scheduled_searches/v1"


def load(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class SafeCheckoutMixin(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert_safe_test_checkout(ROOT.parent)


class CriteriaModelTests(SafeCheckoutMixin):
    def test_valid_criteria_fixture_roundtrips_without_clamping(self) -> None:
        raw = load("criteria.valid.json")
        criteria = ScheduledSearchCriteria.model_validate(raw)
        self.assertEqual(criteria.max_results, 100)
        self.assertEqual(criteria.sources, ["copart", "iaai", "manheim"])
        self.assertEqual(criteria.fuel_type, "Hybrid")
        self.assertEqual(criteria.excluded_damage_types, ["Flood", "Burn"])

    def test_absent_sources_normalized_to_default_pair(self) -> None:
        criteria = ScheduledSearchCriteria.model_validate({"make": "Toyota"})
        self.assertEqual(criteria.sources, DEFAULT_SOURCES)
        self.assertIsNot(criteria.sources, DEFAULT_SOURCES)  # copy, not shared

    def test_sources_lowercased(self) -> None:
        criteria = ScheduledSearchCriteria.model_validate(
            {"make": "Toyota", "sources": ["Copart", "IAAI"]}
        )
        self.assertEqual(criteria.sources, ["copart", "iaai"])

    def test_unsupported_source_rejected_not_clamped(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate(
                {"make": "Toyota", "sources": ["copart", "ebay"]}
            )

    def test_empty_sources_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate({"make": "Toyota", "sources": []})

    def test_too_many_sources_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate(
                {"make": "Toyota", "sources": ["copart", "iaai", "manheim", "copart"]}
            )

    def test_max_results_upper_bound_101_rejected_not_clamped(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate({"make": "Toyota", "max_results": 101})

    def test_max_results_zero_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate({"make": "Toyota", "max_results": 0})

    def test_max_results_100_accepted(self) -> None:
        criteria = ScheduledSearchCriteria.model_validate(
            {"make": "Toyota", "max_results": 100}
        )
        self.assertEqual(criteria.max_results, 100)

    def test_missing_make_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate({"model": "RAV4"})

    def test_blank_make_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate({"make": "   "})

    def test_year_from_greater_than_year_to_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate(
                {"make": "Toyota", "year_from": 2024, "year_to": 2020}
            )

    def test_unknown_criteria_key_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate({"make": "Toyota", "surprise": 1})

    def test_searched_by_rejected_in_criteria(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate(
                {"make": "Toyota", "searched_by": "operator@example.com"}
            )

    def test_bad_fuel_type_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ScheduledSearchCriteria.model_validate({"make": "Toyota", "fuel_type": "LPG"})


class CreateRequestTests(SafeCheckoutMixin):
    def test_valid_create_fixture_parses(self) -> None:
        req = CreateScheduledSearchRequest.model_validate(load("create-request.valid.json"))
        self.assertEqual(req.interval_hours, 168)
        self.assertEqual(req.label, "RAV4 Hybrid daily")
        self.assertFalse(req.notifications.telegram_global)
        self.assertEqual(req.criteria.max_results, 100)

    def test_notifications_default_off_when_absent(self) -> None:
        req = CreateScheduledSearchRequest.model_validate(
            {"criteria": {"make": "Toyota"}, "interval_hours": 24}
        )
        self.assertIsInstance(req.notifications, NotificationSettings)
        self.assertFalse(req.notifications.telegram_global)

    def test_interval_zero_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CreateScheduledSearchRequest.model_validate(
                {"criteria": {"make": "Toyota"}, "interval_hours": 0}
            )

    def test_interval_169_rejected_not_clamped(self) -> None:
        with self.assertRaises(ValidationError):
            CreateScheduledSearchRequest.model_validate(
                {"criteria": {"make": "Toyota"}, "interval_hours": 169}
            )

    def test_interval_bool_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CreateScheduledSearchRequest.model_validate(
                {"criteria": {"make": "Toyota"}, "interval_hours": True}
            )

    def test_interval_fractional_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CreateScheduledSearchRequest.model_validate(
                {"criteria": {"make": "Toyota"}, "interval_hours": 24.5}
            )

    def test_missing_interval_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CreateScheduledSearchRequest.model_validate({"criteria": {"make": "Toyota"}})

    def test_unknown_top_level_key_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CreateScheduledSearchRequest.model_validate(
                {"criteria": {"make": "Toyota"}, "interval_hours": 24, "foo": "bar"}
            )

    def test_client_controlled_attribution_and_state_rejected(self) -> None:
        forbidden = [
            "owner_site_user",
            "searched_by",
            "created_by",
            "actor",
            "schedule_id",
            "job_id",
            "id",
            "status",
            "version",
            "runs_count",
            "last_result_count",
            "next_run_at",
            "created_at",
        ]
        for key in forbidden:
            with self.subTest(key=key):
                payload = {
                    "criteria": {"make": "Toyota"},
                    "interval_hours": 24,
                    key: "x",
                }
                with self.assertRaises(ValidationError):
                    CreateScheduledSearchRequest.model_validate(payload)


class UpdateRequestTests(SafeCheckoutMixin):
    def test_valid_update_fixture_parses(self) -> None:
        req = UpdateScheduledSearchRequest.model_validate(load("update-request.valid.json"))
        self.assertEqual(req.interval_hours, 24)
        self.assertEqual(req.expected_version, 3)
        self.assertTrue(req.notifications.telegram_global)

    def test_update_requires_at_least_one_mutable_field(self) -> None:
        with self.assertRaises(ValidationError):
            UpdateScheduledSearchRequest.model_validate({"expected_version": 3})

    def test_update_requires_expected_version(self) -> None:
        with self.assertRaises(ValidationError):
            UpdateScheduledSearchRequest.model_validate({"interval_hours": 24})

    def test_update_interval_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            UpdateScheduledSearchRequest.model_validate(
                {"interval_hours": 200, "expected_version": 1}
            )

    def test_update_owner_override_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            UpdateScheduledSearchRequest.model_validate(
                {"interval_hours": 24, "expected_version": 1, "owner_site_user": "x"}
            )


class StateRequestTests(SafeCheckoutMixin):
    def test_valid_state_fixture_parses(self) -> None:
        req = SetScheduledSearchStateRequest.model_validate(load("state-request.valid.json"))
        self.assertFalse(req.enabled)
        self.assertEqual(req.expected_version, 4)

    def test_enabled_required(self) -> None:
        with self.assertRaises(ValidationError):
            SetScheduledSearchStateRequest.model_validate({"expected_version": 4})

    def test_enabled_non_bool_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SetScheduledSearchStateRequest.model_validate({"enabled": "yes"})

    def test_unknown_key_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SetScheduledSearchStateRequest.model_validate({"enabled": True, "status": "x"})


class ResponseModelTests(SafeCheckoutMixin):
    def test_schedule_envelope_fixture_parses(self) -> None:
        env = ScheduledSearchEnvelope.model_validate(load("schedule-envelope.success.json"))
        self.assertEqual(env.schedule.owner_site_user, "operator@example.com")
        self.assertEqual(env.schedule.last_result_count, 0)
        self.assertEqual(env.schedule.status, "enabled")
        self.assertEqual(env.limits.max_active, 20)

    def test_schedule_list_fixture_parses(self) -> None:
        listing = ScheduledSearchList.model_validate(load("schedule-list.success.json"))
        self.assertEqual(listing.count, 1)
        self.assertIn("operator@example.com", listing.limits_by_owner)

    def test_execution_history_fixture_parses(self) -> None:
        history = ScheduleExecutionList.model_validate(load("execution-history.success.json"))
        self.assertIsNone(history.next_cursor)
        succeeded = [e for e in history.executions if e.status == "succeeded"]
        self.assertTrue(succeeded)
        self.assertEqual(succeeded[0].result_count, 0)
        self.assertIsNotNone(succeeded[0].record_id)
        failed = [e for e in history.executions if e.status == "failed"]
        self.assertTrue(failed)
        self.assertIsNone(failed[0].record_id)
        self.assertTrue(failed[0].error.retryable)

    def test_capability_fixture_parses_and_matches_defaults(self) -> None:
        cap = ScheduledSearchCapability.model_validate(load("capability.available.json"))
        self.assertTrue(cap.available)
        self.assertFalse(cap.worker_enabled)
        self.assertEqual(cap.max_results, 100)
        self.assertEqual(cap.sources, list(ALLOWED_SOURCES))

    def test_public_error_fixtures_parse(self) -> None:
        errors = load("errors.public.json")
        validation = PublicErrorEnvelope.model_validate(errors["validation_error"])
        self.assertEqual(validation.error.code, "validation_error")
        self.assertIn("interval_hours", validation.error.fields)
        limit = PublicErrorEnvelope.model_validate(errors["active_limit_exceeded"])
        self.assertEqual(limit.error.code, "active_limit_exceeded")
        self.assertEqual(limit.error.active_count, 20)
        self.assertEqual(limit.error.limit, 20)


if __name__ == "__main__":
    unittest.main()
