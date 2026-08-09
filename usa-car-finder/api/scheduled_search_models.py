"""Strict domain models for the scheduled recurring search feature (v1).

These Pydantic v2 models define the *additive*, versioned contract exposed under
``/api/queue/schedules`` (see ``.kiro/specs/scheduled-recurring-car-search``).

Design rules encoded here (Requirements 1.1, 1.2, 2.1, 2.3, 5.1, 5.2, 7.3, 10.5, 11.3):

* Requests are ``extra="forbid"`` — unknown keys are rejected (422), never stripped.
* Client-controlled attribution/state is impossible: ``owner_site_user``, ``searched_by``,
  ``created_by``, ``schedule_id``, ``job_id``, ``id``, ``status``, ``version`` and any
  counter/timestamp field are not declared on mutable request models, so ``extra="forbid"``
  rejects them.
* The ONLY normalized defaults are: absent ``sources`` -> ``["copart", "iaai"]`` and absent
  notifications -> ``telegram_global=False``.
* ``interval_hours`` (1..168), ``max_results`` (1..100) and ``sources`` are validated and
  *rejected* when out of range / unsupported. They are never clamped or silently corrected.

This module intentionally does NOT reuse ``parser.models.ClientCriteria`` because that legacy
model clamps ``max_results`` to 15 and only accepts ``copart``/``iaai`` — the v1 contract must
support ``max_results`` up to 100 and three sources without clamping.
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

# --- Contract constants -----------------------------------------------------

CONTRACT_NAME = "scheduled_searches_v1"
CONTRACT_VERSION = 1
CRITERIA_CONTRACT_VERSION = 1
BASE_PATH = "/api/queue/schedules"

INTERVAL_HOURS_MIN = 1
INTERVAL_HOURS_MAX = 168
MAX_RESULTS_MIN = 1
MAX_RESULTS_MAX = 100

ALLOWED_SOURCES: tuple[str, ...] = ("copart", "iaai", "manheim")
DEFAULT_SOURCES: list[str] = ["copart", "iaai"]

LABEL_MAX_LEN = 200
MODEL_MAX_LEN = 80
MAKE_MAX_LEN = 80
DAMAGE_TYPE_MAX_LEN = 40
DAMAGE_TYPES_MAX_ITEMS = 20
YEAR_MIN = 1900
YEAR_MAX = 2100
BUDGET_MAX = 1_000_000
ODOMETER_MAX = 1_000_000

FuelType = Literal["Gas", "Hybrid", "Diesel", "Electric"]

ScheduledSearchStatus = Literal["enabled", "disabled"]
LastExecutionStatus = Literal[
    "never", "queued", "running", "retry_wait", "succeeded", "failed"
]
ScheduleExecutionStatus = Literal[
    "queued", "running", "retry_wait", "succeeded", "failed"
]
NotificationStatus = Literal["not_requested", "pending", "sent", "failed"]

ErrorCode = Literal[
    "validation_error",
    "active_limit_exceeded",
    "not_found",
    "version_conflict",
    "store_busy",
    "backend_unavailable",
    "incomplete_configuration",
    "unauthorized",
    "forbidden",
    "capability_unavailable",
    "internal_error",
]


# --- Criteria ---------------------------------------------------------------


class ScheduledSearchCriteria(BaseModel):
    """Search criteria for a scheduled search.

    Mirrors the GUI ``criteriaSchema`` domain but forbids ``searched_by`` and any unknown
    key. ``sources`` is normalized to the default pair when omitted; nothing else is coerced.
    """

    model_config = ConfigDict(extra="forbid")

    make: StrictStr = Field(min_length=1, max_length=MAKE_MAX_LEN)
    model: Optional[StrictStr] = Field(default=None, max_length=MODEL_MAX_LEN)
    year_from: Optional[StrictInt] = Field(default=None, ge=YEAR_MIN, le=YEAR_MAX)
    year_to: Optional[StrictInt] = Field(default=None, ge=YEAR_MIN, le=YEAR_MAX)
    budget_usd: Optional[Union[StrictInt, StrictFloat]] = Field(
        default=None, ge=0, le=BUDGET_MAX
    )
    max_odometer_mi: Optional[StrictInt] = Field(default=None, ge=0, le=ODOMETER_MAX)
    fuel_type: Optional[FuelType] = None
    excluded_damage_types: list[StrictStr] = Field(default_factory=list)
    max_results: Optional[StrictInt] = Field(
        default=None, ge=MAX_RESULTS_MIN, le=MAX_RESULTS_MAX
    )
    sources: Optional[list[StrictStr]] = Field(default=None, validate_default=True)

    @field_validator("make")
    @classmethod
    def _make_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Marka jest wymagana.")
        if len(stripped) > MAKE_MAX_LEN:
            raise ValueError(f"Marka może mieć maksymalnie {MAKE_MAX_LEN} znaków.")
        return stripped

    @field_validator("excluded_damage_types")
    @classmethod
    def _validate_damage_types(cls, value: list[str]) -> list[str]:
        if len(value) > DAMAGE_TYPES_MAX_ITEMS:
            raise ValueError(
                f"Maksymalnie {DAMAGE_TYPES_MAX_ITEMS} typów uszkodzeń."
            )
        for item in value:
            if len(item) > DAMAGE_TYPE_MAX_LEN:
                raise ValueError(
                    f"Typ uszkodzenia może mieć maksymalnie {DAMAGE_TYPE_MAX_LEN} znaków."
                )
        return value

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, value: Optional[list[str]]) -> list[str]:
        # Normalize the only explicit default: absent/empty -> default pair.
        if value is None:
            return list(DEFAULT_SOURCES)
        normalized = [item.lower() for item in value]
        if not normalized:
            raise ValueError(
                "sources musi zawierać co najmniej jedno z: copart, iaai, manheim."
            )
        if len(normalized) > len(ALLOWED_SOURCES):
            raise ValueError("sources może zawierać maksymalnie trzy źródła.")
        invalid = [item for item in normalized if item not in ALLOWED_SOURCES]
        if invalid:
            raise ValueError(
                "Nieobsługiwane źródła: "
                + ", ".join(sorted(set(invalid)))
                + ". Dozwolone: copart, iaai, manheim."
            )
        return normalized

    @model_validator(mode="after")
    def _validate_ranges(self) -> "ScheduledSearchCriteria":
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("Rocznik 'od' nie może być większy niż rocznik 'do'.")
        return self


# --- Notifications ----------------------------------------------------------


class NotificationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telegram_global: StrictBool = False


def _default_notifications() -> NotificationSettings:
    return NotificationSettings(telegram_global=False)


# --- Requests ---------------------------------------------------------------


class CreateScheduledSearchRequest(BaseModel):
    """POST /api/queue/schedules body."""

    model_config = ConfigDict(extra="forbid")

    label: Optional[StrictStr] = Field(default=None, max_length=LABEL_MAX_LEN)
    criteria: ScheduledSearchCriteria
    interval_hours: StrictInt = Field(ge=INTERVAL_HOURS_MIN, le=INTERVAL_HOURS_MAX)
    notifications: NotificationSettings = Field(default_factory=_default_notifications)

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        if len(trimmed) > LABEL_MAX_LEN:
            raise ValueError(f"Etykieta może mieć maksymalnie {LABEL_MAX_LEN} znaków.")
        return trimmed


class UpdateScheduledSearchRequest(BaseModel):
    """PATCH /api/queue/schedules/{id} body — at least one mutable field required."""

    model_config = ConfigDict(extra="forbid")

    label: Optional[StrictStr] = Field(default=None, max_length=LABEL_MAX_LEN)
    criteria: Optional[ScheduledSearchCriteria] = None
    interval_hours: Optional[StrictInt] = Field(
        default=None, ge=INTERVAL_HOURS_MIN, le=INTERVAL_HOURS_MAX
    )
    notifications: Optional[NotificationSettings] = None
    expected_version: StrictInt = Field(ge=1)

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Etykieta nie może być pusta.")
        if len(trimmed) > LABEL_MAX_LEN:
            raise ValueError(f"Etykieta może mieć maksymalnie {LABEL_MAX_LEN} znaków.")
        return trimmed

    @model_validator(mode="after")
    def _require_mutable_field(self) -> "UpdateScheduledSearchRequest":
        if (
            self.label is None
            and self.criteria is None
            and self.interval_hours is None
            and self.notifications is None
        ):
            raise ValueError(
                "Żądanie edycji musi zawierać co najmniej jedno pole do zmiany."
            )
        return self


class SetScheduledSearchStateRequest(BaseModel):
    """PUT /api/queue/schedules/{id}/state body."""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    expected_version: Optional[StrictInt] = Field(default=None, ge=1)


# --- Responses --------------------------------------------------------------


class PublicErrorDetail(BaseModel):
    code: ErrorCode
    message: StrictStr
    fields: Optional[dict[str, str]] = None
    active_count: Optional[int] = None
    limit: Optional[int] = None
    request_id: Optional[str] = None


class PublicErrorEnvelope(BaseModel):
    error: PublicErrorDetail


class ScheduleLimits(BaseModel):
    active_count: int
    max_active: int


class ScheduledSearchErrorInfo(BaseModel):
    code: StrictStr
    message: StrictStr


class ScheduledSearch(BaseModel):
    id: int
    label: str
    criteria: ScheduledSearchCriteria
    interval_hours: int
    status: ScheduledSearchStatus
    owner_site_user: str
    notifications: NotificationSettings
    next_run_at: str
    last_run_at: Optional[str] = None
    runs_count: int
    last_result_count: Optional[int] = None
    last_execution_status: LastExecutionStatus
    last_error: Optional[ScheduledSearchErrorInfo] = None
    in_flight_execution_id: Optional[str] = None
    created_at: str
    updated_at: str
    version: int


class ScheduledSearchEnvelope(BaseModel):
    schedule: ScheduledSearch
    limits: ScheduleLimits


class ScheduledSearchList(BaseModel):
    schedules: list[ScheduledSearch]
    count: int
    limits_by_owner: dict[str, ScheduleLimits]


class ScheduleExecutionError(BaseModel):
    code: StrictStr
    message: StrictStr
    retryable: bool


class ScheduleExecution(BaseModel):
    id: str
    schedule_id: int
    owner_site_user: str
    scheduled_for: str
    criteria_snapshot: ScheduledSearchCriteria
    interval_hours_snapshot: int
    status: ScheduleExecutionStatus
    attempt_count: int
    job_id: Optional[str] = None
    record_id: Optional[int] = None
    result_count: Optional[int] = None
    error: Optional[ScheduleExecutionError] = None
    notification_status: NotificationStatus
    notification_attempts: int
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_at: str


class ScheduleExecutionList(BaseModel):
    executions: list[ScheduleExecution]
    next_cursor: Optional[str] = None


class ScheduledSearchCapability(BaseModel):
    capability: str = CONTRACT_NAME
    available: bool
    contract_version: int = CONTRACT_VERSION
    criteria_contract_version: int = CRITERIA_CONTRACT_VERSION
    max_results: int = MAX_RESULTS_MAX
    sources: list[str] = Field(default_factory=lambda: list(ALLOWED_SOURCES))
    worker_enabled: bool = False


__all__ = [
    "CONTRACT_NAME",
    "CONTRACT_VERSION",
    "CRITERIA_CONTRACT_VERSION",
    "BASE_PATH",
    "INTERVAL_HOURS_MIN",
    "INTERVAL_HOURS_MAX",
    "MAX_RESULTS_MIN",
    "MAX_RESULTS_MAX",
    "ALLOWED_SOURCES",
    "DEFAULT_SOURCES",
    "FuelType",
    "ScheduledSearchStatus",
    "LastExecutionStatus",
    "ScheduleExecutionStatus",
    "NotificationStatus",
    "ErrorCode",
    "ScheduledSearchCriteria",
    "NotificationSettings",
    "CreateScheduledSearchRequest",
    "UpdateScheduledSearchRequest",
    "SetScheduledSearchStateRequest",
    "PublicErrorDetail",
    "PublicErrorEnvelope",
    "ScheduleLimits",
    "ScheduledSearch",
    "ScheduledSearchEnvelope",
    "ScheduledSearchList",
    "ScheduleExecution",
    "ScheduleExecutionList",
    "ScheduledSearchCapability",
]
