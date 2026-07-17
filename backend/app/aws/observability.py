"""CloudWatch observability: log groups, metrics, and alarms.

Creates log groups automatically. Emits correlated metrics for cleanup failures
and orphaned shadow clusters, and ensures matching alarms exist.
"""

from __future__ import annotations

import asyncio
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.aws.clients import AwsClientFactory
from app.aws.config import AwsSettings
from app.aws.exceptions import AwsError
from app.core.logging import get_logger

logger = get_logger(__name__)

METRIC_CLEANUP_FAILED = "CleanupFailed"
METRIC_ORPHANED_SHADOW_CLUSTERS = "OrphanedShadowClusters"
ALARM_CLEANUP_FAILED = "migration-oracle-cleanup-failed"
ALARM_ORPHANED_CLUSTERS = "migration-oracle-orphaned-shadow-clusters"


class ObservabilityError(AwsError):
    """Raised when CloudWatch operations fail."""


class CloudWatchObservability:
    """Ensure log groups/alarms and publish workflow metrics."""

    def __init__(
        self,
        factory: AwsClientFactory,
        settings: AwsSettings | None = None,
    ) -> None:
        self._factory = factory
        self._settings = settings or factory.settings

    def _logs(self):
        return self._factory.logs()

    def _cloudwatch(self):
        return self._factory.cloudwatch()

    @property
    def namespace(self) -> str:
        return self._settings.cloudwatch_namespace

    @property
    def primary_log_group(self) -> str:
        return (
            self._settings.cloudwatch_log_group
            or "/migration-oracle/application"
        )

    def lambda_log_group(self, function_suffix: str) -> str:
        prefix = self._settings.lambda_function_prefix
        return f"/migration-oracle/lambda/{prefix}-{function_suffix}"

    def workflow_log_group(self) -> str:
        return "/migration-oracle/workflow"

    def ensure_log_group_sync(
        self,
        log_group_name: str,
        *,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        retention = retention_days or self._settings.cloudwatch_log_retention_days
        client = self._logs()
        created = False
        try:
            client.create_log_group(logGroupName=log_group_name)
            created = True
            logger.info(
                "Created CloudWatch log group",
                extra={"log_group": log_group_name},
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in {"ResourceAlreadyExistsException", "ResourceAlreadyExists"}:
                raise ObservabilityError(
                    f"Unable to create log group {log_group_name!r} ({code})"
                ) from exc

        try:
            client.put_retention_policy(
                logGroupName=log_group_name,
                retentionInDays=retention,
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            # Retention is best-effort; group existence is required.
            logger.warning(
                "Unable to set log group retention",
                extra={"log_group": log_group_name, "error_code": code},
            )

        return {"log_group": log_group_name, "created": created, "retention_days": retention}

    async def ensure_log_group(
        self,
        log_group_name: str,
        *,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.ensure_log_group_sync,
            log_group_name,
            retention_days=retention_days,
        )

    async def ensure_standard_log_groups(self) -> list[dict[str, Any]]:
        groups = [
            self.primary_log_group,
            self.workflow_log_group(),
            self.lambda_log_group("discover-schema"),
            self.lambda_log_group("provision-shadow-cluster"),
            self.lambda_log_group("load-schema"),
            self.lambda_log_group("execute-migration"),
            self.lambda_log_group("collect-metrics"),
            self.lambda_log_group("persist-results"),
            self.lambda_log_group("cleanup"),
        ]
        results = []
        for name in groups:
            results.append(await self.ensure_log_group(name))
        return results

    def put_metric_sync(
        self,
        metric_name: str,
        value: float,
        *,
        unit: str = "Count",
        dimensions: dict[str, str] | None = None,
    ) -> None:
        metric: dict[str, Any] = {
            "MetricName": metric_name,
            "Value": value,
            "Unit": unit,
        }
        if dimensions:
            metric["Dimensions"] = [
                {"Name": key, "Value": str(val)}
                for key, val in dimensions.items()
            ]
        try:
            self._cloudwatch().put_metric_data(
                Namespace=self.namespace,
                MetricData=[metric],
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ObservabilityError(
                f"Unable to put metric {metric_name!r}"
            ) from exc
        logger.info(
            "Published CloudWatch metric",
            extra={
                "namespace": self.namespace,
                "metric_name": metric_name,
                "value": value,
                **(dimensions or {}),
            },
        )

    async def put_metric(
        self,
        metric_name: str,
        value: float,
        *,
        unit: str = "Count",
        dimensions: dict[str, str] | None = None,
    ) -> None:
        await asyncio.to_thread(
            self.put_metric_sync,
            metric_name,
            value,
            unit=unit,
            dimensions=dimensions,
        )

    async def record_cleanup_failed(self, *, run_id: str) -> None:
        await self.put_metric(
            METRIC_CLEANUP_FAILED,
            1.0,
            dimensions={"RunId": run_id},
        )
        # Also publish undimensioned series for the alarm.
        await self.put_metric(METRIC_CLEANUP_FAILED, 1.0)

    async def record_orphaned_shadow_clusters(self, count: float) -> None:
        await self.put_metric(METRIC_ORPHANED_SHADOW_CLUSTERS, float(count))

    def ensure_alarm_sync(
        self,
        *,
        alarm_name: str,
        metric_name: str,
        threshold: float,
        comparison_operator: str,
        period_seconds: int,
        evaluation_periods: int,
        statistic: str,
        treat_missing_data: str = "notBreaching",
        description: str,
    ) -> dict[str, Any]:
        try:
            self._cloudwatch().put_metric_alarm(
                AlarmName=alarm_name,
                AlarmDescription=description,
                Namespace=self.namespace,
                MetricName=metric_name,
                Statistic=statistic,
                Period=period_seconds,
                EvaluationPeriods=evaluation_periods,
                Threshold=threshold,
                ComparisonOperator=comparison_operator,
                TreatMissingData=treat_missing_data,
                ActionsEnabled=False,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ObservabilityError(
                f"Unable to ensure alarm {alarm_name!r}"
            ) from exc
        logger.info(
            "Ensured CloudWatch alarm",
            extra={
                "alarm_name": alarm_name,
                "metric_name": metric_name,
                "threshold": threshold,
                "period_seconds": period_seconds,
            },
        )
        return {
            "alarm_name": alarm_name,
            "metric_name": metric_name,
            "threshold": threshold,
        }

    async def ensure_alarm(self, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self.ensure_alarm_sync, **kwargs)

    async def ensure_standard_alarms(self) -> list[dict[str, Any]]:
        """Create/update alarms with sensible thresholds for demo ops."""
        cleanup = await self.ensure_alarm(
            alarm_name=ALARM_CLEANUP_FAILED,
            metric_name=METRIC_CLEANUP_FAILED,
            threshold=float(self._settings.alarm_cleanup_failed_threshold),
            comparison_operator="GreaterThanOrEqualToThreshold",
            period_seconds=self._settings.alarm_cleanup_failed_period_seconds,
            evaluation_periods=self._settings.alarm_cleanup_failed_evaluation_periods,
            statistic="Sum",
            description=(
                "Fires when shadow-cluster cleanup fails at least once "
                "within the evaluation window"
            ),
        )
        orphans = await self.ensure_alarm(
            alarm_name=ALARM_ORPHANED_CLUSTERS,
            metric_name=METRIC_ORPHANED_SHADOW_CLUSTERS,
            threshold=float(self._settings.alarm_orphaned_clusters_threshold),
            comparison_operator="GreaterThanOrEqualToThreshold",
            period_seconds=self._settings.alarm_orphaned_clusters_period_seconds,
            evaluation_periods=(
                self._settings.alarm_orphaned_clusters_evaluation_periods
            ),
            statistic="Maximum",
            description=(
                "Fires when the orphan sweeper reports one or more "
                "active shadow clusters past max lifetime"
            ),
        )
        return [cleanup, orphans]

    async def ensure_infrastructure(self) -> dict[str, Any]:
        log_groups = await self.ensure_standard_log_groups()
        alarms = await self.ensure_standard_alarms()
        return {"log_groups": log_groups, "alarms": alarms}
