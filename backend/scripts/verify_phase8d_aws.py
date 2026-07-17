"""Verify Phase 8D AWS integrations: Secrets Manager, S3, CloudWatch.

Exercises idempotent secret writes, cached reads, idempotent artifact uploads,
automatic log-group creation, and standard alarms.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from pydantic import SecretStr  # noqa: E402

from app.aws import (  # noqa: E402
    ArtifactStore,
    AwsClientFactory,
    CloudWatchObservability,
    SecretsService,
    correlation_context,
    get_aws_settings,
)
from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.schema_analysis.database_connection import (  # noqa: E402
    DatabaseConnection,
    SslMode,
)

logger = get_logger(__name__)


async def main() -> int:
    settings = get_aws_settings()
    setup_logging("INFO")

    if not settings.aws_enabled:
        print("FAIL: AWS_ENABLED=false", file=sys.stderr)
        return 1
    if not settings.run_artifacts_bucket:
        print("FAIL: RUN_ARTIFACTS_BUCKET is required", file=sys.stderr)
        return 1

    factory = AwsClientFactory(settings)
    secrets = SecretsService(
        factory,
        settings,
        cache_ttl_seconds=settings.secrets_cache_ttl_seconds,
    )
    artifacts = ArtifactStore(factory, settings)
    observability = CloudWatchObservability(factory, settings)

    run_id = str(uuid.uuid4())
    connection_id = f"phase8d-verify-{run_id[:8]}"

    try:
        with correlation_context(run_id=run_id, lambda_function_name="phase8d-verify"):
            logger.info("Phase 8D verification started")

            # --- Secrets Manager ---
            connection = DatabaseConnection(
                host="example.invalid",
                port=26257,
                database="verify_db",
                username="verify_user",
                password=SecretStr("verify-password-not-real"),
                ssl_mode=SslMode.REQUIRE,
            )
            arn1 = await secrets.store_customer_connection(connection_id, connection)
            arn2 = await secrets.store_customer_connection(connection_id, connection)
            if arn1 != arn2:
                print("FAIL: duplicate secret create returned different ARNs", file=sys.stderr)
                return 1
            print(f"OK secrets idempotent create/update arn={arn1}")

            loaded = await secrets.get_customer_connection(arn1)
            cached = await secrets.get_customer_connection(arn1)
            if loaded.host != connection.host or cached.database != connection.database:
                print("FAIL: secret round-trip mismatch", file=sys.stderr)
                return 1
            print("OK secrets retrieve + cache")

            # --- S3 artifacts ---
            snapshot = {
                "run_id": run_id,
                "table_count": 1,
                "schemas": [{"name": "public", "table_count": 1}],
            }
            up1 = await artifacts.put_schema_snapshot(run_id, snapshot)
            up2 = await artifacts.put_schema_snapshot(run_id, snapshot)
            if up1["uploaded"] is not True:
                print("FAIL: first schema upload should write", file=sys.stderr)
                return 1
            if up2["uploaded"] is not False:
                print("FAIL: second schema upload should skip duplicate", file=sys.stderr)
                return 1
            print(f"OK s3 schema artifact uri={up1['uri']}")

            report = {
                "run_id": run_id,
                "success": True,
                "duration_seconds": 1.23,
                "storage_mb": 0.0,
            }
            r1 = await artifacts.put_execution_report(run_id, report)
            r2 = await artifacts.put_execution_report(run_id, report)
            if r1["uploaded"] is not True or r2["uploaded"] is not False:
                print("FAIL: execution report idempotency", file=sys.stderr)
                return 1
            print(f"OK s3 execution report uri={r1['uri']}")

            # --- CloudWatch ---
            infra = await observability.ensure_infrastructure()
            print(
                "OK cloudwatch log groups="
                f"{len(infra['log_groups'])} alarms={len(infra['alarms'])}"
            )
            await observability.record_orphaned_shadow_clusters(0.0)
            print("OK cloudwatch orphan metric published (0)")

            # Cleanup verify secret (leave artifacts for inspection)
            await secrets.delete(arn1)
            print("OK secrets cleanup")

            logger.info("Phase 8D verification succeeded")
            print("\nAll Phase 8D AWS integrations verified.")
            return 0
    except Exception as exc:
        logger.exception("Phase 8D verification failed")
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        factory.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
