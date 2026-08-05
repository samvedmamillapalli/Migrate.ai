"""Pydantic schemas for cross-customer memory sharing consent — docs/cross_customer.md."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class MemorySharingStatusResponse(BaseModel):
    """Current opt-in state. Absence of a row is the same as ``False`` —
    see MemorySharingPreferenceRepository.is_enabled."""

    owner_identity: str
    enabled: bool
    enabled_at: datetime | None = None
    disabled_at: datetime | None = None


class MemorySharingSetRequest(BaseModel):
    enabled: bool
    # Only used when auth is not enforced (local/anon dev) — the token
    # owner always wins when auth IS enforced, matching
    # app.auth.tenancy.resolve_owner_identity's existing contract (see
    # runs.py's create_run/approve_run for the same pattern).
    owner_identity: str | None = None


class MemorySharingPreviewResponse(BaseModel):
    """docs/cross_customer.md §6 — a real, live example of what would be
    shared, built from one of the account's own past graded runs, shown
    before the user confirms opting in. Never written to the database."""

    available: bool
    reason: str | None = None
    source_run_id: str | None = None
    sql_shape_template: str | None = None
    generalized_summary: str | None = None
    generalized_risk_narrative: str | None = None
    generalized_lessons_learned: str | None = None
    generalized_surprise_notes: str | None = None
    risk_flags: list[dict[str, Any]] | None = None
