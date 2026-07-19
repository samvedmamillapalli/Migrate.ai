"""Human approval gate for Phase 9 — proceed starts the verify workflow."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_logger
from app.database.models import (
    Approval,
    ApprovalDecision,
    MigrationRun,
    MigrationRunStatus,
    PolicyDecision,
)
from app.database.retry import with_txn_retry
from app.repositories.approval_repository import ApprovalRepository
from app.repositories.migration_run_repository import MigrationRunRepository
from app.services.migration_run_service import MigrationRunService

if TYPE_CHECKING:
    from app.services.workflow_orchestration_service import WorkflowOrchestrationService

logger = get_logger(__name__)

_DECISION_TO_STATUS: dict[ApprovalDecision, MigrationRunStatus] = {
    ApprovalDecision.PROCEED: MigrationRunStatus.RUNNING,
    ApprovalDecision.ACCEPT_RECOMMENDED: MigrationRunStatus.COMPLETED,
    ApprovalDecision.CANCEL: MigrationRunStatus.FAILED,
}


class ApprovalService:
    """Record human decisions at awaiting_approval. Append-only audit records.

    Selecting the recommended plan ends the run (completed) and does **not**
    queue AI-generated SQL for execution. Proceed moves the run to running and
    starts the durable shadow verify workflow when configured.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        migration_run_repository: MigrationRunRepository,
        approval_repository: ApprovalRepository,
        migration_run_service: MigrationRunService,
        workflow_orchestration: WorkflowOrchestrationService | None = None,
        auto_start_workflow: bool = True,
    ) -> None:
        self._session = session
        self._runs = migration_run_repository
        self._approvals = approval_repository
        self._run_service = migration_run_service
        self._workflow = workflow_orchestration
        self._auto_start = auto_start_workflow

    async def approve(
        self,
        run_id: uuid.UUID,
        *,
        decision: ApprovalDecision,
        approver_identity: str,
        override_rationale: str | None = None,
        connection_secret_arn: str | None = None,
        start_workflow: bool | None = None,
    ) -> MigrationRun:
        identity = approver_identity.strip()
        if not identity:
            raise ValidationError("approver_identity must not be empty")

        rationale = override_rationale.strip() if override_rationale else None
        do_start = self._auto_start if start_workflow is None else start_workflow

        async def _commit() -> MigrationRun:
            run = await self._runs.get_by_id_or_raise(run_id, load_children=True)

            if run.status != MigrationRunStatus.AWAITING_APPROVAL:
                raise ConflictError(
                    f"Approvals are only accepted when status is "
                    f"awaiting_approval; current status is '{run.status.value}'"
                )

            if run.approval is not None:
                raise ConflictError(
                    f"MigrationRun {run_id} already has an approval record"
                )

            if (
                decision == ApprovalDecision.PROCEED
                and run.policy_decision == PolicyDecision.BLOCK
            ):
                if not rationale:
                    raise ValidationError(
                        "override_rationale is required when proceeding "
                        "against a policy_decision of block"
                    )

            if decision == ApprovalDecision.ACCEPT_RECOMMENDED:
                logger.info(
                    "User accepted recommended plan; ending run without execution",
                    extra={"run_id": str(run_id), "approver": identity},
                )

            if connection_secret_arn and connection_secret_arn.strip():
                run.connection_secret_arn = connection_secret_arn.strip()

            if (
                decision == ApprovalDecision.PROCEED
                and do_start
                and self._workflow is not None
            ):
                secret = (
                    (connection_secret_arn or "").strip()
                    or (run.connection_secret_arn or "").strip()
                )
                if not secret:
                    raise ValidationError(
                        "connection_secret_arn is required to start the verify "
                        "workflow after proceed (POST /discover first, or pass "
                        "connection_secret_arn on approve). Set start_workflow=false "
                        "to record proceed without starting Step Functions."
                    )

            new_status = _DECISION_TO_STATUS[decision]
            self._run_service._validate_status_transition(  # noqa: SLF001
                run.status,
                new_status,
            )

            approval = Approval(
                migration_run_id=run.id,
                approver_identity=identity,
                decision=decision,
                override_rationale=rationale,
            )
            await self._approvals.create(approval)

            run.status = new_status
            await self._runs.update(run)
            await self._session.commit()
            return await self._runs.get_by_id_or_raise(run_id, load_children=True)

        updated = await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Approval recorded",
            extra={
                "run_id": str(run_id),
                "decision": decision.value,
                "approver": identity,
                "new_status": updated.status.value,
                "had_override_rationale": bool(rationale),
            },
        )

        if (
            decision == ApprovalDecision.PROCEED
            and do_start
            and self._workflow is not None
        ):
            secret = (
                (connection_secret_arn or "").strip()
                or (updated.connection_secret_arn or "").strip()
            )
            if not secret:
                logger.warning(
                    "Proceed recorded but workflow not started: "
                    "connection_secret_arn missing on run",
                    extra={"run_id": str(run_id)},
                )
            else:
                try:
                    updated = await self._workflow.start_for_run(
                        run_id,
                        connection_secret_arn=secret,
                        require_prediction_and_approval=True,
                    )
                except Exception:
                    logger.exception(
                        "Failed to auto-start workflow after proceed",
                        extra={"run_id": str(run_id)},
                    )
                    # Leave status as running so operator can POST /start-workflow.

        return updated
