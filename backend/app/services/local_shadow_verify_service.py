"""Local (in-process) shadow verify when Step Functions is not deployed.

Runs the same Lambda handlers as the durable workflow, with
``LAMBDA_LOCAL_MODE=1`` and ``SHADOW_PROVIDER=mock``, so developers can
exercise predict → approve → verify → grade → remember without
``MIGRATION_WORKFLOW_ARN``.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_logger
from app.database.models import (
    ApprovalDecision,
    MigrationRun,
    MigrationRunStatus,
    WorkflowStatus,
)
from app.database.retry import with_txn_retry
from app.lambdas import HANDLERS
from app.lambdas.helpers import connection_from_database_url
from app.lambdas.runtime import get_runtime, reset_runtime
from app.repositories.migration_run_repository import MigrationRunRepository
from app.services.pipeline_progress import set_progress

logger = get_logger(__name__)


def _prog(run_id: uuid.UUID, stage: str, message: str, percent: int) -> None:
    set_progress(run_id, stage=stage, message=message, percent=percent)


class LocalShadowVerifyService:
    """In-process mock-shadow closed loop for development / demo without SFN."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        repository: MigrationRunRepository,
    ) -> None:
        self._session = session
        self._runs = repository

    async def verify_run(self, run_id: uuid.UUID) -> MigrationRun:
        run = await self._runs.get_by_id_or_raise(run_id, load_children=True)

        if run.status in {MigrationRunStatus.COMPLETED, MigrationRunStatus.FAILED}:
            raise ConflictError(
                f"Cannot local-verify terminal run status={run.status.value}"
            )
        if run.prediction is None:
            raise ConflictError(
                "Prediction is required before local verify (POST /predict first)"
            )
        if run.approval is None:
            raise ConflictError(
                "Approval is required before local verify (POST /approve proceed first)"
            )
        if run.approval.decision != ApprovalDecision.PROCEED:
            raise ConflictError(
                f"Local verify requires decision=proceed; got "
                f"'{run.approval.decision.value}'"
            )
        if run.execution_result is not None:
            # Idempotent: already verified.
            return await self._finalize(run_id, already_done=True)

        results = await self._run_handler_chain(run_id)
        logger.info(
            "Local shadow verify completed",
            extra={
                "run_id": str(run_id),
                "execute_success": results.get("execute_migration", {}).get("success"),
                "graded": "execution_result_id" in (results.get("persist_results") or {}),
            },
        )
        return await self._finalize(run_id, already_done=False, step_results=results)

    async def _finalize(
        self,
        run_id: uuid.UUID,
        *,
        already_done: bool,
        step_results: dict[str, Any] | None = None,
    ) -> MigrationRun:
        async def _commit() -> MigrationRun:
            current = await self._runs.get_by_id_or_raise(run_id, load_children=True)
            if current.status == MigrationRunStatus.RUNNING or (
                current.status == MigrationRunStatus.AWAITING_APPROVAL
            ):
                current.status = MigrationRunStatus.COMPLETED
            current.workflow_status = WorkflowStatus.SUCCEEDED
            if current.workflow_started_at is None:
                current.workflow_started_at = datetime.now(tz=UTC)
            current.workflow_finished_at = datetime.now(tz=UTC)
            if not current.sfn_execution_arn:
                current.sfn_execution_arn = f"local://verify/{run_id}"
            # Keep a small breadcrumb for the UI without inventing graded history.
            explain = dict(current.explainability or {})
            explain["local_verify"] = {
                "mode": "mock_shadow",
                "already_done": already_done,
                "note": (
                    "In-process mock shadow verify (no Step Functions). "
                    "Deploy MIGRATION_WORKFLOW_ARN for durable AWS verify."
                ),
                "steps": list((step_results or {}).keys()) if step_results else None,
            }
            current.explainability = explain
            updated = await self._runs.update(current)
            await self._session.commit()
            return await self._runs.get_by_id_or_raise(run_id, load_children=True)

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

    async def _run_handler_chain(self, run_id: uuid.UUID) -> dict[str, Any]:
        # Force local mock provider for this process invocation.
        os.environ["LAMBDA_LOCAL_MODE"] = "1"
        prev_provider = os.environ.get("SHADOW_PROVIDER")
        os.environ["SHADOW_PROVIDER"] = "mock"
        reset_runtime()

        try:
            settings = get_settings()
            runtime = get_runtime()
            connection = connection_from_database_url(
                settings.database_url.get_secret_value()
            )
            secret_payload = {
                "host": connection.host,
                "port": connection.port,
                "database": connection.database,
                "username": connection.username,
                "password": connection.password.get_secret_value(),
                "ssl_mode": connection.ssl_mode.value,
            }
            secret_arn = await runtime.secrets.put_json(
                f"migration-oracle/connections/{run_id}",
                secret_payload,
            )

            # Ensure run is marked running before handlers.
            async def _mark_running() -> None:
                current = await self._runs.get_by_id_or_raise(run_id)
                if current.status == MigrationRunStatus.AWAITING_APPROVAL:
                    current.status = MigrationRunStatus.RUNNING
                if current.workflow_status == WorkflowStatus.NOT_STARTED:
                    current.workflow_status = WorkflowStatus.RUNNING
                if current.workflow_started_at is None:
                    current.workflow_started_at = datetime.now(tz=UTC)
                current.connection_secret_arn = secret_arn
                await self._runs.update(current)
                await self._session.commit()

            await with_txn_retry(_mark_running, on_retry=self._session.rollback)

            base: dict[str, Any] = {
                "run_id": str(run_id),
                "connection_secret_arn": secret_arn,
                "artifacts_bucket": runtime.settings.shadow_app_tag,
            }
            sr: dict[str, Any] = {}
            _prog(run_id, "discover", "Local verify: discover schema…", 15)
            sr["discover_schema"] = HANDLERS["discover-schema"]({**base}, None)
            _prog(run_id, "provision", "Local verify: provision mock shadow…", 30)
            sr["provision_shadow_cluster"] = HANDLERS["provision-shadow-cluster"](
                {**base, "discover_schema": sr["discover_schema"]}, None
            )
            prov = sr["provision_shadow_cluster"] or {}
            _prog(
                run_id,
                "provision",
                f"Shadow ready · name={prov.get('cluster_name') or '?'} · "
                f"id={prov.get('cluster_id') or prov.get('shadow_id') or '?'} · "
                f"status={prov.get('status') or '?'}",
                35,
            )
            _prog(run_id, "load", "Local verify: load schema onto shadow…", 45)
            sr["load_schema"] = HANDLERS["load-schema"](
                {
                    **base,
                    "provision_shadow_cluster": sr["provision_shadow_cluster"],
                },
                None,
            )
            _prog(run_id, "execute", "Local verify: execute migration SQL…", 60)
            sr["execute_migration"] = HANDLERS["execute-migration"](
                {
                    **base,
                    "provision_shadow_cluster": sr["provision_shadow_cluster"],
                    "load_schema": sr["load_schema"],
                },
                None,
            )
            _prog(run_id, "metrics", "Local verify: collect metrics…", 75)
            sr["collect_metrics"] = HANDLERS["collect-metrics"](
                {**base, "execute_migration": sr["execute_migration"]}, None
            )
            _prog(run_id, "persist", "Local verify: persist + grade + remember…", 88)
            sr["persist_results"] = HANDLERS["persist-results"](
                {**base, "step_results": sr}, None
            )
            _prog(run_id, "cleanup", "Local verify: cleanup shadow…", 95)
            sr["cleanup"] = HANDLERS["cleanup"](
                {
                    **base,
                    "outcome": {"workflow_failed": False},
                    "step_results": sr,
                },
                None,
            )
            _prog(run_id, "done", "Local verify complete", 100)

            if not sr["persist_results"].get("execution_result_id"):
                raise ValidationError("Local verify did not persist an execution result")
            return sr
        finally:
            if prev_provider is None:
                os.environ.pop("SHADOW_PROVIDER", None)
            else:
                os.environ["SHADOW_PROVIDER"] = prev_provider
            reset_runtime()


__all__ = ["LocalShadowVerifyService"]
