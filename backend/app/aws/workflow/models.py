"""Step Functions workflow models and constants (Phase 8B)."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class WorkflowStatus(str, enum.Enum):
    """Durable workflow status persisted on MigrationRun (CockroachDB)."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ABORTED = "aborted"


# ASL state names — keep in sync with infra/stepfunctions/migration_workflow.asl.json
WORKFLOW_TASK_STATES: tuple[str, ...] = (
    "DiscoverSchema",
    "ProvisionShadowCluster",
    "LoadSchema",
    "ExecuteMigration",
    "CollectMetrics",
    "PersistResults",
    "Cleanup",
)

WORKFLOW_CONTROL_STATES: tuple[str, ...] = (
    "MarkSucceeded",
    "MarkFailed",
    "ChooseOutcome",
    "WorkflowSucceeded",
    "WorkflowFailed",
    "CleanupFailed",
)

# Substitution keys in the ASL template → Lambda function name suffixes
LAMBDA_SUBSTITUTIONS: dict[str, str] = {
    "DiscoverSchemaFunctionArn": "discover-schema",
    "ProvisionShadowClusterFunctionArn": "provision-shadow-cluster",
    "LoadSchemaFunctionArn": "load-schema",
    "ExecuteMigrationFunctionArn": "execute-migration",
    "CollectMetricsFunctionArn": "collect-metrics",
    "PersistResultsFunctionArn": "persist-results",
    "CleanupFunctionArn": "cleanup",
}

SFN_STATUS_TO_WORKFLOW: dict[str, WorkflowStatus] = {
    "RUNNING": WorkflowStatus.RUNNING,
    "SUCCEEDED": WorkflowStatus.SUCCEEDED,
    "FAILED": WorkflowStatus.FAILED,
    "TIMED_OUT": WorkflowStatus.TIMED_OUT,
    "ABORTED": WorkflowStatus.ABORTED,
}


@dataclass(frozen=True, slots=True)
class WorkflowStartInput:
    """Payload passed into the state machine. Credentials live in Secrets Manager only."""

    run_id: str
    connection_secret_arn: str
    artifacts_bucket: str

    def to_execution_input(self) -> dict[str, Any]:
        # error/outcome seeded so Cleanup Parameters can always Path-reference them.
        return {
            "run_id": self.run_id,
            "connection_secret_arn": self.connection_secret_arn,
            "artifacts_bucket": self.artifacts_bucket,
            "step_results": {},
            "error": None,
            "outcome": None,
        }


@dataclass(frozen=True, slots=True)
class WorkflowExecutionRef:
    """Identifiers returned after starting or describing an execution."""

    execution_arn: str
    execution_name: str
    status: WorkflowStatus
    state_machine_arn: str | None = None
    start_date: str | None = None
    stop_date: str | None = None
    error: str | None = None
    cause: str | None = None
