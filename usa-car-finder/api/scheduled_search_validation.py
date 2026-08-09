"""Validation-before-limit precheck for scheduled-search creation (v1).

This module encodes the *ordering contract* required by
Feature: scheduled-recurring-car-search, Property 1
(Strict validation, atomic rejection and precedence) and Requirements
1.2, 1.5, 2.3, 5.1, 5.2:

* After authentication (Requirement 11.2, handled upstream), strict input
  validation is evaluated *before* the per-owner active limit.
* No persistence side effect may occur for any rejected request: the precheck
  is a pure function returning an outcome, and the caller persists *only* on
  acceptance. The management service (task 3.2) wraps this precheck in a
  BEGIN IMMEDIATE transaction, so the precedence/atomic-rejection semantics
  are guaranteed independently of the storage engine.
* The immutable owner is derived exclusively from the trusted actor, never from
  the client payload (client attribution keys are rejected by the strict
  request models).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Union

from pydantic import ValidationError

from api.scheduled_search_models import (
    CreateScheduledSearchRequest,
    PublicErrorDetail,
)


@dataclass(frozen=True)
class CreateAccepted:
    """Validation and limit both passed; caller may persist."""

    request: CreateScheduledSearchRequest
    owner_site_user: str


@dataclass(frozen=True)
class CreateRejected:
    """Request rejected before any persistence side effect."""

    error: PublicErrorDetail


CreateOutcome = Union[CreateAccepted, CreateRejected]


def _validation_error(exc: ValidationError) -> PublicErrorDetail:
    fields: dict[str, str] = {}
    for err in exc.errors():
        loc = err.get("loc", ())
        key = ".".join(str(part) for part in loc) or "__root__"
        # First error per field wins; keep messages sanitized (no raw input echoed).
        fields.setdefault(key, str(err.get("msg", "Nieprawidłowa wartość.")))
    return PublicErrorDetail(
        code="validation_error",
        message="Nieprawidłowe dane wejściowe zaplanowanego wyszukiwania.",
        fields=fields or None,
    )


def create_precheck(
    payload: Mapping[str, Any],
    *,
    actor_site_user: str,
    active_count: int,
    max_active: int,
) -> CreateOutcome:
    """Validate a create request, then evaluate the active limit, in that order.

    Returns :class:`CreateAccepted` only when the payload satisfies the strict
    schema *and* the owner is below the active limit. Any rejection returns a
    :class:`CreateRejected` and performs no persistence.
    """
    # 1. Strict validation has precedence over the limit (Requirements 1.5, 5.2).
    try:
        request = CreateScheduledSearchRequest.model_validate(payload)
    except ValidationError as exc:
        return CreateRejected(error=_validation_error(exc))

    # 2. Only after successful validation do we evaluate the per-owner limit.
    if active_count >= max_active:
        return CreateRejected(
            error=PublicErrorDetail(
                code="active_limit_exceeded",
                message="Przekroczono limit aktywnych zaplanowanych wyszukiwań.",
                active_count=active_count,
                limit=max_active,
            )
        )

    # 3. Owner comes from the trusted actor only (never the client payload).
    return CreateAccepted(request=request, owner_site_user=actor_site_user)


__all__ = [
    "CreateAccepted",
    "CreateRejected",
    "CreateOutcome",
    "create_precheck",
]
