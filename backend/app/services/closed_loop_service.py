"""One-button closed loop: predict → approve(proceed) → start workflow when possible."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from app.core.exceptions import ConflictError
from app.core.logging import get_logger
from app.database.models import ApprovalDecision, MigrationRun, MigrationRunStatus
from app.repositories.migration_run_repository import MigrationRunRepository
from app.services.approval_service import ApprovalService
from app.services.prediction_pipeline_service import PredictionPipelineService

if TYPE_CHECKING:
    from app.services.workflow_orchestration_service import WorkflowOrchestrationService

logger = get_logger(__name__)


class ClosedLoopRequest(BaseModel):
    """Drive the operator happy path from a single POST."""

    approver_identity: str = Field(default="closed-loop", min_length=1, max_length=256)
    connection_secret_arn: str | None = None
    override_rationale: str | None = None
    start_workflow: bool = True

    @field_validator("approver_identity")
    @classmethod
    def strip_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("approver_identity must not be empty")
        return normalized

    @field_validator("connection_secret_arn", "override_rationale")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ClosedLoopService:
    def __init__(
        self,
        *,
        runs: MigrationRunRepository,
        prediction: PredictionPipelineService,
        approval: ApprovalService,
        workflow: WorkflowOrchestrationService | None = None,
    ) -> None:
        self._runs = runs
        self._prediction = prediction
        self._approval = approval
        self._workflow = workflow

    async def run(
        self,
        run_id: uuid.UUID,
        request: ClosedLoopRequest,
    ) -> MigrationRun:
        """Predict (if needed) → approve proceed → start workflow when configured."""
        run = await self._runs.get_by_id_or_raise(run_id, load_children=True)

        if run.status in {
            MigrationRunStatus.PENDING,
            MigrationRunStatus.PREDICTING,
        }:
            run = await self._prediction.run_prediction_pipeline(run_id)
        elif run.status == MigrationRunStatus.AWAITING_APPROVAL:
            pass
        elif run.status == MigrationRunStatus.RUNNING and run.sfn_execution_arn:
            return run
        elif run.status == MigrationRunStatus.RUNNING:
            # Already proceeded; try start/sync workflow.
            secret = (
                (request.connection_secret_arn or "").strip()
                or (run.connection_secret_arn or "").strip()
            )
            if self._workflow is not None and secret and request.start_workflow:
                return await self._workflow.start_for_run(
                    run_id,
                    connection_secret_arn=secret,
                    require_prediction_and_approval=True,
                )
            return run
        else:
            raise ConflictError(
                f"Closed loop cannot start from status={run.status.value}"
            )

        if run.status != MigrationRunStatus.AWAITING_APPROVAL:
            raise ConflictError(
                f"Expected awaiting_approval after predict; got {run.status.value}"
            )

        if run.approval is not None:
            raise ConflictError(f"MigrationRun {run_id} already has an approval")

        updated = await self._approval.approve(
            run_id,
            decision=ApprovalDecision.PROCEED,
            approver_identity=request.approver_identity,
            override_rationale=request.override_rationale,
            connection_secret_arn=request.connection_secret_arn,
            start_workflow=request.start_workflow,
        )
        logger.info(
            "Closed-loop proceed recorded",
            extra={
                "run_id": str(run_id),
                "status": updated.status.value,
                "sfn_execution_arn": updated.sfn_execution_arn,
            },
        )
        return updated
