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
    stop_workflow_execution,
)
from app.aws.workflow.models import WorkflowStatus as AwsWorkflowStatus
from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_logger
from app.database.models import CCloudAuditEvent, MigrationRun, MigrationRunStatus, WorkflowStatus
from app.database.retry import with_txn_retry
from app.repositories.ccloud_audit_event_repository import CCloudAuditEventRepository
from app.repositories.migration_run_repository import MigrationRunRepository
from app.services.github_notification_service import GithubNotificationService
from app.services.slack_helpers import derive_migration_name
from app.services.slack_notification_service import SlackNotificationService
from app.shadow.ccloud_cli_client import CCloudCliError, fetch_audit_events

logger = get_logger(__name__)

# ccloud CLI audit-trail corroboration (docs/cockroach_hookup.md §4), sidelined
# 2026-08-02 per user decision: real, tested to fail safely, but judged not
# impactful enough to a core feature to keep active. Code stays intact and
# tested — flip this back to True to re-enable, no other changes needed.
_CCLOUD_AUDIT_TRAIL_ENABLED = False

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
        slack_notifications: SlackNotificationService | None = None,
        github_notifications: GithubNotificationService | None = None,
    ) -> None:
        self._repository = repository
        self._session = session
        self._aws_clients = aws_clients
        self._aws_settings = aws_settings
        self._slack_notifications = slack_notifications
        self._github_notifications = github_notifications

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
        await self._notify_shadow_started(updated)
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
        just_became_terminal = False

        async def _commit() -> MigrationRun:
            nonlocal just_became_terminal
            current = await self._repository.get_by_id_or_raise(run_id)
            just_became_terminal = (
                db_status in _TERMINAL_WORKFLOW
                and current.workflow_status not in _TERMINAL_WORKFLOW
            )
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

        if just_became_terminal:
            await self._notify_terminal(updated)
            await self._notify_github_terminal(updated.id)

        if just_became_terminal and _CCLOUD_AUDIT_TRAIL_ENABLED:
            # ccloud CLI audit-trail corroboration (docs/cockroach_hookup.md §4):
            # fetch the Cloud control plane's own audit-log corroboration for
            # this run's shadow cluster, exactly once, right as the run
            # finishes. Sidelined — see _CCLOUD_AUDIT_TRAIL_ENABLED above.
            await self._fetch_ccloud_audit_trail(run_id)

        return updated

    async def _fetch_ccloud_audit_trail(self, run_id: uuid.UUID) -> None:
        try:
            full = await self._repository.get_by_id_or_raise(
                run_id, load_children=True
            )
            cluster = full.shadow_cluster
            if cluster is None:
                logger.info(
                    "Skipping ccloud audit-trail fetch: no shadow cluster on run",
                    extra={"run_id": str(run_id)},
                )
                return

            events = fetch_audit_events(
                starting_from=full.created_at,
                limit=50,
            )
            # The audit log is org-wide, not per-cluster; ccloud's exact JSON
            # shape for `audit list` isn't documented in --help, so match on
            # the cluster's own identifiers appearing anywhere in the raw
            # event payload rather than assuming a specific field name.
            needles = [v for v in (cluster.cluster_id, cluster.cluster_name) if v]
            matched = [
                e
                for e in events
                if any(needle in str(e) for needle in needles)
            ] if needles else events

            if not matched:
                logger.info(
                    "ccloud audit-trail fetch found no matching events",
                    extra={"run_id": str(run_id), "total_events": len(events)},
                )
                return

            rows = [
                CCloudAuditEvent(
                    migration_run_id=run_id,
                    event_type=str(
                        e.get("action") or e.get("eventType") or e.get("type") or "unknown"
                    ),
                    actor=(
                        str(e.get("actor") or e.get("principal") or e.get("user"))
                        if (e.get("actor") or e.get("principal") or e.get("user"))
                        else None
                    ),
                    occurred_at=_parse_iso(
                        e.get("timestamp") or e.get("occurredAt") or e.get("createdAt")
                    ),
                    raw_payload=e,
                )
                for e in matched
            ]
            await CCloudAuditEventRepository(self._session).bulk_create(rows)
            await self._session.commit()
            logger.info(
                "ccloud audit-trail persisted",
                extra={"run_id": str(run_id), "count": len(rows)},
            )
        except CCloudCliError as exc:
            logger.warning(
                "ccloud audit-trail fetch unavailable (non-fatal)",
                extra={"run_id": str(run_id), "error": f"{type(exc).__name__}: {exc}"},
            )
        except Exception as exc:  # noqa: BLE001 - enrichment, never fails the run
            logger.warning(
                "ccloud audit-trail fetch failed unexpectedly (non-fatal)",
                extra={"run_id": str(run_id), "error": f"{type(exc).__name__}: {exc}"},
            )

    async def _notify_shadow_started(self, run: MigrationRun) -> None:
        """Best-effort Slack notification after a fresh SFN start commits.

        Fires only on the non-idempotent path in ``start_for_run`` — when a
        run already has an execution ARN (idempotent re-entry), ``sync_status``
        is called instead and no shadow_started notification is sent. Any
        Slack lookup, token-decryption, network, or API failure is logged and
        swallowed so notification issues never affect the caller.
        """
        if self._slack_notifications is None:
            return
        try:
            await self._slack_notifications.send_shadow_started(
                owner_identity=run.owner_identity or "",
                # None -> SlackNotificationService resolves the channel:
                # DM the OAuth installer first, slack_default_channel only
                # as a fallback for rows predating authed_user_id.
                channel=None,
                run_id=run.id,
                migration_name=derive_migration_name(run.migration_sql),
                status=run.status.value,
                timestamp=run.workflow_started_at or datetime.now(tz=UTC),
                description=(
                    "Step Functions execution started. Shadow cluster "
                    "provisioning is underway."
                ),
            )
        except Exception:
            logger.warning(
                "Slack shadow_started notification failed",
                extra={"run_id": str(run.id)},
                exc_info=True,
            )

    async def _notify_terminal(
        self,
        run: MigrationRun,
        *,
        description_override: str | None = None,
    ) -> None:
        """Best-effort Slack notification when a run first becomes terminal.

        Dispatches on the run's final status: COMPLETED → shadow_completed,
        FAILED → shadow_failed. Guarded by ``just_became_terminal`` in
        ``sync_status`` so a later sync of an already-terminal run does not
        re-send. Any Slack failure is logged and swallowed.
        """
        if self._slack_notifications is None:
            return
        try:
            if run.status == MigrationRunStatus.COMPLETED:
                if description_override is None:
                    description = (
                        "Shadow migration executed and measured. Grading and "
                        "learned memory persisted."
                    )
                else:
                    description = description_override
                await self._slack_notifications.send_shadow_completed(
                    owner_identity=run.owner_identity or "",
                    channel=None,
                    run_id=run.id,
                    migration_name=derive_migration_name(run.migration_sql),
                    status=run.status.value,
                    timestamp=run.workflow_finished_at or datetime.now(tz=UTC),
                    description=description,
                )
            elif run.status == MigrationRunStatus.FAILED:
                if description_override is None:
                    description = (
                        f"Shadow workflow ended with {run.workflow_status.value}."
                    )
                else:
                    description = description_override
                await self._slack_notifications.send_shadow_failed(
                    owner_identity=run.owner_identity or "",
                    channel=None,
                    run_id=run.id,
                    migration_name=derive_migration_name(run.migration_sql),
                    status=run.status.value,
                    timestamp=run.workflow_finished_at or datetime.now(tz=UTC),
                    description=description,
                )
        except Exception:
            logger.warning(
                "Slack terminal notification failed",
                extra={"run_id": str(run.id)},
                exc_info=True,
            )

    async def _notify_github_terminal(self, run_id: uuid.UUID) -> None:
        """Best-effort predicted-vs-measured PR comment when a run first
        becomes terminal — docs/FUTURE_GITHUB_INTEGRATION_PLAN.md's terminal
        follow-up. No-ops for the vast majority of runs (no linked PR).

        Unlike ``_notify_terminal``, this needs ``prediction`` /
        ``execution_result`` / ``grade`` loaded to build the comparison
        table, which the caller's plain ``get_by_id_or_raise(run_id)`` row
        doesn't carry — fetched fresh here with ``load_children=True``.
        """
        if self._github_notifications is None:
            return
        try:
            full_run = await self._repository.get_by_id_or_raise(
                run_id, load_children=True
            )
            await self._github_notifications.send_terminal_result(full_run)
        except Exception:
            logger.warning(
                "GitHub terminal notification failed",
                extra={"run_id": str(run_id)},
                exc_info=True,
            )

    async def abort_for_run(
        self,
        run_id: uuid.UUID,
        *,
        reason: str = "Operator aborted shadow workflow",
    ) -> MigrationRun:
        """Stop a running Step Functions execution and tear down any shadow.

        StopExecution does not run the ASL Cleanup state, so we invoke the
        cleanup handler explicitly after stopping.
        """
        run = await self._repository.get_by_id_or_raise(run_id, load_children=True)
        if not run.sfn_execution_arn:
            raise ValidationError(
                f"Migration run {run_id} has no Step Functions execution to abort"
            )
        if run.workflow_status in _TERMINAL_WORKFLOW:
            return await self.sync_status(run_id)

        await stop_workflow_execution(
            self._aws_clients,
            run.sfn_execution_arn,
            error="OperatorAbort",
            cause=reason,
        )

        try:
            from app.lambdas import HANDLERS

            HANDLERS["cleanup"](
                {
                    "run_id": str(run_id),
                    "connection_secret_arn": run.connection_secret_arn,
                }
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Cleanup after abort failed; sweeper is the backstop",
                extra={"run_id": str(run_id)},
            )

        async def _commit() -> MigrationRun:
            current = await self._repository.get_by_id_or_raise(run_id)
            current.workflow_status = WorkflowStatus.ABORTED
            current.workflow_finished_at = datetime.now(tz=UTC)
            if current.status == MigrationRunStatus.RUNNING:
                current.status = MigrationRunStatus.FAILED
            explain = dict(current.explainability or {})
            explain["workflow"] = {
                "status": WorkflowStatus.ABORTED.value,
                "error": "OperatorAbort",
                "cause": reason[:2000],
                "sfn_execution_arn": current.sfn_execution_arn,
            }
            current.explainability = explain
            updated = await self._repository.update(current)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        updated = await with_txn_retry(_commit, on_retry=self._session.rollback)
        if updated.status == MigrationRunStatus.FAILED:
            await self._notify_terminal(
                updated,
                description_override=f"Shadow workflow aborted by operator: {reason}",
            )
            await self._notify_github_terminal(updated.id)
        return updated
