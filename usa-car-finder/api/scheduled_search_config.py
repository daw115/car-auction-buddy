"""Exact-domain configuration parsing for the scheduled-search limit (v1).

Feature: scheduled-recurring-car-search, Property 12: Limit configuration
has an exact domain.
Validates Requirements 8.2, 8.3.

The ``MAX_ACTIVE_SCHEDULES`` configuration has an *exact* domain with no
coercion and no silent default fallback:

* Absent (the environment variable is not set at all -> ``None``) resolves to
  the documented default of ``20`` active schedules per owner (Requirement 8.2).
* An explicit value is accepted *only* when it denotes an integer greater than
  or equal to ``1`` (Requirement 8.3). A canonical base-10 integer string
  (optionally surrounded by whitespace) or a genuine ``int`` object counts.
* Every other explicit value -- ``0``, negatives, fractional/float values,
  booleans, non-numeric or empty strings, and any non-integer type -- is
  malformed. A malformed value never coerces and never silently defaults to
  ``20``; instead it marks the capability/worker as unavailable so the
  scheduled-search API and the worker stay disabled until the operator fixes
  the configuration.

This module is a pure resolver plus a thin environment reader. It performs no
persistence and no I/O beyond reading the provided mapping, so it is safe to
exercise under property tests.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from api.scheduled_search_models import PublicErrorDetail

# --- Contract constants ----------------------------------------------------
ENV_VAR_NAME = "MAX_ACTIVE_SCHEDULES"
DEFAULT_MAX_ACTIVE_SCHEDULES = 20
MIN_MAX_ACTIVE_SCHEDULES = 1

# A canonical, strict base-10 non-negative-or-negative integer literal. The
# leading optional minus lets us classify negatives as *malformed integers*
# (rejected by the >= 1 rule) rather than as unparseable strings. Underscores,
# plus signs, unicode digits, exponents and radix prefixes are intentionally
# rejected so the domain stays exact.
_INT_LITERAL = re.compile(r"^-?[0-9]+$")


class IncompleteScheduleConfigurationError(RuntimeError):
    """Raised when an explicit limit configuration is outside the exact domain.

    The scheduled-search capability and worker must stay disabled while this
    condition holds; the error is never swallowed into a silent default.
    """

    def __init__(self, detail: "PublicErrorDetail") -> None:
        super().__init__(detail.message)
        self.detail = detail


@dataclass(frozen=True)
class MaxActiveSchedulesConfig:
    """Resolved outcome for the ``MAX_ACTIVE_SCHEDULES`` configuration.

    ``max_active`` is ``None`` exactly when the explicit value was malformed.
    In that state the capability/worker must be treated as unavailable.
    """

    max_active: Optional[int]
    source: str  # one of: "default", "explicit", "invalid"
    error: Optional["PublicErrorDetail"] = None

    @property
    def is_valid(self) -> bool:
        return self.max_active is not None

    @property
    def capability_available(self) -> bool:
        """Whether the scheduled-search capability/worker may be enabled."""
        return self.is_valid

    def require(self) -> int:
        """Return the resolved limit or raise when the configuration is invalid."""
        if self.max_active is None:
            assert self.error is not None  # invariant: invalid => error present
            raise IncompleteScheduleConfigurationError(self.error)
        return self.max_active


def _invalid(reason: str) -> MaxActiveSchedulesConfig:
    detail = PublicErrorDetail(
        code="incomplete_configuration",
        message=(
            "Nieprawidlowa konfiguracja limitu aktywnych zaplanowanych "
            "wyszukiwan; wymagana liczba calkowita >= 1."
        ),
        fields={ENV_VAR_NAME: reason},
    )
    return MaxActiveSchedulesConfig(max_active=None, source="invalid", error=detail)


def resolve_max_active_schedules(raw: Any) -> MaxActiveSchedulesConfig:
    """Resolve the exact domain of the limit configuration.

    ``raw`` is the explicit configuration value, or ``None`` when the setting
    is absent from the environment.
    """
    # 1. Absent -> documented default (Requirement 8.2). Only a true ``None``
    #    (variable not present) counts as absent.
    if raw is None:
        return MaxActiveSchedulesConfig(
            max_active=DEFAULT_MAX_ACTIVE_SCHEDULES, source="default"
        )

    # 2. Booleans are NOT integers here even though ``bool`` subclasses ``int``.
    if isinstance(raw, bool):
        return _invalid("wartosc logiczna nie jest liczba calkowita")

    # 3. A genuine integer object is accepted iff it is >= 1 (no coercion).
    if isinstance(raw, int):
        if raw >= MIN_MAX_ACTIVE_SCHEDULES:
            return MaxActiveSchedulesConfig(max_active=raw, source="explicit")
        return _invalid("liczba calkowita musi byc >= 1")

    # 4. A string is accepted iff it is a canonical integer literal >= 1.
    if isinstance(raw, str):
        candidate = raw.strip()
        if not _INT_LITERAL.match(candidate):
            return _invalid("wartosc nie jest liczba calkowita")
        value = int(candidate)
        if value >= MIN_MAX_ACTIVE_SCHEDULES:
            return MaxActiveSchedulesConfig(max_active=value, source="explicit")
        return _invalid("liczba calkowita musi byc >= 1")

    # 5. Any other type (float, list, etc.) is malformed. Notably a ``float``
    #    such as ``5.0`` is rejected: the domain is exact, with no coercion.
    return _invalid("nieobslugiwany typ wartosci konfiguracji")


def read_max_active_schedules_config(
    environ: Optional[Mapping[str, str]] = None,
) -> MaxActiveSchedulesConfig:
    """Read and resolve the limit configuration from an environment mapping.

    Uses ``os.environ`` by default. Absent variable -> default; present value
    is parsed exactly by :func:`resolve_max_active_schedules`.
    """
    env = os.environ if environ is None else environ
    return resolve_max_active_schedules(env.get(ENV_VAR_NAME))


__all__ = [
    "ENV_VAR_NAME",
    "DEFAULT_MAX_ACTIVE_SCHEDULES",
    "MIN_MAX_ACTIVE_SCHEDULES",
    "IncompleteScheduleConfigurationError",
    "MaxActiveSchedulesConfig",
    "resolve_max_active_schedules",
    "read_max_active_schedules_config",
]
