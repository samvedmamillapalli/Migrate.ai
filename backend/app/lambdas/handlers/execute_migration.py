"""ExecuteMigration Lambda — run migration SQL on the shadow cluster."""

from __future__ import annotations

import os
from time import perf_counter
from typing import Any

from app.core.logging import get_logger
from app.database.models import ShadowCluster, ShadowClusterStatus
from app.lambdas.errors import LambdaHandlerError, LambdaValidationError
from app.lambdas.helpers import parse_run_id, shadow_secret_name
from app.lambdas.runtime import get_runtime, run_async, with_session
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.services.shadow_cluster_service import ShadowClusterService
from app.shadow.changefeed_watch import read_changefeed_events
from app.shadow.migration_runner import run_migration
from app.shadow.schema_snapshot import build_schema_diff

logger = get_logger(__name__)

# The seeded shadow schema always lands in `defaultdb` for real ccloud_api
# clusters — confirmed repeatedly against real provisioned clusters this
# session (schema-analysis connection logs report `"database": "defaultdb"`
# for every ccloud_api run).
_CCLOUD_API_SHADOW_DATABASE = "defaultdb"

# CockroachDB Changefeed live event stream (docs/cockroach_hookup.md
# §Changefeeds). On by default — flip to False to disable without touching
# the rest of this handler, same convention as the sidelined ccloud CLI /
# Agent Skills flags elsewhere in this codebase.
_CHANGEFEED_ENABLED = True


async def _run_blast_radius_investigation(
    *,
    shadow: ShadowCluster,
    migration_sql: str,
    schema_snapshot_before: dict[str, Any] | None,
    schema_snapshot_after: dict[str, Any] | None,
    row_sample_after: dict[str, Any] | None,
    session: Any = None,
) -> dict[str, Any] | None:
    """Best-effort: returns a ModelTrace-shaped dict, or None. Never raises —
    see app.shadow.blast_radius_investigator's own module docstring for why.
    Only runs for real ccloud_api clusters: a mock-provider scratch database
    has no distinct Cloud cluster ID to scope MCP to (see
    docs/COCKROACHDB_MCP_INTEGRATION_PLAN.md §5's non-goals) — skipped
    honestly rather than faked against the wrong cluster.
    """
    if shadow.provider != "cockroachdb_cloud_api" or not shadow.cluster_id:
        logger.info(
            "Skipping blast-radius investigation: not a real ccloud_api cluster",
            extra={"provider": shadow.provider},
        )
        return None
    if schema_snapshot_before is None and schema_snapshot_after is None:
        logger.info("Skipping blast-radius investigation: no schema snapshot captured")
        return None

    try:
        from app.config import get_settings
        from app.prediction.bedrock_client import AwsBedrockClient, MockBedrockClient
        from app.shadow.blast_radius_investigator import investigate
        from app.shadow.factory import resolve_ccloud_api_bearer_token

        settings = get_settings()
        runtime = get_runtime()
        aws = runtime.aws_settings

        if aws.bedrock_prediction_model_id:
            bedrock_client = AwsBedrockClient(settings=aws)
            model_id = aws.bedrock_prediction_model_id
        elif settings.environment.strip().lower() in {
            "development",
            "dev",
            "local",
            "test",
        }:
            bedrock_client = MockBedrockClient()
            model_id = "mock"
        else:
            logger.warning(
                "Skipping blast-radius investigation: no BEDROCK_PREDICTION_MODEL_ID "
                "outside dev/local"
            )
            return None

        api_secret = resolve_ccloud_api_bearer_token(settings)
        schema_diff = build_schema_diff(schema_snapshot_before, schema_snapshot_after)

        # Embedding client for the agent's search_prior_migrations tool. Same
        # mock-outside-dev posture as the Bedrock client above: if Titan isn't
        # reachable we simply don't offer the tool rather than advertising one
        # that errors on every call.
        embedding_client = None
        if session is not None:
            from app.memory.embedding_client import (
                AwsTitanEmbeddingClient,
                MockEmbeddingClient,
            )

            try:
                if aws.aws_enabled and aws.bedrock_embedding_model_id:
                    embedding_client = AwsTitanEmbeddingClient(settings=aws)
                elif settings.environment.strip().lower() in {
                    "development",
                    "dev",
                    "local",
                    "test",
                }:
                    embedding_client = MockEmbeddingClient()
            except Exception as exc:  # noqa: BLE001 - tool is optional enrichment
                logger.warning(
                    "Embedding client unavailable; search_prior_migrations "
                    "will not be offered",
                    extra={"error": f"{type(exc).__name__}: {exc}"},
                )

        return await investigate(
            bedrock_client=bedrock_client,
            model_id=model_id,
            cluster_id=shadow.cluster_id,
            database=_CCLOUD_API_SHADOW_DATABASE,
            api_secret=api_secret,
            mcp_base_url=settings.cockroach_mcp_url,
            migration_sql=migration_sql,
            schema_diff=schema_diff,
            row_sample_after=row_sample_after,
            session=session,
            embedding_client=embedding_client,
        )
    except Exception as exc:  # noqa: BLE001 - enrichment, never blocks the migration
        logger.warning(
            "Blast-radius investigation raised unexpectedly; skipping",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return None


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    from app.lambdas.runtime import handler_correlation

    with handler_correlation(event, context, function_name="execute-migration"):
        return run_async(_handle(event))


async def _handle(event: dict[str, Any]) -> dict[str, Any]:
    run_id = parse_run_id(event)
    runtime = get_runtime()
    settings = runtime.settings

    provision = event.get("provision_shadow_cluster") or {}
    shadow_secret_arn = (
        event.get("shadow_secret_arn")
        or provision.get("shadow_secret_arn")
        or shadow_secret_name(run_id)
    )

    logger.info("ExecuteMigration started", extra={"run_id": str(run_id)})

    async def _run(session):
        run_repo = MigrationRunRepository(session)
        shadow_repo = ShadowClusterRepository(session)
        shadow_service = ShadowClusterService(repository=shadow_repo, session=session)

        run = await run_repo.get_by_id_or_raise(run_id)
        shadow = await shadow_service.get_by_run(run_id)
        if shadow is None:
            raise LambdaValidationError(f"No shadow cluster for run_id={run_id}")

        if shadow.status in {ShadowClusterStatus.SEEDING, ShadowClusterStatus.READY}:
            await shadow_service.transition(shadow.id, ShadowClusterStatus.MIGRATING)
        elif shadow.status == ShadowClusterStatus.MIGRATING:
            pass
        else:
            raise LambdaValidationError(
                f"Shadow cluster not ready for migration: {shadow.status.value}"
            )

        connection_url = await runtime.secrets.get_string(str(shadow_secret_arn))
        t0 = perf_counter()
        outcome = await run_migration(
            connection_url,
            run.migration_sql,
            statement_timeout_ms=int(settings.shadow_migrate_timeout_seconds * 1000),
            run_id=str(run_id),
            changefeed_s3_bucket=os.environ.get("CHANGEFEED_S3_BUCKET") if _CHANGEFEED_ENABLED else None,
            changefeed_access_key_id=os.environ.get("CHANGEFEED_S3_ACCESS_KEY_ID") if _CHANGEFEED_ENABLED else None,
            changefeed_secret_access_key=os.environ.get("CHANGEFEED_S3_SECRET_ACCESS_KEY") if _CHANGEFEED_ENABLED else None,
        )
        migrate_ms = (
            outcome.duration_seconds * 1000.0
            if outcome.duration_seconds is not None
            else (perf_counter() - t0) * 1000.0
        )

        # CockroachDB Changefeed events (docs/cockroach_hookup.md §Changefeeds) —
        # augments job_watch, doesn't replace it; empty for migration types
        # (e.g. CREATE INDEX) that don't rewrite the base table, or when no
        # changefeed was created at all.
        changefeed_events: list[dict[str, Any]] = []
        if outcome.changefeed_job_id is not None:
            bucket = os.environ.get("CHANGEFEED_S3_BUCKET")
            if bucket:
                changefeed_events = read_changefeed_events(
                    runtime.aws_clients.s3(), bucket=bucket, run_id=str(run_id)
                )

        # Performance optimization: write stage timings + schema/row snapshots
        # in ONE transaction instead of two (merge_timings then
        # set_schema_snapshot were 2 transactions / 8 DB round-trips for the
        # same shadow row). Semantics are identical: timings keys are merged
        # (None values not written) and each snapshot field is only written
        # when provided — so passing all-None snapshots is a no-op, exactly
        # matching the old conditional guard below.
        await shadow_service.merge_timings_and_snapshot(
            shadow.id,
            timings={
                "migrate_ms": round(migrate_ms, 1),
                "job_watch": outcome.job_watch or [],
                "job_ids": outcome.job_ids or [],
                "job_progress": outcome.job_progress or [],
                "changefeed_events": changefeed_events,
                "changefeed_tables": outcome.changefeed_tables or [],
            },
            before=outcome.schema_snapshot_before,
            after=outcome.schema_snapshot_after,
            row_sample_before=outcome.row_sample_before,
            row_sample_after=outcome.row_sample_after,
        )

        # Real CockroachDB Managed MCP investigation — see
        # docs/COCKROACHDB_MCP_INTEGRATION_PLAN.md. Best-effort, additive:
        # never blocks the migration outcome above, which is already final.
        investigation_trace = await _run_blast_radius_investigation(
            shadow=shadow,
            migration_sql=run.migration_sql,
            schema_snapshot_before=outcome.schema_snapshot_before,
            schema_snapshot_after=outcome.schema_snapshot_after,
            row_sample_after=outcome.row_sample_after,
            # Reuse this handler's existing session rather than opening a
            # second one — it backs the agent's search_prior_migrations tool.
            session=session,
        )
        cockroachdb_tools_summary = (
            "MCP investigation unavailable for this run "
            "(mock provider, no Bedrock model configured, or MCP connection failed) "
            "— see docs/COCKROACHDB_MCP_INTEGRATION_PLAN.md."
        )
        if investigation_trace is not None:
            explainability = dict(run.explainability or {})
            bedrock_traces = dict(explainability.get("bedrock_traces") or {})
            bedrock_traces["blast_radius_investigation"] = investigation_trace
            explainability["bedrock_traces"] = bedrock_traces
            run.explainability = explainability
            await run_repo.update(run)
            await session.commit()
            verdict = (investigation_trace.get("final_parsed") or {}).get("verdict")
            tool_call_count = sum(
                len(a.get("tool_calls") or []) for a in investigation_trace["attempts"]
            )
            cockroachdb_tools_summary = (
                verdict
                or f"Real Managed MCP investigation ran ({tool_call_count} live tool "
                "calls) but produced no parsed verdict — see Model Traces for the raw response."
            )
        await shadow_service.merge_timings(
            shadow.id, cockroachdb_tools=cockroachdb_tools_summary
        )

        return {
            "run_id": str(run_id),
            "shadow_id": str(shadow.id),
            "success": outcome.success,
            "duration_seconds": outcome.duration_seconds,
            "storage_growth_mb": outcome.storage_growth_mb,
            "rollback_required": outcome.rollback_required,
            "error_message": outcome.error_message,
            "timed_out": outcome.timed_out,
            "job_watch": outcome.job_watch or [],
            "cockroachdb_tools": cockroachdb_tools_summary,
        }

    try:
        result = await with_session(runtime, _run)
    except LambdaValidationError:
        raise
    except Exception as exc:
        # Log the real cause before re-raising. `raise ... from exc` preserves
        # __cause__ in Python, but AWS Lambda's error serialization only walks
        # the outermost traceback, so CloudWatch/Step Functions show a
        # LambdaHandlerError whose stack stops at this very line — the actual
        # failure is invisible. That cost a long diagnosis on 2026-08-02;
        # logger.exception() here keeps the root cause in the log stream.
        logger.exception(
            "ExecuteMigration failed — root cause",
            extra={
                "run_id": str(run_id),
                "error_type": type(exc).__name__,
                "error": str(exc)[:2000],
            },
        )
        raise LambdaHandlerError(
            f"ExecuteMigration failed for run_id={run_id}: "
            f"{type(exc).__name__}: {exc}"[:900]
        ) from exc

    logger.info(
        "ExecuteMigration completed",
        extra={
            "run_id": str(run_id),
            "success": result.get("success"),
            "duration_seconds": result.get("duration_seconds"),
        },
    )
    return result
