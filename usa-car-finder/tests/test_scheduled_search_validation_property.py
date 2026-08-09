"""Property-based test for scheduled-search create validation (task 2.3).

Feature: scheduled-recurring-car-search, Property 1: Strict validation, atomic
rejection and precedence.

Validates Requirements 1.2, 1.5, 2.3, 5.1, 5.2.

The property proves three things at once, over Hypothesis-generated inputs
(interval boundaries 0/1/168/169, bool-vs-int, fractional, missing, unknown
keys, Unicode/whitespace makes, unsupported sources, invalid max_results,
and simultaneous validation+limit violations):

* interval_hours is accepted iff it is a non-boolean integer in [1, 168] AND
  the criteria satisfy the strict schema (and no unknown/attribution key is
  present);
* every rejected input leaves persistence unchanged (atomic rejection);
* after authentication, validation is evaluated before the active limit, so a
  request that violates both validation and the limit is rejected as a
  validation error (precedence).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from api.scheduled_search_models import (
    ALLOWED_SOURCES,
    INTERVAL_HOURS_MAX,
    INTERVAL_HOURS_MIN,
    CreateScheduledSearchRequest,
)
from api.scheduled_search_validation import (
    CreateAccepted,
    CreateRejected,
    create_precheck,
)
from tests.isolation_guard import assert_safe_test_checkout

ROOT = Path(__file__).resolve().parents[1]
ACTOR = "operator@example.com"
MAX_ACTIVE = 20

# --- Forbidden / unknown top-level keys ------------------------------------
FORBIDDEN_TOP_KEYS = (
    "owner_site_user",
    "searched_by",
    "created_by",
    "schedule_id",
    "job_id",
    "id",
    "status",
    "version",
    "runs_count",
    "next_run_at",
    "__unknown__",
)


# --- Criteria strategies ---------------------------------------------------
_VALID_MAKES = (
    "Toyota",
    "BMW",
    "Škoda",       # Unicode
    "日産",          # Unicode
    "  Ford  ",     # surrounding whitespace, non-empty after strip
    "Mercedes-Benz",
)


@st.composite
def valid_criteria(draw: st.DrawFn) -> dict[str, Any]:
    crit: dict[str, Any] = {"make": draw(st.sampled_from(_VALID_MAKES))}
    if draw(st.booleans()):
        yf = draw(st.integers(min_value=1900, max_value=2100))
        yt = draw(st.integers(min_value=yf, max_value=2100))
        crit["year_from"] = yf
        crit["year_to"] = yt
    if draw(st.booleans()):
        crit["max_results"] = draw(st.integers(min_value=1, max_value=100))
    if draw(st.booleans()):
        crit["sources"] = draw(
            st.lists(
                st.sampled_from(list(ALLOWED_SOURCES)),
                min_size=1,
                max_size=len(ALLOWED_SOURCES),
                unique=True,
            )
        )
    if draw(st.booleans()):
        crit["fuel_type"] = draw(
            st.sampled_from(["Gas", "Hybrid", "Diesel", "Electric"])
        )
    return crit


@st.composite
def invalid_criteria(draw: st.DrawFn) -> dict[str, Any]:
    """A base valid criteria dict with exactly one guaranteed violation."""
    crit: dict[str, Any] = {"make": "Toyota"}
    kind = draw(
        st.sampled_from(
            [
                "missing_make",
                "blank_make",
                "whitespace_make",
                "make_wrong_type",
                "unsupported_source",
                "empty_sources",
                "too_many_sources",
                "max_results_zero",
                "max_results_over",
                "max_results_fractional",
                "max_results_bool",
                "year_inverted",
                "year_out_of_range",
                "unknown_criteria_key",
            ]
        )
    )
    if kind == "missing_make":
        crit.pop("make")
    elif kind == "blank_make":
        crit["make"] = ""
    elif kind == "whitespace_make":
        crit["make"] = "   "
    elif kind == "make_wrong_type":
        crit["make"] = draw(st.integers())
    elif kind == "unsupported_source":
        crit["sources"] = ["copart", "ebay"]
    elif kind == "empty_sources":
        crit["sources"] = []
    elif kind == "too_many_sources":
        crit["sources"] = ["copart", "iaai", "manheim", "copart"]
    elif kind == "max_results_zero":
        crit["max_results"] = 0
    elif kind == "max_results_over":
        crit["max_results"] = draw(st.integers(min_value=101, max_value=10_000))
    elif kind == "max_results_fractional":
        crit["max_results"] = 1.5
    elif kind == "max_results_bool":
        crit["max_results"] = draw(st.booleans())
    elif kind == "year_inverted":
        crit["year_from"] = 2020
        crit["year_to"] = 2000
    elif kind == "year_out_of_range":
        crit["year_from"] = draw(st.sampled_from([1800, 2200, 0]))
    elif kind == "unknown_criteria_key":
        crit["__nope__"] = "x"
    return crit


# --- Interval strategies ---------------------------------------------------
def valid_interval() -> st.SearchStrategy[int]:
    return st.integers(min_value=INTERVAL_HOURS_MIN, max_value=INTERVAL_HOURS_MAX)


def invalid_interval() -> st.SearchStrategy[Any]:
    return st.one_of(
        st.sampled_from([0, 169, -1, -100, 200, 1000, 100000]),  # out of range
        st.booleans(),                                           # bool-vs-int
        st.sampled_from([1.5, 24.0, 0.5, 168.0]),                # fractional / float
        st.sampled_from(["24", "abc", ""]),                     # wrong type
        st.none(),                                               # explicit null
    )


# --- Full request case -----------------------------------------------------
@st.composite
def create_case(draw: st.DrawFn) -> tuple[dict[str, Any], bool]:
    """Build a payload and its independently-computed expected validity."""
    criteria_valid = draw(st.booleans())
    criteria = draw(valid_criteria() if criteria_valid else invalid_criteria())

    interval_valid = draw(st.booleans())
    include_interval = True
    payload: dict[str, Any] = {"criteria": criteria}

    if interval_valid:
        payload["interval_hours"] = draw(valid_interval())
    else:
        iv = draw(invalid_interval())
        if iv is None and draw(st.booleans()):
            # 'missing' variant: omit the required key entirely.
            include_interval = False
        else:
            payload["interval_hours"] = iv
    if not include_interval:
        payload.pop("interval_hours", None)

    # Optional valid label (never a source of invalidity here).
    if draw(st.booleans()):
        payload["label"] = draw(st.sampled_from(["My watch", "Škoda daily", "  x  "]))

    # Optionally inject an unknown/attribution top-level key -> always invalid.
    inject_bad_key = draw(st.booleans())
    if inject_bad_key:
        payload[draw(st.sampled_from(FORBIDDEN_TOP_KEYS))] = "tampered"

    interval_ok = interval_valid and include_interval
    expected_valid = criteria_valid and interval_ok and not inject_bad_key
    return payload, expected_valid


class SafeCheckoutMixin(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert_safe_test_checkout(ROOT.parent)


class StrictValidationPropertyTests(SafeCheckoutMixin):
    """Feature: scheduled-recurring-car-search, Property 1: Strict validation,
    atomic rejection and precedence."""

    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @given(case=create_case(), at_limit=st.booleans())
    @example(  # interval boundary 0 (rejected) while at limit -> precedence
        case=({"criteria": {"make": "Toyota"}, "interval_hours": 0}, False),
        at_limit=True,
    )
    @example(  # interval boundary 1 (accepted)
        case=({"criteria": {"make": "Toyota"}, "interval_hours": 1}, True),
        at_limit=False,
    )
    @example(  # interval boundary 168 (accepted)
        case=({"criteria": {"make": "Toyota"}, "interval_hours": 168}, True),
        at_limit=False,
    )
    @example(  # interval boundary 169 (rejected)
        case=({"criteria": {"make": "Toyota"}, "interval_hours": 169}, False),
        at_limit=False,
    )
    @example(  # bool-vs-int: True must NOT be accepted as 1
        case=({"criteria": {"make": "Toyota"}, "interval_hours": True}, False),
        at_limit=False,
    )
    @example(  # fractional interval
        case=({"criteria": {"make": "Toyota"}, "interval_hours": 1.5}, False),
        at_limit=False,
    )
    @example(  # missing interval
        case=({"criteria": {"make": "Toyota"}}, False),
        at_limit=False,
    )
    @example(  # valid at limit -> limit error (not validation)
        case=({"criteria": {"make": "Toyota"}, "interval_hours": 24}, True),
        at_limit=True,
    )
    def test_strict_validation_atomic_rejection_and_precedence(
        self, case: tuple[dict[str, Any], bool], at_limit: bool
    ) -> None:
        payload, expected_valid = case

        # (a) The strict model accepts iff our independent oracle says so.
        model_ok = _model_accepts(payload)
        self.assertEqual(
            model_ok,
            expected_valid,
            msg=f"schema acceptance disagreed with oracle for payload={payload}",
        )

        # Model a persistence store: existing active rows for this owner.
        active_count = MAX_ACTIVE if at_limit else 0
        store = list(range(active_count))
        before = list(store)

        outcome = create_precheck(
            payload,
            actor_site_user=ACTOR,
            active_count=active_count,
            max_active=MAX_ACTIVE,
        )

        # Caller persists ONLY on acceptance.
        if isinstance(outcome, CreateAccepted):
            store.append(outcome)

        if not expected_valid:
            # Precedence: validation is evaluated before the limit, so even at
            # the limit an invalid payload is a validation_error.
            self.assertIsInstance(outcome, CreateRejected)
            self.assertEqual(outcome.error.code, "validation_error")
            # Atomic rejection: persistence unchanged.
            self.assertEqual(store, before)
        elif at_limit:
            # Valid payload but limit reached -> limit error, nothing persisted.
            self.assertIsInstance(outcome, CreateRejected)
            self.assertEqual(outcome.error.code, "active_limit_exceeded")
            self.assertEqual(outcome.error.active_count, active_count)
            self.assertEqual(outcome.error.limit, MAX_ACTIVE)
            self.assertEqual(store, before)
        else:
            # Valid and under limit -> accepted, owner from trusted actor.
            self.assertIsInstance(outcome, CreateAccepted)
            self.assertEqual(outcome.owner_site_user, ACTOR)
            self.assertEqual(outcome.request.interval_hours, payload["interval_hours"])
            self.assertEqual(len(store), active_count + 1)


def _model_accepts(payload: dict[str, Any]) -> bool:
    try:
        CreateScheduledSearchRequest.model_validate(payload)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    unittest.main()
