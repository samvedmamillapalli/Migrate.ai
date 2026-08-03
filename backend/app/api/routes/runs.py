from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tenancy import (
    assert_run_access,
    auth_enforced,
    resolve_owner_identity,
    session_owner,
)
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.models import MigrationRun, MigrationRunStatus
from app.dependencies import (
    ApprovalSvc,
    ClosedLoopSvc,
    GradingPipelineSvc,
    LocalShadowVerifySvc,
    MemoryWriteSvc,
    MigrationRunSvc,
    PredictionPipelineSvc,
    SchemaDiscoverySvc,
    ShadowClusterSvc,
    WorkflowOrchestrationSvc,
    get_db_session,
)
from app.memory.metrics import fetch_accuracy_metrics
from app.schemas.approval import ApprovalCreateRequest, ApprovalResponse
from app.schemas.grade import GradeResponse, MemoryResponse, RepairEmbeddingsRequest
from app.schemas.migration_run import (
    MigrationRunCreateRequest,
    MigrationRunListResponse,
    MigrationRunResponse,
    MigrationRunStatusUpdateRequest,
    MigrationRunSummaryResponse,
)
from app.schemas.observability import (
    ExecutionResultResponse,
    ShadowClusterResponse,
)
from app.schemas.workflow import DiscoverSchemaRequest, StartWorkflowRequest
from app.schema_analysis.database_connection import DatabaseConnection, SslMode
from app.services.closed_loop_service import ClosedLoopRequest

router = APIRouter(prefix="/runs", tags=["migration-runs"])
logger = get_logger(__name__)


# --- Tenant-scoped run access -----------------------------------------------
#
# Every `/{run_id}...` route below must resolve the run through one of these
# two dependencies rather than calling `service.get_migration_run` directly.
# An earlier version of this file had `assert_run_access` copy-pasted into
# only 4 of 21 run-scoped routes; the other 17 fetched by ID with no
# ownership check at all — any authenticated user who knew (or guessed) a
# UUID could read another user's Bedrock prediction traces, grades, and
# shadow-cluster state, or worse, call start-workflow / abort-workflow /
# predict on a run they didn't own. Routing every handler through a shared
# dependency makes that omission structurally harder to reintroduce: a new
# route has to actively skip these to reproduce the bug, instead of the
# leak being the default.


async def get_owned_run(
    run_id: uuid.UUID,
    request: Request,
    service: MigrationRunSvc,
) -> MigrationRun:
    """Fetch a run and enforce tenant ownership. No relationships loaded."""
    run = await service.get_migration_run(run_id)
    assert_run_access(request, run)
    return run


async def get_owned_run_with_children(
    run_id: uuid.UUID,
    request: Request,
    service: MigrationRunSvc,
) -> MigrationRun:
    """Same as ``get_owned_run``, with related rows eager-loaded — for
    routes that read approval / grade / memory / shadow_cluster /
    execution_result / explainability off the returned run."""
    run = await service.get_migration_run(run_id, load_children=True)
    assert_run_access(request, run)
    return run


@router.post(
    "",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    payload: MigrationRunCreateRequest,
    service: MigrationRunSvc,
    request: Request,
) -> MigrationRunResponse:
    owner = resolve_owner_identity(request, payload.owner_identity)
    run = await service.create_migration_run(
        payload.migration_sql,
        owner_identity=owner,
        revises_run_id=payload.revises_run_id,
        run_kind=payload.run_kind,
    )
    return MigrationRunResponse.model_validate(run)


@router.get("", response_model=MigrationRunListResponse)
async def list_runs(
    request: Request,
    service: MigrationRunSvc,
    status_filter: MigrationRunStatus | None = Query(default=None, alias="status"),
    owner_identity: str | None = Query(default=None, min_length=1, max_length=256),
    run_kind: str | None = Query(default=None, min_length=1, max_length=32),
    exclude_kinds: str | None = Query(
        default=None,
        description="Comma-separated run_kind values to exclude, e.g. chaos,debug",
    ),
    q: str | None = Query(
        default=None,
        max_length=200,
        description="Case-insensitive substring match on the migration SQL.",
    ),
    risk: str | None = Query(
        default=None,
        description="Filter by compatibility_risk: low | medium | high",
    ),
    decision: str | None = Query(
        default=None,
        description=(
            "Filter by recorded approval decision: proceed | accept_recommended "
            "| cancel, or 'none' for runs with no decision yet."
        ),
    ),
    approver: str | None = Query(default=None, max_length=256),
    order_by: str = Query(
        default="created_at",
        description="created_at | updated_at | status | compatibility_risk",
    ),
    order_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> MigrationRunListResponse:
    # Auth mode always scopes to the session owner (ignore client filter).
    scoped = session_owner(request) if request else None
    if auth_enforced():
        owner_identity = scoped
    excluded = (
        [kind.strip() for kind in exclude_kinds.split(",") if kind.strip()]
        if exclude_kinds
        else None
    )
    if risk is not None and risk not in {"low", "medium", "high"}:
        raise ValidationError("risk must be one of: low, medium, high")
    if decision is not None and decision not in {
        "proceed",
        "accept_recommended",
        "cancel",
        "none",
    }:
        raise ValidationError(
            "decision must be one of: proceed, accept_recommended, cancel, none"
        )

    filters = {
        "status": status_filter,
        "owner_identity": owner_identity,
        "run_kind": run_kind,
        "exclude_kinds": excluded,
        "search": (q or "").strip() or None,
        "compatibility_risk": risk,
        "approval_decision": decision,
        "approver_identity": (approver or "").strip() or None,
    }
    runs = await service.list_migration_runs(
        offset=offset,
        limit=limit,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )
    total = await service.count_migration_runs(**filters)
    return MigrationRunListResponse(
        items=[MigrationRunSummaryResponse.from_orm_run(run) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/metrics/accuracy")
async def get_accuracy_metrics(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    owner_identity: str | None = Query(default=None, min_length=1, max_length=256),
) -> dict[str, Any]:
    """Plain SQL accuracy / learning metrics (Phase 11 chart source).

    Scoped to the same owner as the Recent-runs list when one is known (auth
    session, or an explicit query param), so this card and "Recent" never show
    two different populations side by side without saying so.
    """
    scoped = session_owner(request) if request else None
    if auth_enforced():
        owner_identity = scoped
    return await fetch_accuracy_metrics(session, owner_identity=owner_identity)


@router.get("/approvers")
async def list_approvers(
    request: Request,
    service: MigrationRunSvc,
    owner_identity: str | None = Query(default=None, min_length=1, max_length=256),
) -> dict[str, Any]:
    """Distinct approver identities, for the history page's filter dropdown."""
    if auth_enforced():
        owner_identity = session_owner(request) if request else None
    approvers = await service.list_approvers(
        owner_identity=owner_identity,
        exclude_kinds=["chaos", "debug"],
    )
    return {"approvers": sorted(approvers)}


@router.get("/volume")
async def get_run_volume(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    owner_identity: str | None = Query(default=None, min_length=1, max_length=256),
    days: int = Query(default=7, ge=1, le=90),
) -> dict[str, Any]:
    """Daily run counts over the whole history, not just one page.

    Splits each day into runs that succeeded and runs that failed or were
    cancelled, so the chart's two series mean something specific. Days with no
    runs are returned as explicit zeroes rather than omitted, so the caller
    doesn't have to reconstruct the calendar.
    """
    from app.services.activity_feed import fetch_run_volume

    if auth_enforced():
        owner_identity = session_owner(request) if request else None
    return await fetch_run_volume(
        session, owner_identity=owner_identity, days=days
    )


@router.get("/activity")
async def get_activity_feed(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    owner_identity: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    """Merged, reverse-chronological stream of what actually happened.

    Every entry is derived from a persisted timestamp (run created, prediction
    written, approval recorded, shadow started/measured, grade written, memory
    stored). Nothing is synthesized. Scoped to the same owner as the Recent
    list so the Overview never mixes two populations.
    """
    from app.services.activity_feed import fetch_activity_feed

    scoped = session_owner(request) if request else None
    if auth_enforced():
        owner_identity = scoped
    return await fetch_activity_feed(
        session,
        owner_identity=owner_identity,
        limit=limit,
    )


@router.post(
    "/debug/demo-with-db",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_debug_demo_with_db(
    service: MigrationRunSvc,
    discovery: SchemaDiscoverySvc,
    request: Request,
    owner_identity: str = Query(default="demo", min_length=1, max_length=256),
) -> MigrationRunResponse:
    """Developer helper: real customer_demo RO DB + sample migration SQL.

    Reads the URL from env ``DEMO_READONLY_DATABASE_URL`` or the gitignored
    ``.local_secrets/.judge_ro_database_url`` (server-side only). Creates the
    run, stores a connection secret, and runs schema discovery so
    predict/shadow can proceed.

    Easy to remove: delete this route + the frontend Developer mode button.
    """
    import os

    from app.demo_secrets import JUDGE_RO_DATABASE_URL_FILE, read_demo_secret

    url = (os.environ.get("DEMO_READONLY_DATABASE_URL") or "").strip()
    if not url:
        url = read_demo_secret(JUDGE_RO_DATABASE_URL_FILE) or ""
    if not url:
        raise ValidationError(
            "Developer demo DB not configured. Set DEMO_READONLY_DATABASE_URL, "
            "or run `python scripts/prepare_judge_demo_db.py` to create "
            ".local_secrets/.judge_ro_database_url."
        )

    run = await service.create_migration_run(
        "ALTER TABLE customers ADD COLUMN demo_flag STRING NOT NULL DEFAULT 'ok';",
        owner_identity=owner_identity,
        run_kind="debug",
    )
    secret_arn = await _store_connection_url(request, run.id, url)
    connection = await _load_connection(request, secret_arn)
    run = await discovery.discover_and_persist(
        run.id,
        connection,
        connection_secret_arn=secret_arn,
    )
    return MigrationRunResponse.model_validate(run)


@router.post(
    "/debug/fake-migration",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_debug_fake_migration(
    service: MigrationRunSvc,
    request: Request,
    owner_identity: str = Query(default="debug", min_length=1, max_length=256),
) -> MigrationRunResponse:
    """Debug helper: random SQL + synthetic schema so predict works without a real DB.

    Stores a connection_secret_arn (control-plane DATABASE_URL) so approve can
    start Step Functions. DiscoverSchema is skipped because discovery already
    SUCCEEDED on the synthetic snapshot. Does not create graded memories.
    """
    from app.config import get_settings

    run = await service.create_debug_fake_migration(owner_identity=owner_identity)
    database_url = get_settings().database_url.get_secret_value()
    secret_arn = await _store_connection_url(request, run.id, database_url)
    run = await service.set_connection_secret_arn(run.id, secret_arn)
    return MigrationRunResponse.model_validate(run)


@router.get("/{run_id}", response_model=MigrationRunResponse)
async def get_run(
    run: MigrationRun = Depends(get_owned_run),
) -> MigrationRunResponse:
    return MigrationRunResponse.model_validate(run)


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_run(
    run_id: uuid.UUID,
    service: MigrationRunSvc,
    _owned: MigrationRun = Depends(get_owned_run),
) -> None:
    """Discard a run abandoned during setup.

    Only a ``pending`` run with no approval, grade, execution result, shadow
    cluster or memory can be removed — see
    MigrationRunService.discard_abandoned_run. Anything further along is part
    of the audit record and returns 409 instead.
    """
    await service.discard_abandoned_run(run_id)


@router.patch("/{run_id}", response_model=MigrationRunResponse)
async def update_run_status(
    payload: MigrationRunStatusUpdateRequest,
    service: MigrationRunSvc,
    owned: MigrationRun = Depends(get_owned_run),
) -> MigrationRunResponse:
    run = await service.update_status(owned.id, payload.status)
    return MigrationRunResponse.model_validate(run)


@router.post(
    "/{run_id}/discover",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def discover_schema(
    run_id: uuid.UUID,
    payload: DiscoverSchemaRequest,
    discovery: SchemaDiscoverySvc,
    request: Request,
    _owned: MigrationRun = Depends(get_owned_run),
) -> MigrationRunResponse:
    """Discover customer schema (read-only) and store connection_secret_arn pointer."""
    secret_arn = payload.connection_secret_arn
    if payload.database_url:
        secret_arn = await _store_connection_url(request, run_id, payload.database_url)

    assert secret_arn is not None
    connection = await _load_connection(request, secret_arn)
    run = await discovery.discover_and_persist(
        run_id,
        connection,
        connection_secret_arn=secret_arn,
    )
    return MigrationRunResponse.model_validate(run)


@router.post(
    "/{run_id}/predict",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def run_prediction_pipeline(
    service: PredictionPipelineSvc,
    owned: MigrationRun = Depends(get_owned_run),
) -> MigrationRunResponse:
    """Run Phase 9 policy → predict → recommend and stop at awaiting_approval."""
    run = await service.run_prediction_pipeline(owned.id)
    return MigrationRunResponse.model_validate(run)


@router.get("/{run_id}/pipeline-progress")
async def get_pipeline_progress(
    run_id: uuid.UUID,
    run: MigrationRun = Depends(get_owned_run),
) -> dict[str, Any]:
    """Live stage progress for a long-running predict / discover / local-verify
    (in-process, single-uvicorn-worker).

    Predict progress is cleared once the run leaves ``predicting``; discover
    progress is only meaningful while the run is still ``pending`` (discovery
    never changes run status itself). Either way, a stale bar from a previous
    stage never survives a status change it doesn't belong to.
    """
    from app.services.pipeline_progress import clear_progress, get_progress

    if run.status not in (MigrationRunStatus.PREDICTING, MigrationRunStatus.PENDING):
        clear_progress(run_id)
        return {
            "run_id": str(run_id),
            "stage": "idle",
            "message": "No active pipeline progress",
            "percent": 0,
            "history": [],
        }

    data = get_progress(run_id)
    if data is None:
        return {
            "run_id": str(run_id),
            "stage": "idle",
            "message": "No active pipeline progress",
            "percent": 0,
            "history": [],
        }
    return data


@router.post(
    "/{run_id}/approve",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def approve_run(
    payload: ApprovalCreateRequest,
    service: ApprovalSvc,
    request: Request,
    owned: MigrationRun = Depends(get_owned_run),
) -> MigrationRunResponse:
    """Record approval. On proceed, auto-starts the verify workflow when configured."""
    from app.services.pipeline_progress import clear_progress

    run_id = owned.id
    clear_progress(run_id)
    approver = resolve_owner_identity(request, payload.approver_identity)
    run = await service.approve(
        run_id,
        decision=payload.decision,
        approver_identity=approver,
        override_rationale=payload.override_rationale,
        connection_secret_arn=payload.connection_secret_arn,
        start_workflow=payload.start_workflow,
    )
    return MigrationRunResponse.model_validate(run)


@router.post(
    "/{run_id}/closed-loop",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def run_closed_loop(
    payload: ClosedLoopRequest,
    service: ClosedLoopSvc,
    owned: MigrationRun = Depends(get_owned_run),
) -> MigrationRunResponse:
    """Predict (if needed) → proceed → start SFN when ARN + connection secret exist."""
    run = await service.run(owned.id, payload)
    return MigrationRunResponse.model_validate(run)


@router.post(
    "/{run_id}/start-workflow",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def start_workflow(
    payload: StartWorkflowRequest,
    service: WorkflowOrchestrationSvc,
    run_service: MigrationRunSvc,
    request: Request,
    run: MigrationRun = Depends(get_owned_run_with_children),
) -> MigrationRunResponse:
    """Start Step Functions verify after prediction + proceed approval."""
    from app.services.pipeline_progress import clear_progress

    run_id = run.id
    clear_progress(run_id)
    secret = (payload.connection_secret_arn or run.connection_secret_arn or "").strip()
    if not secret and payload.database_url:
        secret = await _store_connection_url(request, run_id, payload.database_url)
        run = await run_service.set_connection_secret_arn(run_id, secret)
    if not secret:
        raise ValidationError(
            "Attach a database first: POST /discover with connection_secret_arn or "
            "database_url, or pass one of those on start-workflow. Without a "
            "connection the shadow cannot seed from your schema."
        )
    updated = await service.start_for_run(
        run_id,
        connection_secret_arn=secret,
        require_prediction_and_approval=True,
    )
    return MigrationRunResponse.model_validate(updated)


@router.post(
    "/{run_id}/verify-local",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_local(
    service: LocalShadowVerifySvc,
    owned: MigrationRun = Depends(get_owned_run),
) -> MigrationRunResponse:
    """Run in-process mock shadow verify when Step Functions is not deployed.

    Same handler chain as the durable workflow (discover → provision → load →
    execute → collect → persist/grade → cleanup), using SHADOW_PROVIDER=mock.
    Use this for local demos; set MIGRATION_WORKFLOW_ARN for real AWS verify.
    """
    run = await service.verify_run(owned.id)
    return MigrationRunResponse.model_validate(run)


@router.post(
    "/{run_id}/sync-workflow",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def sync_workflow(
    service: WorkflowOrchestrationSvc,
    owned: MigrationRun = Depends(get_owned_run),
) -> MigrationRunResponse:
    run = await service.sync_status(owned.id)
    return MigrationRunResponse.model_validate(run)


@router.post(
    "/{run_id}/abort-workflow",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def abort_workflow(
    service: WorkflowOrchestrationSvc,
    owned: MigrationRun = Depends(get_owned_run),
) -> MigrationRunResponse:
    """Abort a running shadow workflow and tear down the shadow cluster."""
    from app.services.pipeline_progress import clear_progress

    run_id = owned.id
    clear_progress(run_id)
    run = await service.abort_for_run(run_id)
    return MigrationRunResponse.model_validate(run)


@router.get("/{run_id}/approval", response_model=ApprovalResponse)
async def get_approval(
    run: MigrationRun = Depends(get_owned_run_with_children),
) -> ApprovalResponse:
    if run.approval is None:
        raise NotFoundError(f"No approval recorded for MigrationRun {run.id}")
    return ApprovalResponse.model_validate(run.approval)


@router.post(
    "/{run_id}/grade",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def grade_run(
    service: GradingPipelineSvc,
    owned: MigrationRun = Depends(get_owned_run),
) -> MigrationRunResponse:
    run = await service.grade_run(owned.id)
    return MigrationRunResponse.model_validate(run)


@router.get("/{run_id}/grade", response_model=GradeResponse)
async def get_grade(
    run: MigrationRun = Depends(get_owned_run_with_children),
) -> GradeResponse:
    if run.grade is None:
        raise NotFoundError(f"No grade recorded for MigrationRun {run.id}")
    return GradeResponse.model_validate(run.grade)


@router.get("/{run_id}/memory", response_model=MemoryResponse)
async def get_memory(
    run: MigrationRun = Depends(get_owned_run_with_children),
) -> MemoryResponse:
    if run.memory is None:
        raise NotFoundError(f"No memory recorded for MigrationRun {run.id}")
    return MemoryResponse.from_orm_memory(run.memory)


@router.get("/{run_id}/shadow-cluster", response_model=ShadowClusterResponse)
async def get_shadow_cluster(
    run: MigrationRun = Depends(get_owned_run_with_children),
    session: AsyncSession = Depends(get_db_session),
) -> ShadowClusterResponse:
    """Read-only shadow cluster lifecycle row (Phase 7 data; Phase 11 exposure).

    Includes ccloud_audit_trail (docs/cockroach_hookup.md §4 "Feature 1") —
    empty until the workflow reaches a terminal state and the audit-trail
    fetch runs, or if ccloud isn't logged in on the backend host.
    """
    from app.repositories.ccloud_audit_event_repository import CCloudAuditEventRepository

    if run.shadow_cluster is None:
        raise NotFoundError(f"No shadow cluster recorded for MigrationRun {run.id}")
    audit_events = await CCloudAuditEventRepository(session).list_for_run(run.id)
    return ShadowClusterResponse.from_orm(
        run.shadow_cluster, ccloud_audit_trail=audit_events
    )


@router.post(
    "/{run_id}/shadow-cluster/teardown-now",
    response_model=ShadowClusterResponse,
    status_code=status.HTTP_200_OK,
)
async def teardown_shadow_cluster_now(
    run_id: uuid.UUID,
    service: ShadowClusterSvc,
    _owned: MigrationRun = Depends(get_owned_run),
) -> ShadowClusterResponse:
    """End a HOLDING cluster's inspection window immediately.

    After execute+measure finish, the cluster is held (not destroyed) for
    ``settings.shadow_hold_minutes`` so the row-sample/schema-diff box stays
    populated — see app.lambdas.handlers.cleanup. This lets the user end that
    hold early instead of waiting out the window or the sweeper. Idempotent:
    calling it on an already-destroyed cluster just returns its current state.

    ``service.get_by_run`` below reads the ``shadow_clusters`` table, which
    has no ``owner_identity`` of its own — ownership can only be checked
    against the parent ``MigrationRun``, hence the extra
    ``get_owned_run`` dependency alongside it.
    """
    from app.lambdas.handlers.cleanup import delete_shadow_secret
    from app.lambdas.runtime import get_runtime
    from app.shadow.factory import create_shadow_provider, provider_choice_for_name

    shadow = await service.get_by_run(run_id)
    if shadow is None:
        raise NotFoundError(f"No shadow cluster recorded for MigrationRun {run_id}")

    if shadow.status.value != "destroyed":
        # Reconstruct the provider that actually *created* this cluster, not
        # whatever SHADOW_PROVIDER is currently set to (see factory.py) — a
        # global-setting mismatch here means calling destroy() against the
        # wrong backend entirely (e.g. the real Cloud API for a cluster that
        # only ever existed as a mock scratch database).
        provider = create_shadow_provider(
            provider_choice=provider_choice_for_name(shadow.provider)
        )
        try:
            shadow = await service.teardown_now(shadow.id, provider=provider)
        finally:
            await provider.aclose()
        if shadow.status.value == "destroyed":
            await delete_shadow_secret(get_runtime(), run_id)

    return ShadowClusterResponse.from_orm(shadow)


@router.get("/{run_id}/shadow-cluster/stream")
async def stream_shadow_cluster(
    run_id: uuid.UUID,
    request: Request,
    _owned: MigrationRun = Depends(get_owned_run),
):
    """Push-based shadow-cluster updates (SSE) — replaces polling GET /shadow-cluster.

    One JSON `ShadowClusterResponse` payload per `event: shadow` message,
    sent only when it actually changed (plus a periodic heartbeat so proxies
    don't time out an idle connection). Falls back gracefully: a client that
    can't use EventSource can keep polling the plain GET route, which is
    unaffected by this endpoint's existence.

    Ownership is checked once, up front, via ``get_owned_run`` — a stream
    for a run you don't own should never open, rather than being checked
    per-tick inside the generator below (which re-fetches the run itself
    for its own polling purposes, unrelated to authorization).
    """
    from sse_starlette.sse import EventSourceResponse

    from app.database.session import DatabaseSessionManager
    from app.repositories.migration_run_repository import MigrationRunRepository

    async def _event_source():
        database: DatabaseSessionManager = request.app.state.database
        last_payload: str | None = None
        started = time.monotonic()
        # Adaptive-ish: check often early (matches the "execute" stage moving
        # fast), back off once a run has been live a while, hard ceiling
        # mirrors the frontend's existing 30-minute polling ceiling.
        interval = 1.0
        while True:
            if await request.is_disconnected():
                return
            elapsed = time.monotonic() - started
            if elapsed > 1800:
                yield {"event": "timeout", "data": "{}"}
                return
            interval = 1.0 if elapsed < 120 else 3.0

            try:
                # aclosing (not a bare `async for ... break`) so the session
                # is deterministically closed/returned to the pool on every
                # tick instead of waiting on GC to finalize the generator.
                async with contextlib.aclosing(database.session()) as gen:
                    session = await gen.__anext__()
                    run_repo = MigrationRunRepository(session)
                    run = await run_repo.get_by_id_or_raise(
                        run_id, load_children=True
                    )
                    if run.shadow_cluster is None:
                        payload = {"waiting": True}
                    else:
                        payload = ShadowClusterResponse.from_orm(
                            run.shadow_cluster
                        ).model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001 - stream must not crash on a blip
                logger.warning(
                    "shadow-cluster stream tick failed",
                    extra={"run_id": str(run_id), "error": str(exc)},
                )
                await asyncio.sleep(interval)
                continue

            serialized = json.dumps(payload, sort_keys=True)
            if serialized != last_payload:
                last_payload = serialized
                yield {"event": "shadow", "data": serialized}
            else:
                yield {"event": "heartbeat", "data": "{}"}

            if isinstance(payload, dict) and payload.get("status") in (
                "destroyed",
                "failed",
            ):
                return
            await asyncio.sleep(interval)

    return EventSourceResponse(_event_source())


@router.get("/{run_id}/execution-result", response_model=ExecutionResultResponse)
async def get_execution_result(
    run: MigrationRun = Depends(get_owned_run_with_children),
) -> ExecutionResultResponse:
    """Read-only shadow execution actuals (Phase 8 data; Phase 11 exposure)."""
    if run.execution_result is None:
        raise NotFoundError(f"No execution result recorded for MigrationRun {run.id}")
    return ExecutionResultResponse.model_validate(run.execution_result)


@router.get("/{run_id}/model-traces")
async def get_model_traces(
    run: MigrationRun = Depends(get_owned_run_with_children),
) -> dict[str, Any]:
    """Durable Bedrock traces from explainability (prediction + recommendation)."""
    explain = run.explainability or {}
    traces = explain.get("bedrock_traces")
    if not traces:
        raise NotFoundError(
            f"No Bedrock model traces recorded for MigrationRun {run.id}. "
            "Traces are stored on predict for runs created after Phase 11."
        )
    return {
        "migration_run_id": str(run.id),
        "traces": traces,
    }


@router.post(
    "/memories/repair-embeddings",
    status_code=status.HTTP_200_OK,
)
async def repair_embeddings(
    payload: RepairEmbeddingsRequest,
    service: MemoryWriteSvc,
) -> dict[str, Any]:
    repaired = await service.repair_pending_embedding(
        memory_id=payload.memory_id,
        run_id=payload.run_id,
        limit=payload.limit,
    )
    return {
        "repaired": [
            {
                "id": str(m.id),
                "migration_run_id": str(m.migration_run_id),
                "embedding_status": m.embedding_status,
                "embedding_error": m.embedding_error,
            }
            for m in repaired
        ]
    }


def _parse_database_url(url: str) -> DatabaseConnection:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValidationError("database_url must include a host")
    database = (parsed.path or "/").lstrip("/") or "defaultdb"
    query = dict(
        part.split("=", 1) for part in (parsed.query or "").split("&") if "=" in part
    )
    ssl_raw = (query.get("sslmode") or "require").replace("_", "-")
    try:
        ssl_mode = SslMode(ssl_raw)
    except ValueError:
        ssl_mode = SslMode.REQUIRE
    return DatabaseConnection(
        host=parsed.hostname,
        port=parsed.port or 26257,
        database=database,
        username=parsed.username or "root",
        password=parsed.password or "",
        ssl_mode=ssl_mode,
    )


async def _store_connection_url(
    request: Request,
    run_id: uuid.UUID,
    database_url: str,
) -> str:
    """Store URL in local/AWS secret store; return ARN/name pointer."""
    name = f"migration-oracle/connections/{run_id}"
    payload = {"database_url": database_url}
    try:
        from app.lambdas.runtime import get_runtime

        runtime = get_runtime()
        return await runtime.secrets.put_json(name, payload)
    except Exception as exc:
        from app.config import get_settings

        env = get_settings().environment.strip().lower()
        if env not in {"development", "dev", "local", "test"}:
            raise ValidationError(
                "Unable to store connection secret in Secrets Manager / local "
                f"secret store (refusing in-memory fallback in {env}): {exc}"
            ) from exc
        # Dev-only ephemeral fallback — lost on API restart.
        request.app.state._demo_secrets = getattr(request.app.state, "_demo_secrets", {})
        request.app.state._demo_secrets[name] = payload
        logger.warning(
            "Stored connection URL in process memory (dev fallback)",
            extra={"secret_name": name},
        )
        return name


async def _load_connection(request: Request, secret_arn: str) -> DatabaseConnection:
    demo = getattr(request.app.state, "_demo_secrets", {})
    if secret_arn in demo:
        url = demo[secret_arn].get("database_url")
        if not url:
            raise ValidationError("Stored secret missing database_url")
        return _parse_database_url(url)

    try:
        from app.lambdas.runtime import get_runtime

        runtime = get_runtime()
        raw = await runtime.secrets.get_json(secret_arn)
        if isinstance(raw, dict) and raw.get("database_url"):
            return _parse_database_url(str(raw["database_url"]))
        if isinstance(raw, dict) and raw.get("host"):
            ssl_raw = str(raw.get("sslmode") or raw.get("ssl_mode") or "require")
            try:
                ssl_mode = SslMode(ssl_raw.replace("_", "-"))
            except ValueError:
                ssl_mode = SslMode.REQUIRE
            return DatabaseConnection(
                host=str(raw["host"]),
                port=int(raw.get("port") or 26257),
                database=str(raw.get("database") or "defaultdb"),
                username=str(raw.get("username") or "root"),
                password=str(raw.get("password") or ""),
                ssl_mode=ssl_mode,
            )
        raise ValidationError("Secret must contain database_url or connection fields")
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"Unable to load connection secret: {exc}") from exc
