from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.database.models import MigrationRunStatus
from app.dependencies import MigrationRunSvc
from app.schemas.migration_run import (
    MigrationRunCreateRequest,
    MigrationRunListResponse,
    MigrationRunResponse,
    MigrationRunStatusUpdateRequest,
    MigrationRunSummaryResponse,
)

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
    run = await service.create_migration_run(payload.migration_sql)
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
