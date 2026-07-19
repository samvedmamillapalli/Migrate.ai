"""Live Bedrock + Phase 9 pipeline smoke test for the frontend path.

Uses BEDROCK_PREDICTION_MODEL_ID from .env (not the mock client).
Run from backend/:

  python scripts/verify_phase9_live_bedrock.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.aws.config import get_aws_settings
from app.database import DatabaseSessionManager
from app.database.models import MigrationRunStatus, SchemaDiscoveryStatus
from app.prediction.bedrock_client import AwsBedrockClient, BedrockAccessError
from app.prediction.predictor import PredictionEngine
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.prediction_repository import PredictionRepository
from app.schema_analysis.models import (
    ColumnMetadata,
    DatabaseMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.services.migration_run_service import MigrationRunService
from app.services.prediction_pipeline_service import PredictionPipelineService
from app.shadow.models import ScaleTier
from app.config import get_settings


def _sample_snapshot() -> DatabaseMetadata:
    users = TableMetadata(
        name="users",
        schema_name="public",
        column_count=2,
        columns=[
            ColumnMetadata(
                name="id",
                data_type="bigint",
                is_nullable=False,
                column_default=None,
                ordinal_position=1,
                is_primary_key=True,
            ),
            ColumnMetadata(
                name="email",
                data_type="text",
                is_nullable=True,
                column_default=None,
                ordinal_position=2,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[],
        indexes=[],
        constraints=[],
        estimated_row_count=50_000,
        estimated_size_bytes=50_000 * 64,
    )
    return DatabaseMetadata(
        database_name="demo",
        server_version="CockroachDB",
        schemas=[SchemaMetadata(name="public", tables=[users], table_count=1)],
        schema_count=1,
        table_count=1,
        inspected_at=datetime.now(timezone.utc),
    )


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def main() -> int:
    # Clear cached settings so a freshly edited .env is picked up.
    get_settings.cache_clear()
    get_aws_settings.cache_clear()

    settings = get_settings()
    aws = get_aws_settings()
    model_id = aws.bedrock_prediction_model_id
    region = aws.bedrock_region

    print("Phase 9 live Bedrock smoke test")
    print(f"  model_id: {model_id}")
    print(f"  region:   {region}")

    if not model_id:
        print("  [FAIL] BEDROCK_PREDICTION_MODEL_ID is empty")
        return 1

    # --- 1) Direct Bedrock converse call ---
    print("\n[1] Direct Bedrock JSON generation")
    try:
        client = AwsBedrockClient(settings=aws)
        text = client.generate_json(
            system_prompt=(
                "Return ONLY a JSON object with keys "
                'estimated_duration_seconds, estimated_storage_mb, rollback_risk, '
                "confidence_score, risk_explanation, key_assumptions, uncertainty_notes. "
                "Predictions are for a shadow cluster run. Units are absolute seconds and MB."
            ),
            user_prompt=(
                "Predict a shadow-run CREATE INDEX on users(email) at scale tier medium. "
                "Table has ~50000 rows."
            ),
            model_id=model_id,
        )
        print(f"  raw response length: {len(text)}")
        engine = PredictionEngine(client, model_id=model_id)
        # Reuse extract via a tiny validate path
        from app.prediction.bedrock_client import extract_json_object
        from app.prediction.models import ModelPredictionOutput

        parsed = ModelPredictionOutput.model_validate(extract_json_object(text))
        print(
            f"  [PASS] direct call "
            f"duration={parsed.estimated_duration_seconds}s "
            f"storage={parsed.estimated_storage_mb}MB "
            f"risk={parsed.rollback_risk.value}"
        )
    except BedrockAccessError as exc:
        print(f"  [FAIL] Bedrock access: {exc.message}")
        print(
            "  Fix: Bedrock console → Model access → request Anthropic Claude "
            f"in {region}, then retry."
        )
        return 1
    except Exception as exc:
        print(f"  [FAIL] {type(exc).__name__}: {exc}")
        # Common Claude-on-Bedrock fix: regional inference profile prefix
        if "inference profile" in str(exc).lower() or "on-demand" in str(exc).lower():
            alt = model_id if model_id.startswith("us.") else f"us.{model_id}"
            print(f"  Hint: try BEDROCK_PREDICTION_MODEL_ID={alt}")
        return 1

    # --- 2) Full pipeline (same path as frontend POST /runs/{id}/predict) ---
    print("\n[2] Full prediction pipeline (frontend path)")
    db = DatabaseSessionManager(settings.database_url.get_secret_value())
    try:
        async for session in db.session():
            run_repo = MigrationRunRepository(session)
            pred_repo = PredictionRepository(session)
            run_service = MigrationRunService(repository=run_repo, session=session)
            pipeline = PredictionPipelineService(
                session=session,
                migration_run_repository=run_repo,
                prediction_repository=pred_repo,
                migration_run_service=run_service,
                bedrock_client=client,
                prediction_model_id=model_id,
                recommendation_model_id=aws.bedrock_recommendation_model_id or model_id,
            )

            run = await run_service.create_migration_run(
                "CREATE INDEX idx_users_email ON users(email);"
            )
            run.schema_snapshot = _sample_snapshot().model_dump(
                mode="json",
                by_alias=True,
            )
            run.schema_discovery_status = SchemaDiscoveryStatus.SUCCEEDED
            await run_repo.update(run)
            await session.commit()

            updated = await pipeline.run_prediction_pipeline(
                run.id,
                scale_tier=ScaleTier.MEDIUM,
            )
            check(
                updated.status == MigrationRunStatus.AWAITING_APPROVAL,
                f"expected awaiting_approval, got {updated.status}",
            )
            check(updated.prediction is not None, "prediction missing")
            check(updated.recommendation is not None, "recommendation missing")
            check(updated.policy_decision is not None, "policy_decision missing")
            check(updated.explainability is not None, "explainability missing")
            pred = updated.prediction
            assert pred is not None
            check(pred.model_version.startswith("bedrock:"), "model_version")
            print(
                f"  [PASS] run={updated.id} status={updated.status.value} "
                f"policy={updated.policy_decision.value} "
                f"confidence={pred.confidence_score} "
                f"model={pred.model_version}"
            )
            print(
                "  Frontend: open /ui/, select this run (or create a new one), "
                "click Run prediction."
            )
            break
    finally:
        await db.close()

    print("\nRESULT: PASS — live Bedrock path works for Phase 9 / frontend")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
