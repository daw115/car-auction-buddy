"""Property-based test for the limit configuration domain (task 2.4).

Feature: scheduled-recurring-car-search, Property 12: Limit configuration
has an exact domain.
Validates Requirements 8.2, 8.3.

The property proves, over Hypothesis-generated inputs, that the
``MAX_ACTIVE_SCHEDULES`` configuration has an *exact* domain:

* absent (``None``) resolves to exactly ``20`` (Requirement 8.2);
* an explicit integer >= 1 -- as a genuine ``int`` or a canonical base-10
  string (with optional surrounding whitespace) -- resolves to that value
  (Requirement 8.3);
* every malformed / explicitly-invalid value (``0``, negatives, fractional,
  floats, booleans, non-numeric or empty strings, and other types) disables
  the capability and worker -- WITHOUT coercion and WITHOUT a silent default
  fallback to 20.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from api.scheduled_search_config import (
    DEFAULT_MAX_ACTIVE_SCHEDULES,
    IncompleteScheduleConfigurationError,
    resolve_max_active_schedules,
)
from tests.isolation_guard import assert_safe_test_checkout

ROOT = Path(__file__).resolve().parents[1]


# --- Strategies ------------------------------------------------------------
# Each strategy yields ``(raw_value, expected)`` where ``expected`` is either
# an ``int`` (valid -> that resolved value) or ``None`` (malformed -> disabled).


def absent_case() -> st.SearchStrategy[tuple[Any, Any]]:
    # Absent == variable not set. Resolves to the documented default.
    return st.just((None, DEFAULT_MAX_ACTIVE_SCHEDULES))


@st.composite
def valid_int_case(draw: st.DrawFn) -> tuple[Any, Any]:
    value = draw(st.integers(min_value=1, max_value=1_000_000))
    as_string = draw(st.booleans())
    if not as_string:
        return value, value
    # Canonical integer string, optionally surrounded by ASCII whitespace.
    lead = draw(st.sampled_from(["", " ", "  ", "\t"]))
    trail = draw(st.sampled_from(["", " ", "  ", "\t", "\n"]))
    return f"{lead}{value}{trail}", value


@st.composite
def malformed_case(draw: st.DrawFn) -> tuple[Any, Any]:
    kind = draw(
        st.sampled_from(
            [
                "zero",
                "negative_int",
                "negative_str",
                "float",
                "float_whole",
                "fractional_str",
                "bool",
                "empty_str",
                "whitespace_str",
                "non_numeric_str",
                "plus_prefixed_str",
                "underscore_str",
                "hex_str",
                "exponent_str",
                "trailing_junk_str",
                "other_type",
            ]
        )
    )
    if kind == "zero":
        return 0, None
    if kind == "negative_int":
        return draw(st.integers(max_value=0)) - 1, None
    if kind == "negative_str":
        return f"-{draw(st.integers(min_value=1, max_value=9999))}", None
    if kind == "float":
        return draw(st.sampled_from([1.5, 0.5, 23.9, 168.01])), None
    if kind == "float_whole":
        # No coercion: 5.0 is not an integer configuration value.
        return draw(st.sampled_from([1.0, 5.0, 20.0])), None
    if kind == "fractional_str":
        return draw(st.sampled_from(["1.5", "24.0", "0.5", "20.0"])), None
    if kind == "bool":
        return draw(st.booleans()), None
    if kind == "empty_str":
        return "", None
    if kind == "whitespace_str":
        return draw(st.sampled_from([" ", "   ", "\t", "\n", "  \t "])), None
    if kind == "non_numeric_str":
        return draw(st.sampled_from(["abc", "twenty", "NaN", "inf", "1o1"])), None
    if kind == "plus_prefixed_str":
        return f"+{draw(st.integers(min_value=1, max_value=9999))}", None
    if kind == "underscore_str":
        return draw(st.sampled_from(["1_000", "2_0", "1_2_3"])), None
    if kind == "hex_str":
        return draw(st.sampled_from(["0x10", "0b101", "0o17"])), None
    if kind == "exponent_str":
        return draw(st.sampled_from(["1e3", "2E2", "1.0e2"])), None
    if kind == "trailing_junk_str":
        return draw(st.sampled_from(["24abc", "20 30", "12,5", "5;"])), None
    # other_type
    return draw(st.sampled_from([[20], {"max": 20}, (1,), object()])), None


def config_case() -> st.SearchStrategy[tuple[Any, Any]]:
    return st.one_of(absent_case(), valid_int_case(), malformed_case())


class SafeCheckoutMixin(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert_safe_test_checkout(ROOT.parent)


class LimitConfigDomainPropertyTests(SafeCheckoutMixin):
    """Feature: scheduled-recurring-car-search, Property 12: Limit
    configuration has an exact domain."""

    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @given(case=config_case())
    @example(case=(None, DEFAULT_MAX_ACTIVE_SCHEDULES))  # absent -> 20
    @example(case=("20", 20))  # canonical string
    @example(case=(" 20 ", 20))  # surrounding whitespace tolerated
    @example(case=(1, 1))  # lower bound as int
    @example(case=("1", 1))  # lower bound as string
    @example(case=(0, None))  # zero rejected
    @example(case=(-5, None))  # negative rejected
    @example(case=("-5", None))  # negative string rejected
    @example(case=(1.5, None))  # fractional rejected
    @example(case=(5.0, None))  # whole float rejected (no coercion)
    @example(case=(True, None))  # bool rejected (not an int here)
    @example(case=(False, None))  # bool rejected
    @example(case=("", None))  # explicit empty rejected (not absent)
    @example(case=("abc", None))  # non-numeric rejected
    def test_limit_configuration_has_exact_domain(
        self, case: tuple[Any, Any]
    ) -> None:
        raw, expected = case
        result = resolve_max_active_schedules(raw)

        if expected is None:
            # Malformed / invalid explicit value:
            #  - capability + worker disabled,
            #  - NO coercion and NO silent default fallback to 20.
            self.assertFalse(result.is_valid, msg=f"raw={raw!r} should be invalid")
            self.assertFalse(result.capability_available)
            self.assertIsNone(result.max_active)
            self.assertEqual(result.source, "invalid")
            self.assertIsNotNone(result.error)
            self.assertEqual(result.error.code, "incomplete_configuration")
            with self.assertRaises(IncompleteScheduleConfigurationError):
                result.require()
        else:
            # Absent -> default 20; explicit integer >= 1 -> that exact value.
            self.assertTrue(result.is_valid, msg=f"raw={raw!r} should be valid")
            self.assertTrue(result.capability_available)
            self.assertEqual(result.max_active, expected)
            self.assertEqual(result.require(), expected)
            self.assertIn(result.source, ("default", "explicit"))
            if raw is None:
                self.assertEqual(result.source, "default")
                self.assertEqual(result.max_active, DEFAULT_MAX_ACTIVE_SCHEDULES)
            else:
                self.assertEqual(result.source, "explicit")


if __name__ == "__main__":
    unittest.main()
