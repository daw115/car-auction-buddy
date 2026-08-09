"""Management service layer for scheduled recurring searches (v1).

Sits between API routes (task 4.1) and the repository (task 3.1),
orchestrating:

1. Strict validation (models 2.1 + scheduled_search_validation 2.3) BEFORE
   any limit transaction — precedence: validation > limit > persist.
2. Trusted owner derivation — owner_site_user comes exclusively from the
   actor_site_user parameter (never from the client payload). On create:
   owner = actor. On edit/toggle/delete: actor != owner is allowed (global
   operator list) but the owner is immutable; actor stored as updated_by.
3. Exact limit policy — resolve_max_active_schedules from 2.4; invalid
   config raises IncompleteScheduleConfigurationError; exceeded raises
   ActiveLimitExceededError with active_count and limit.
4. Sanitized outcome mapping — results mapped to PublicErrorEnvelope /
   ScheduledSearchEnvelope / ScheduledSearchList from models 2.1. Never
   expose DB path, SQL, stack, token, or raw exception message.

Requirements: 1.1, 1.4, 1.5, 2.1, 2.2, 2.3, 4.4, 4.5, 5.2, 6.1, 8.1, 8.4, 8.5, 11.3
"""

from __future__ import annotations

import sqlite3
import traceback
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from pydantic import ValidationError

from api.schedule_repository import (
    ActiveLimitExceededError,
    EmptyPatchError,
    ScheduleNotFoundError,
    VersionConflictError,
    count_active_for_owner,
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    set_schedule_enabled,
    update_schedule,
)
from api.scheduled_search_config import (
    IncompleteScheduleConfigurationError,
    MaxActiveSchedulesConfig,
    read_max_active_schedules_config,
    resolve_max_active_schedules,
)
from api.scheduled_search_models import (
    CreateScheduledSearchRequest,
    PublicErrorDetail,
    PublicErrorEnvelope,
    ScheduledSearchEnvelope,
    ScheduledSearchList,
    ScheduleLimits,
    SetScheduledSearchStateRequest,
    UpdateScheduledSearchRequest,
)
from api.scheduled_search_validation import (
    CreateAccepted,
    CreateRejected,
    create_precheck,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection to the schedule database."""
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _resolve_limit(
    environ: Optional[Mapping[str, str]] = None,
) -> int:
    """Resolve the max active schedules limit.

    Raises IncompleteScheduleConfigurationError if the explicit config is
    malformed (invalid value blocks capability/worker).
    """
    config = read_max_active_schedules_config(environ)
    return config.require()


def _sanitized_error(
    code: str,
    message: str,
    *,
    fields: Optional[dict[str, str]] = None,
    active_count: Optional[int] = None,
    limit: Optional[int] = None,
) -> PublicErrorEnvelope:
    """Build a sanitized error envelope — never leaks internals."""
    return PublicErrorEnvelope(
        error=PublicErrorDetail(
            code=code,
            message=message,
            fields=fields,
            active_count=active_count,
            limit=limit,
        )
    )


def _validation_error_from_exc(exc: ValidationError) -> PublicErrorEnvelope:
    """Map a Pydantic ValidationError to a sanitized error envelope."""
    fields: dict[str, str] = {}
    for err in exc.errors():
        loc = err.get("loc", ())
        key = ".".join(str(part) for part in loc) or "__root__"
        fields.setdefault(key, str(err.get("msg", "Nieprawidlowa wartosc.")))
    return _sanitized_error(
        code="validation_error",
        message="Nieprawidlowe dane wejsciowe zaplanowanego wyszukiwania.",
        fields=fields or None,
    )


# ---------------------------------------------------------------------------
# Public service methods
# ---------------------------------------------------------------------------


def create_scheduled_search(
    *,
    db_path: str,
    actor_site_user: str,
    payload: Mapping[str, Any],
    environ: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
) -> ScheduledSearchEnvelope:
    """Create a new scheduled search.

    Ordering contract: validation > limit > persist.
    Owner is derived exclusively from actor_site_user.

    Raises:
        IncompleteScheduleConfigurationError: invalid limit config.
        ActiveLimitExceededError: owner at or above active limit.
        ValidationError/CreateRejected path: re-raised as domain errors.
    """
    max_active = _resolve_limit(environ)

    # Open connection to get active count for precheck
    conn = _connect(db_path)
    try:
        active_count = count_active_for_owner(conn, actor_site_user)

        # Validation-first precheck (precedence: validation > limit > persist)
        outcome = create_precheck(
            payload,
            actor_site_user=actor_site_user,
            active_count=active_count,
            max_active=max_active,
        )

        if isinstance(outcome, CreateRejected):
            # Re-raise as domain error depending on code
            detail = outcome.error
            if detail.code == "active_limit_exceeded":
                raise ActiveLimitExceededError(
                    detail.active_count or active_count,
                    detail.limit or max_active,
                )
            # Validation error — raise with the detail
            raise ScheduleValidationError(detail)

        # CreateAccepted — proceed to persist
        accepted: CreateAccepted = outcome
        request = accepted.request

        envelope = create_schedule(
            conn,
            criteria=request.criteria,
            interval_hours=request.interval_hours,
            owner=actor_site_user,
            label=request.label,
            notifications=request.notifications,
            now=now,
            max_active=max_active,
        )
        return envelope
    finally:
        conn.close()


def update_scheduled_search(
    *,
    db_path: str,
    actor_site_user: str,
    schedule_id: int,
    payload: Mapping[str, Any],
    environ: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
) -> ScheduledSearchEnvelope:
    """Update an existing scheduled search.

    Strict validation before repository call. Owner is immutable;
    actor is recorded as updated_by_site_user.

    Raises:
        IncompleteScheduleConfigurationError: invalid limit config.
        ScheduleNotFoundError: schedule does not exist or is deleted.
        VersionConflictError: optimistic locking failure.
        EmptyPatchError: no mutable fields provided.
        ScheduleValidationError: payload fails strict validation.
    """
    max_active = _resolve_limit(environ)

    # Strict validation via Pydantic model BEFORE any DB operation
    try:
        request = UpdateScheduledSearchRequest.model_validate(payload)
    except ValidationError as exc:
        raise ScheduleValidationError(_validation_error_from_exc(exc).error)

    # Build patch dict from validated request
    patch: dict[str, Any] = {}
    if request.label is not None:
        patch["label"] = request.label
    if request.criteria is not None:
        patch["criteria"] = request.criteria
    if request.interval_hours is not None:
        patch["interval_hours"] = request.interval_hours
    if request.notifications is not None:
        patch["notifications"] = request.notifications

    conn = _connect(db_path)
    try:
        envelope = update_schedule(
            conn,
            schedule_id=schedule_id,
            patch=patch,
            expected_version=request.expected_version,
            actor=actor_site_user,
            now=now,
            max_active=max_active,
        )
        return envelope
    finally:
        conn.close()


def set_scheduled_search_enabled(
    *,
    db_path: str,
    actor_site_user: str,
    schedule_id: int,
    payload: Mapping[str, Any],
    environ: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
) -> ScheduledSearchEnvelope:
    """Toggle enabled/disabled state for a scheduled search.

    Strict validation before repository. Limit check on disable->enable only.

    Raises:
        IncompleteScheduleConfigurationError: invalid limit config.
        ScheduleNotFoundError: schedule does not exist or is deleted.
        VersionConflictError: optimistic locking mismatch.
        ActiveLimitExceededError: re-enabling would exceed limit.
        ScheduleValidationError: payload fails strict validation.
    """
    max_active = _resolve_limit(environ)

    # Strict validation
    try:
        request = SetScheduledSearchStateRequest.model_validate(payload)
    except ValidationError as exc:
        raise ScheduleValidationError(_validation_error_from_exc(exc).error)

    expected_version = request.expected_version
    if expected_version is None:
        # If not provided, we need to read current version
        # The repository will handle version check internally
        # We pass a sentinel that the repo interprets
        # Actually, the repo requires expected_version — read it
        conn = _connect(db_path)
        try:
            # Read current version
            row = conn.execute(
                "SELECT version FROM watch_entries WHERE id = ? "
                "AND schedule_kind = ? AND deleted_at IS NULL",
                (schedule_id, "scheduled_recurring_v1"),
            ).fetchone()
            if row is None:
                raise ScheduleNotFoundError()
            expected_version = row["version"]
        finally:
            conn.close()

    conn = _connect(db_path)
    try:
        envelope = set_schedule_enabled(
            conn,
            schedule_id=schedule_id,
            enabled=request.enabled,
            expected_version=expected_version,
            actor=actor_site_user,
            now=now,
            max_active=max_active,
        )
        return envelope
    finally:
        conn.close()


def delete_scheduled_search(
    *,
    db_path: str,
    actor_site_user: str,
    schedule_id: int,
    environ: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Delete (soft) a scheduled search. Idempotent.

    No payload validation needed — just limit config check for consistency.

    Raises:
        IncompleteScheduleConfigurationError: invalid limit config.
    """
    _resolve_limit(environ)  # Ensure config is valid (capability gate)

    conn = _connect(db_path)
    try:
        result = delete_schedule(
            conn,
            schedule_id=schedule_id,
            actor=actor_site_user,
            now=now,
        )
        return result
    finally:
        conn.close()


def get_scheduled_search(
    *,
    db_path: str,
    actor_site_user: str,
    schedule_id: int,
    environ: Optional[Mapping[str, str]] = None,
) -> ScheduledSearchEnvelope:
    """Get a single scheduled search detail.

    Raises:
        IncompleteScheduleConfigurationError: invalid limit config.
        ScheduleNotFoundError: missing or deleted.
    """
    max_active = _resolve_limit(environ)

    conn = _connect(db_path)
    try:
        envelope = get_schedule(conn, schedule_id, max_active=max_active)
        return envelope
    finally:
        conn.close()


def list_scheduled_searches(
    *,
    db_path: str,
    actor_site_user: str,
    environ: Optional[Mapping[str, str]] = None,
) -> ScheduledSearchList:
    """List all native non-deleted scheduled searches (global).

    Returns ScheduledSearchList with per-owner limits.

    Raises:
        IncompleteScheduleConfigurationError: invalid limit config.
    """
    max_active = _resolve_limit(environ)

    conn = _connect(db_path)
    try:
        result = list_schedules(conn, max_active=max_active)
        # Map to the typed ScheduledSearchList model
        return ScheduledSearchList(
            schedules=result["schedules"],
            count=result["count"],
            limits_by_owner={
                owner: ScheduleLimits(
                    active_count=data["active_count"],
                    max_active=data["max_active"],
                )
                for owner, data in result["limits_by_owner"].items()
            },
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Domain exceptions for the service layer
# ---------------------------------------------------------------------------


class ScheduleValidationError(Exception):
    """Raised when input fails strict validation (before limit check)."""

    def __init__(self, detail: PublicErrorDetail) -> None:
        super().__init__(detail.message)
        self.detail = detail


# ---------------------------------------------------------------------------
# Error mapping — converts domain exceptions to sanitized envelopes
# ---------------------------------------------------------------------------


def map_service_error_to_envelope(exc: Exception) -> PublicErrorEnvelope:
    """Map any domain exception to a sanitized PublicErrorEnvelope.

    NEVER leaks DB path, SQL, stack trace, token, or raw exception message.
    """
    if isinstance(exc, ScheduleValidationError):
        return PublicErrorEnvelope(error=exc.detail)

    if isinstance(exc, ActiveLimitExceededError):
        return _sanitized_error(
            code="active_limit_exceeded",
            message="Przekroczono limit aktywnych zaplanowanych wyszukiwan.",
            active_count=exc.active_count,
            limit=exc.limit,
        )

    if isinstance(exc, IncompleteScheduleConfigurationError):
        return PublicErrorEnvelope(error=exc.detail)

    if isinstance(exc, ScheduleNotFoundError):
        return _sanitized_error(
            code="not_found",
            message="Zaplanowane wyszukiwanie nie zostalo znalezione.",
        )

    if isinstance(exc, VersionConflictError):
        return _sanitized_error(
            code="version_conflict",
            message="Konflikt wersji; obiekt zostal zmodyfikowany.",
        )

    if isinstance(exc, EmptyPatchError):
        return _sanitized_error(
            code="validation_error",
            message="Zadanie edycji musi zawierac co najmniej jedno pole do zmiany.",
        )

    # Catch-all: internal error without leaking details
    return _sanitized_error(
        code="internal_error",
        message="Wewnetrzny blad serwera.",
    )


__all__ = [
    "create_scheduled_search",
    "update_scheduled_search",
    "set_scheduled_search_enabled",
    "delete_scheduled_search",
    "get_scheduled_search",
    "list_scheduled_searches",
    "ScheduleValidationError",
    "map_service_error_to_envelope",
]
