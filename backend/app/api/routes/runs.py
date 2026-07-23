from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.database.models import MigrationRunStatus
from app.dependencies import (
    ApprovalSvc,
    ClosedLoopSvc,
    GradingPipelineSvc,
    LocalShadowVerifySvc,
    MemoryWriteSvc,
    MigrationRunSvc,
    PredictionPipelineSvc,
    SchemaDiscoverySvc,
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


@router.post(
    "",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    payload: MigrationRunCreateRequest,
    service: MigrationRunSvc,
) -> MigrationRunResponse:
    run = await service.create_migration_run(
        payload.migration_sql,
        owner_identity=payload.owner_identity,
        revises_run_id=payload.revises_run_id,
    )
    return MigrationRunResponse.model_validate(run)


@router.get("", response_model=MigrationRunListResponse)
async def list_runs(
    service: MigrationRunSvc,
    status_filter: MigrationRunStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> MigrationRunListResponse:
    runs = await service.list_migration_runs(
        offset=offset,
        limit=limit,
        status=status_filter,
    )
    total = await service.count_migration_runs(status=status_filter)
    return MigrationRunListResponse(
        items=[MigrationRunSummaryResponse.model_validate(run) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/metrics/accuracy")
async def get_accuracy_metrics(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Plain SQL accuracy / learning metrics (Phase 11 chart source)."""
    return await fetch_accuracy_metrics(session)


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
    run_id: uuid.UUID,
    service: MigrationRunSvc,
) -> MigrationRunResponse:
    run = await service.get_migration_run(run_id)
    return MigrationRunResponse.model_validate(run)


@router.patch("/{run_id}", response_model=MigrationRunResponse)
async def update_run_status(
    run_id: uuid.UUID,
    payload: MigrationRunStatusUpdateRequest,
    service: MigrationRunSvc,
) -> MigrationRunResponse:
    run = await service.update_status(run_id, payload.status)
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
    run_id: uuid.UUID,
    service: PredictionPipelineSvc,
) -> MigrationRunResponse:
    """Run Phase 9 policy → predict → recommend and stop at awaiting_approval."""
    run = await service.run_prediction_pipeline(run_id)
    return MigrationRunResponse.model_validate(run)


@router.get("/{run_id}/pipeline-progress")
async def get_pipeline_progress(run_id: uuid.UUID) -> dict[str, Any]:
    """Live stage progress for a long-running predict / local-verify (in-process)."""
    from app.services.pipeline_progress import get_progress

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
    run_id: uuid.UUID,
    payload: ApprovalCreateRequest,
    service: ApprovalSvc,
) -> MigrationRunResponse:
    """Record approval. On proceed, auto-starts the verify workflow when configured."""
    run = await service.approve(
        run_id,
        decision=payload.decision,
        approver_identity=payload.approver_identity,
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
    run_id: uuid.UUID,
    payload: ClosedLoopRequest,
    service: ClosedLoopSvc,
) -> MigrationRunResponse:
    """Predict (if needed) → proceed → start SFN when ARN + connection secret exist."""
    run = await service.run(run_id, payload)
    return MigrationRunResponse.model_validate(run)


@router.post(
    "/{run_id}/start-workflow",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def start_workflow(
    run_id: uuid.UUID,
    payload: StartWorkflowRequest,
    service: WorkflowOrchestrationSvc,
    run_service: MigrationRunSvc,
) -> MigrationRunResponse:
    """Start Step Functions verify after prediction + proceed approval."""
    run = await run_service.get_migration_run(run_id, load_children=True)
    secret = (payload.connection_secret_arn or run.connection_secret_arn or "").strip()
    if not secret:
        raise ValidationError(
            "connection_secret_arn is required (pass in body or POST /discover first)"
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
    run_id: uuid.UUID,
    service: LocalShadowVerifySvc,
) -> MigrationRunResponse:
    """Run in-process mock shadow verify when Step Functions is not deployed.

    Same handler chain as the durable workflow (discover → provision → load →
    execute → collect → persist/grade → cleanup), using SHADOW_PROVIDER=mock.
    Use this for local demos; set MIGRATION_WORKFLOW_ARN for real AWS verify.
    """
    run = await service.verify_run(run_id)
    return MigrationRunResponse.model_validate(run)


@router.post(
    "/{run_id}/sync-workflow",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def sync_workflow(
    run_id: uuid.UUID,
    service: WorkflowOrchestrationSvc,
) -> MigrationRunResponse:
    run = await service.sync_status(run_id)
    return MigrationRunResponse.model_validate(run)


@router.get("/{run_id}/approval", response_model=ApprovalResponse)
async def get_approval(
    run_id: uuid.UUID,
    service: MigrationRunSvc,
) -> ApprovalResponse:
    run = await service.get_migration_run(run_id, load_children=True)
    if run.approval is None:
        raise NotFoundError(f"No approval recorded for MigrationRun {run_id}")
    return ApprovalResponse.model_validate(run.approval)


@router.post(
    "/{run_id}/grade",
    response_model=MigrationRunResponse,
    status_code=status.HTTP_200_OK,
)
async def grade_run(
    run_id: uuid.UUID,
    service: GradingPipelineSvc,
) -> MigrationRunResponse:
    run = await service.grade_run(run_id)
    return MigrationRunResponse.model_validate(run)


@router.get("/{run_id}/grade", response_model=GradeResponse)
async def get_grade(
    run_id: uuid.UUID,
    service: MigrationRunSvc,
) -> GradeResponse:
    run = await service.get_migration_run(run_id, load_children=True)
    if run.grade is None:
        raise NotFoundError(f"No grade recorded for MigrationRun {run_id}")
    return GradeResponse.model_validate(run.grade)


@router.get("/{run_id}/memory", response_model=MemoryResponse)
async def get_memory(
    run_id: uuid.UUID,
    service: MigrationRunSvc,
) -> MemoryResponse:
    run = await service.get_migration_run(run_id, load_children=True)
    if run.memory is None:
        raise NotFoundError(f"No memory recorded for MigrationRun {run_id}")
    return MemoryResponse.from_orm_memory(run.memory)


@router.get("/{run_id}/shadow-cluster", response_model=ShadowClusterResponse)
async def get_shadow_cluster(
    run_id: uuid.UUID,
    service: MigrationRunSvc,
) -> ShadowClusterResponse:
    """Read-only shadow cluster lifecycle row (Phase 7 data; Phase 11 exposure)."""
    run = await service.get_migration_run(run_id, load_children=True)
    if run.shadow_cluster is None:
        raise NotFoundError(f"No shadow cluster recorded for MigrationRun {run_id}")
    return ShadowClusterResponse.from_orm(run.shadow_cluster)


@router.get("/{run_id}/execution-result", response_model=ExecutionResultResponse)
async def get_execution_result(
    run_id: uuid.UUID,
    service: MigrationRunSvc,
) -> ExecutionResultResponse:
    """Read-only shadow execution actuals (Phase 8 data; Phase 11 exposure)."""
    run = await service.get_migration_run(run_id, load_children=True)
    if run.execution_result is None:
        raise NotFoundError(f"No execution result recorded for MigrationRun {run_id}")
    return ExecutionResultResponse.model_validate(run.execution_result)


@router.get("/{run_id}/model-traces")
async def get_model_traces(
    run_id: uuid.UUID,
    service: MigrationRunSvc,
) -> dict[str, Any]:
    """Durable Bedrock traces from explainability (prediction + recommendation)."""
    run = await service.get_migration_run(run_id, load_children=True)
    explain = run.explainability or {}
    traces = explain.get("bedrock_traces")
    if not traces:
        raise NotFoundError(
            f"No Bedrock model traces recorded for MigrationRun {run_id}. "
            "Traces are stored on predict for runs created after Phase 11."
        )
    return {
        "migration_run_id": str(run_id),
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
    except Exception:
        request.app.state._demo_secrets = getattr(request.app.state, "_demo_secrets", {})
        request.app.state._demo_secrets[name] = payload
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
