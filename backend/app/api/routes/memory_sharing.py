"""Cross-customer memory sharing consent HTTP routes — docs/cross_customer.md.

Opt-in, default OFF, scoped per ``owner_identity`` (Hard Constraint 1). The
preview endpoint exists specifically for §6's informed-consent requirement:
show a real generalized example from the account's own history before they
flip the toggle, not just a checkbox next to a privacy policy link.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.auth.tenancy import auth_enforced, resolve_owner_identity, session_owner
from app.dependencies import BedrockClientDep, DbSession, EmbeddingClientDep
from app.repositories.cross_customer_memory_repository import (
    CrossCustomerMemoryRepository,
)
from app.repositories.grade_repository import GradeRepository
from app.repositories.memory_sharing_preference_repository import (
    MemorySharingPreferenceRepository,
)
from app.repositories.prediction_repository import PredictionRepository
from app.schemas.memory_sharing import (
    MemorySharingPreviewResponse,
    MemorySharingSetRequest,
    MemorySharingStatusResponse,
)
from app.services.cross_customer_promotion_service import CrossCustomerPromotionService

router = APIRouter(prefix="/api/memory-sharing", tags=["memory-sharing"])


def _read_scope_owner(request: Request, owner_identity: str | None) -> str:
    """Read-path owner resolution — same pattern as
    ``memories.py``'s ``browse_memories``: the token owner wins when auth is
    enforced, otherwise fall back to a client-supplied identity (local/anon
    dev, where ``OwnerIdentityField`` on the frontend is the source of
    truth). Unlike ``resolve_owner_identity``, a missing identity here is
    not an error — reads just report "not enabled" for no owner, same as
    an owner who has never set a preference."""
    if auth_enforced():
        return session_owner(request) or ""
    return (owner_identity or "").strip()


@router.get("/status", response_model=MemorySharingStatusResponse)
async def get_status(
    request: Request,
    session: DbSession,
    owner_identity: str | None = Query(default=None),
) -> MemorySharingStatusResponse:
    owner = _read_scope_owner(request, owner_identity)
    prefs = MemorySharingPreferenceRepository(session)
    pref = await prefs.get_by_owner(owner)
    return MemorySharingStatusResponse(
        owner_identity=owner,
        enabled=bool(pref and pref.cross_customer_sharing_enabled),
        enabled_at=pref.enabled_at if pref else None,
        disabled_at=pref.disabled_at if pref else None,
    )


@router.post("/set", response_model=MemorySharingStatusResponse)
async def set_status(
    payload: MemorySharingSetRequest,
    request: Request,
    session: DbSession,
) -> MemorySharingStatusResponse:
    """Flip the opt-in toggle. The frontend is expected to have shown
    ``/preview`` before calling this with ``enabled=true`` (§6) — enforced
    in the UI, not here, matching how consent flows work everywhere else in
    this app (e.g. Slack install is a deliberate user action, not
    server-gated on having viewed a specific screen first). Write path, so
    unlike the read routes above, a genuinely missing identity is a hard
    422 (resolve_owner_identity), not a silent "" — a consent row keyed on
    an empty identity would opt in every run whose owner is also blank."""
    owner = resolve_owner_identity(request, payload.owner_identity)
    prefs = MemorySharingPreferenceRepository(session)
    pref = await prefs.set_enabled(owner, enabled=payload.enabled)
    await session.commit()
    return MemorySharingStatusResponse(
        owner_identity=owner,
        enabled=pref.cross_customer_sharing_enabled,
        enabled_at=pref.enabled_at,
        disabled_at=pref.disabled_at,
    )


@router.get("/preview", response_model=MemorySharingPreviewResponse)
async def get_preview(
    request: Request,
    session: DbSession,
    bedrock: BedrockClientDep,
    embedding: EmbeddingClientDep,
    owner_identity: str | None = Query(default=None),
) -> MemorySharingPreviewResponse:
    """Live example of what would be shared, built from this account's own
    most recently graded run — never written to the database. Does not
    require the account to already be opted in; that's the point of a
    preview."""
    owner = _read_scope_owner(request, owner_identity)
    if not owner:
        return MemorySharingPreviewResponse(
            available=False,
            reason="Sign in to preview what would be shared.",
        )

    grades = GradeRepository(session)
    latest = await grades.get_most_recent_for_owner(owner)
    if latest is None:
        return MemorySharingPreviewResponse(
            available=False,
            reason=(
                "No graded migrations yet — run and grade at least one "
                "migration to see a live example of what would be shared."
            ),
        )
    run, grade = latest

    predictions = PredictionRepository(session)
    prediction = await predictions.get_by_migration_run_id(run.id)

    from app.aws import get_aws_settings

    aws = get_aws_settings()
    service = CrossCustomerPromotionService(
        # preview() never writes, so session/repositories below are
        # constructor-required only, cheap to build for real rather than
        # passing sentinels.
        session=session,
        cross_customer_repository=CrossCustomerMemoryRepository(session),
        sharing_preference_repository=MemorySharingPreferenceRepository(session),
        bedrock_client=bedrock,
        bedrock_model_id=(
            aws.bedrock_recommendation_model_id
            or aws.bedrock_prediction_model_id
            or "mock-model"
        ),
        embedding_client=embedding,
        embedding_model_id=aws.bedrock_embedding_model_id,
    )
    result = service.preview(run=run, prediction=prediction, grade=grade)
    if result is None:
        return MemorySharingPreviewResponse(
            available=False,
            reason=(
                "Couldn't generate a clean anonymized example from your "
                "most recent graded run (this is the same safety check "
                "that would have blocked sharing it for real) — try again "
                "after your next graded run."
            ),
        )
    return MemorySharingPreviewResponse(
        available=True,
        source_run_id=result["run_id"],
        sql_shape_template=result["sql_shape_template"],
        generalized_summary=result["generalized_summary"],
        generalized_risk_narrative=result["generalized_risk_narrative"],
        generalized_lessons_learned=result["generalized_lessons_learned"],
        generalized_surprise_notes=result["generalized_surprise_notes"],
        risk_flags=result["risk_flags"],
    )
