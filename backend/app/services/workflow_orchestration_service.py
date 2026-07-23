"""Orchestration service: start/sync Step Functions executions for migration runs.

Keeps AWS Step Functions concerns out of MigrationRunService business logic.
Does not implement Lambda step handlers (Phase 8C+).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.aws.clients import AwsClientFactory
from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConfigurationError
from app.aws.workflow import (
    WorkflowExecutionError,
    WorkflowStartInput,
    describe_workflow_execution,
    start_workflow_execution,
)
from app.aws.workflow.models import WorkflowStatus as AwsWorkflowStatus
from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_logger
from app.database.models import MigrationRun, MigrationRunStatus, WorkflowStatus
from app.database.retry import with_txn_retry
from app.repositories.migration_run_repository import MigrationRunRepository

logger = get_logger(__name__)

_TERMINAL_WORKFLOW = frozenset(
    {
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.FAILED,
        WorkflowStatus.TIMED_OUT,
        WorkflowStatus.ABORTED,
    }
)


def _to_db_status(status: AwsWorkflowStatus) -> WorkflowStatus:
    return WorkflowStatus(status.value)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


class WorkflowOrchestrationService:
    """Start and synchronize durable migration workflows."""

    def __init__(
        self,
        *,
        repository: MigrationRunRepository,
        session: AsyncSession,
        aws_clients: AwsClientFactory,
        aws_settings: AwsSettings,
    ) -> None:
        self._repository = repository
        self._session = session
        self._aws_clients = aws_clients
        self._aws_settings = aws_settings

    async def start_for_run(
        self,
        run_id: uuid.UUID,
        *,
        connection_secret_arn: str,
        require_prediction_and_approval: bool = True,
    ) -> MigrationRun:
        """Start (or attach to) the Step Functions execution for ``run_id``.

        Idempotent: if the run already has an execution ARN, sync and return it.
        Execution name is the run UUID so AWS rejects duplicate starts.

        When ``require_prediction_and_approval`` is True (default), refuses to
        start unless the run has a prediction and a ``proceed`` approval —
        preventing SFN from skipping Phase 9.
        """
        secret = connection_secret_arn.strip()
        if not secret:
            raise ValidationError("connection_secret_arn must not be empty")
        if not self._aws_settings.migration_workflow_arn:
            raise AwsConfigurationError(
                "MIGRATION_WORKFLOW_ARN is required to start workflows"
            )
        if not self._aws_settings.run_artifacts_bucket:
            raise AwsConfigurationError(
                "RUN_ARTIFACTS_BUCKET is required to start workflows"
            )

        run = await self._repository.get_by_id_or_raise(run_id, load_children=True)
        if run.sfn_execution_arn:
            logger.info(
                "Workflow already started; syncing status",
                extra={
                    "run_id": str(run_id),
                    "sfn_execution_arn": run.sfn_execution_arn,
                },
            )
            return await self.sync_status(run_id)

        if run.status in {MigrationRunStatus.COMPLETED, MigrationRunStatus.FAILED}:
            raise ConflictError(
                f"Cannot start workflow for terminal run status={run.status.value}"
            )

        if require_prediction_and_approval:
            if run.prediction is None:
                raise ConflictError(
                    f"Cannot start workflow for MigrationRun {run_id}: "
                    "prediction is required (POST /runs/{id}/predict first)"
                )
            if run.approval is None:
                raise ConflictError(
                    f"Cannot start workflow for MigrationRun {run_id}: "
                    "human approval is required (POST /runs/{id}/approve)"
                )
            from app.database.models import ApprovalDecision

            if run.approval.decision != ApprovalDecision.PROCEED:
                raise ConflictError(
                    f"Cannot start workflow: approval decision is "
                    f"'{run.approval.decision.value}', need 'proceed'"
                )

        # Persist secret pointer for retries / approve auto-start.
        if not run.connection_secret_arn:
            async def _save_secret() -> None:
                current = await self._repository.get_by_id_or_raise(run_id)
                current.connection_secret_arn = secret
                await self._repository.update(current)
                await self._session.commit()

            await with_txn_retry(_save_secret, on_retry=self._session.rollback)

        start_input = WorkflowStartInput(
            run_id=str(run_id),
            connection_secret_arn=secret,
            artifacts_bucket=self._aws_settings.run_artifacts_bucket,
        )

        try:
            execution = await start_workflow_execution(
                self._aws_clients,
                self._aws_settings,
                start_input,
            )
        except WorkflowExecutionError:
            logger.exception(
                "Step Functions start failed",
                extra={"run_id": str(run_id)},
            )
            raise

        async def _commit() -> MigrationRun:
            current = await self._repository.get_by_id_or_raise(run_id)
            if current.sfn_execution_arn and current.sfn_execution_arn != execution.execution_arn:
                raise ConflictError(
                    "Migration run already linked to a different workflow execution"
                )
            current.sfn_execution_arn = execution.execution_arn
            current.connection_secret_arn = secret
            current.workflow_status = _to_db_status(execution.status)
            current.workflow_started_at = (
                _parse_iso(execution.start_date) or datetime.now(tz=UTC)
            )
            if current.status in {
                MigrationRunStatus.PENDING,
                MigrationRunStatus.PREDICTING,
                MigrationRunStatus.AWAITING_APPROVAL,
            }:
                current.status = MigrationRunStatus.RUNNING
            updated = await self._repository.update(current)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        updated = await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Recorded Step Functions execution on migration run",
            extra={
                "run_id": str(run_id),
                "sfn_execution_arn": updated.sfn_execution_arn,
                "workflow_status": updated.workflow_status.value,
            },
        )
        return updated

    async def sync_status(self, run_id: uuid.UUID) -> MigrationRun:
        """Pull execution status from Step Functions and persist it."""
        run = await self._repository.get_by_id_or_raise(run_id)
        if not run.sfn_execution_arn:
            raise ValidationError(
                f"Migration run {run_id} has no Step Functions execution ARN"
            )

        try:
            execution = await describe_workflow_execution(
                self._aws_clients,
                run.sfn_execution_arn,
            )
        except WorkflowExecutionError:
            logger.exception(
                "Step Functions describe failed",
                extra={
                    "run_id": str(run_id),
                    "sfn_execution_arn": run.sfn_execution_arn,
                },
            )
            raise

        db_status = _to_db_status(execution.status)

        async def _commit() -> MigrationRun:
            current = await self._repository.get_by_id_or_raise(run_id)
            current.workflow_status = db_status
            if execution.start_date and current.workflow_started_at is None:
                current.workflow_started_at = _parse_iso(execution.start_date)
            if db_status in _TERMINAL_WORKFLOW:
                current.workflow_finished_at = (
                    _parse_iso(execution.stop_date) or datetime.now(tz=UTC)
                )
                if db_status == WorkflowStatus.SUCCEEDED:
                    if current.status == MigrationRunStatus.RUNNING:
                        current.status = MigrationRunStatus.COMPLETED
                elif current.status not in {
                    MigrationRunStatus.COMPLETED,
                    MigrationRunStatus.FAILED,
                }:
                    current.status = MigrationRunStatus.FAILED
            if execution.error or execution.cause or db_status == WorkflowStatus.FAILED:
                explain = dict(current.explainability or {})
                explain["workflow"] = {
                    "status": db_status.value,
                    "error": execution.error,
                    "cause": (execution.cause or "")[:2000] or None,
                    "sfn_execution_arn": current.sfn_execution_arn,
                }
                current.explainability = explain
            updated = await self._repository.update(current)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        updated = await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Synced workflow status",
            extra={
                "run_id": str(run_id),
                "sfn_execution_arn": updated.sfn_execution_arn,
                "workflow_status": updated.workflow_status.value,
                "run_status": updated.status.value,
            },
        )
        return updated
