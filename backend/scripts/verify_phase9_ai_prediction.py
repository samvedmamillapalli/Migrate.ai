"""Phase 9 verification: policy → prediction → recommendation → approval gate.

Runs end-to-end with an injectable MockBedrockClient (no live Bedrock access).
Requires DATABASE_URL pointing at CockroachDB (same as earlier phase scripts).

Usage (from backend/):
  python scripts/verify_phase9_ai_prediction.py
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from datetime import datetime, timezone
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings
from app.core.exceptions import ConflictError, ValidationError
from app.database import DatabaseSessionManager
from app.database.models import (
    ApprovalDecision,
    MigrationRunStatus,
    PolicyDecision,
    SchemaDiscoveryStatus,
)
from app.policy import PolicyEngine, analyze_migration, get_policy_file
from app.prediction import (
    MockBedrockClient,
    PredictionEngine,
    StubMemoryRetrieval,
    adjust_confidence,
)
from app.prediction.predictor import reset_repair_retry_count
from app.repositories.approval_repository import ApprovalRepository
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.prediction_repository import PredictionRepository
from app.schema_analysis.models import (
    ColumnMetadata,
    DatabaseMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.services.approval_service import ApprovalService
from app.services.migration_run_service import MigrationRunService
from app.services.prediction_pipeline_service import PredictionPipelineService
from app.shadow.models import ScaleTier


class CheckError(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


def _sample_snapshot(*, users_rows: int = 5_000_000) -> DatabaseMetadata:
    users = TableMetadata(
        name="users",
        schema_name="public",
        column_count=3,
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
            ColumnMetadata(
                name="age",
                data_type="integer",
                is_nullable=True,
                column_default=None,
                ordinal_position=3,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[],
        indexes=[],
        constraints=[],
        estimated_row_count=users_rows,
        estimated_size_bytes=users_rows * 64,
    )
    return DatabaseMetadata(
        database_name="demo",
        server_version="CockroachDB",
        schemas=[
            SchemaMetadata(name="public", tables=[users], table_count=1),
        ],
        schema_count=1,
        table_count=1,
        inspected_at=datetime.now(timezone.utc),
    )


def verify_policy_layer() -> dict[str, Any]:
    policy = get_policy_file()
    check(policy.version == 1, "policy version")
    check("drop_table" in policy.rules, "drop_table rule missing")

    snapshot = _sample_snapshot(users_rows=5_000_000)
    engine = PolicyEngine(policy)

    # DROP TABLE → block
    drop = engine.analyze("DROP TABLE users;", snapshot)
    check(drop.policy_decision.value == "block", f"drop decision={drop.policy_decision}")
    check(any(f.rule_id == "drop_table" for f in drop.risk_flags), "drop_table finding")
    check(drop.requires_manual_review, "drop requires review")

    # CREATE INDEX severity escalates with row count
    idx = engine.analyze("CREATE INDEX idx_users_email ON users(email);", snapshot)
    check(any(f.rule_id == "index_creation" for f in idx.risk_flags), "index finding")
    idx_finding = next(f for f in idx.risk_flags if f.rule_id == "index_creation")
    check(idx_finding.severity.value == "high", f"index severity={idx_finding.severity}")
    check(idx_finding.row_count == 5_000_000, "index row_count")

    # Parse failure → flagged, not crash, not silent allow
    bad = analyze_migration("THIS IS NOT SQL!!!")
    check(bad.parse_failed, "parse_failed flag")
    check(bad.requires_manual_review, "parse requires review")
    check(
        bad.policy_decision.value in {"allow_with_warning", "block"},
        f"parse decision too permissive: {bad.policy_decision}",
    )
    check(any(f.rule_id == "parse_failure" for f in bad.risk_flags), "parse finding")

    # Unknown table row count called out
    unknown = engine.analyze(
        "CREATE INDEX idx_x ON missing_table(x);",
        snapshot,
    )
    unk = next(f for f in unknown.risk_flags if f.rule_id == "index_creation")
    check(not unk.row_count_known, "unknown table should mark row_count unknown")
    check("unknown" in unk.explanation.lower(), "explanation mentions unknown")

    return {
        "drop_decision": drop.policy_decision.value,
        "index_severity": idx_finding.severity.value,
        "parse_failed": bad.parse_failed,
    }


async def verify_pipeline_and_approval(database_url: str) -> dict[str, Any]:
    reset_repair_retry_count()
    db = DatabaseSessionManager(database_url)
    mock = MockBedrockClient()
    results: dict[str, Any] = {}

    try:
        async for session in db.session():
            run_repo = MigrationRunRepository(session)
            pred_repo = PredictionRepository(session)
            approval_repo = ApprovalRepository(session)
            run_service = MigrationRunService(repository=run_repo, session=session)
            pipeline = PredictionPipelineService(
                session=session,
                migration_run_repository=run_repo,
                prediction_repository=pred_repo,
                migration_run_service=run_service,
                bedrock_client=mock,
                prediction_model_id="mock-claude-sonnet",
                recommendation_model_id="mock-claude-sonnet",
                memory_retrieval=StubMemoryRetrieval(),
            )
            approval_service = ApprovalService(
                session=session,
                migration_run_repository=run_repo,
                approval_repository=approval_repo,
                migration_run_service=run_service,
            )

            # --- Happy path: index creation ---
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
                scale_tier=ScaleTier.LARGE,
            )
            check(
                updated.status == MigrationRunStatus.AWAITING_APPROVAL,
                f"expected awaiting_approval, got {updated.status}",
            )
            check(updated.prediction is not None, "prediction missing")
            check(updated.recommendation is not None, "recommendation missing")
            check(updated.explainability is not None, "explainability missing")
            check(updated.policy_decision is not None, "policy_decision missing")

            pred = updated.prediction
            assert pred is not None
            check(pred.estimated_duration_seconds == 42.0, "duration units")
            check(pred.estimated_storage_mb == 128.0, "storage units")
            check(
                pred.raw_confidence_score > pred.confidence_score,
                "confidence should be reduced from raw (stub memory)",
            )
            check(
                any(
                    a.get("reason_code") == "weak_retrieval"
                    for a in pred.confidence_adjustments
                ),
                "weak_retrieval adjustment missing",
            )
            check(
                updated.explainability["prediction"]["prediction_target"]
                == "shadow_run_only",
                "explainability must state shadow target",
            )
            check(
                updated.explainability["memory"]["retrieved_count"] == 0,
                "memory stub should be empty in explainability",
            )
            check(
                len(mock.calls) >= 2,
                "expected separate prediction + recommendation calls",
            )

            results["happy_run_id"] = str(run.id)
            results["confidence_raw"] = pred.raw_confidence_score
            results["confidence_adjusted"] = pred.confidence_score

            # Wrong-state approval rejection (use a fresh pending run)
            pending = await run_service.create_migration_run("SELECT 1;")
            try:
                await approval_service.approve(
                    pending.id,
                    decision=ApprovalDecision.PROCEED,
                    approver_identity="verifier",
                )
                raise CheckError("wrong-state approval should have been rejected")
            except ConflictError:
                pass
            results["wrong_state_rejected"] = True

            # Block override requires rationale
            block_run = await run_service.create_migration_run("DROP TABLE users;")
            block_run.schema_snapshot = _sample_snapshot().model_dump(
                mode="json",
                by_alias=True,
            )
            block_run.schema_discovery_status = SchemaDiscoveryStatus.SUCCEEDED
            await run_repo.update(block_run)
            await session.commit()

            blocked = await pipeline.run_prediction_pipeline(block_run.id)
            check(
                blocked.policy_decision == PolicyDecision.BLOCK,
                f"expected block, got {blocked.policy_decision}",
            )
            check(
                blocked.status == MigrationRunStatus.AWAITING_APPROVAL,
                "blocked run still awaits approval",
            )

            try:
                await approval_service.approve(
                    blocked.id,
                    decision=ApprovalDecision.PROCEED,
                    approver_identity="verifier",
                    override_rationale=None,
                )
                raise CheckError("block override without rationale should fail")
            except ValidationError:
                pass

            overridden = await approval_service.approve(
                blocked.id,
                decision=ApprovalDecision.PROCEED,
                approver_identity="verifier@example.com",
                override_rationale=(
                    "Emergency hotfix with verified backup restore plan."
                ),
            )
            check(
                overridden.status == MigrationRunStatus.RUNNING,
                f"proceed should → running, got {overridden.status}",
            )
            check(overridden.approval is not None, "approval record missing")
            check(
                overridden.approval.override_rationale is not None,
                "override rationale not persisted",
            )
            results["block_override_ok"] = True

            # Accept recommended plan → completed, no shadow
            rec_run = await run_service.create_migration_run(
                "ALTER TABLE users ALTER COLUMN email SET NOT NULL;"
            )
            rec_run.schema_snapshot = _sample_snapshot(users_rows=100).model_dump(
                mode="json",
                by_alias=True,
            )
            rec_run.schema_discovery_status = SchemaDiscoveryStatus.SUCCEEDED
            await run_repo.update(rec_run)
            await session.commit()

            rec_updated = await pipeline.run_prediction_pipeline(rec_run.id)
            accepted = await approval_service.approve(
                rec_updated.id,
                decision=ApprovalDecision.ACCEPT_RECOMMENDED,
                approver_identity="verifier",
            )
            check(
                accepted.status == MigrationRunStatus.COMPLETED,
                f"accept_recommended should → completed, got {accepted.status}",
            )
            check(
                accepted.shadow_cluster is None,
                "accept_recommended must not provision a shadow cluster",
            )
            results["accept_recommended_ok"] = True

            # Cancel → failed
            cancel_run = await run_service.create_migration_run(
                "CREATE INDEX idx2 ON users(age);"
            )
            cancel_run.schema_snapshot = _sample_snapshot(users_rows=100).model_dump(
                mode="json",
                by_alias=True,
            )
            cancel_run.schema_discovery_status = SchemaDiscoveryStatus.SUCCEEDED
            await run_repo.update(cancel_run)
            await session.commit()
            cancel_updated = await pipeline.run_prediction_pipeline(cancel_run.id)
            cancelled = await approval_service.approve(
                cancel_updated.id,
                decision=ApprovalDecision.CANCEL,
                approver_identity="verifier",
            )
            check(
                cancelled.status == MigrationRunStatus.FAILED,
                f"cancel should → failed, got {cancelled.status}",
            )
            results["cancel_ok"] = True

            # Repair retry path (malformed then valid)
            reset_repair_retry_count()
            repair_client = MockBedrockClient(malformed_then_valid=True)
            repair_engine = PredictionEngine(
                repair_client,
                model_id="mock-repair",
            )
            policy = PolicyEngine().analyze(
                "CREATE INDEX idx3 ON users(email);",
                _sample_snapshot(users_rows=100),
            )
            memories = await StubMemoryRetrieval().retrieve(
                migration_sql="CREATE INDEX idx3 ON users(email);",
                statement_types=policy.parsed_statement_types,
                scale_tier="small",
            )
            repaired = repair_engine.predict(
                migration_sql="CREATE INDEX idx3 ON users(email);",
                snapshot=_sample_snapshot(users_rows=100),
                policy=policy,
                memories=memories,
                scale_tier=ScaleTier.SMALL,
            )
            check(repaired.repair_retried, "expected repair retry")
            results["repair_retry_ok"] = True

            # Confidence adjustment unit check
            score, adjustments = adjust_confidence(
                0.9,
                policy=policy,
                memories=memories,
                scale_tier=ScaleTier.SMALL,
                snapshot_total_rows=100,
            )
            check(score < 0.9, "confidence must decrease")
            check(
                any(a.reason_code == "weak_retrieval" for a in adjustments),
                "weak_retrieval in adjustments",
            )
            results["confidence_adjust_ok"] = True

            # Hard failure after two malformed outputs (no partial prediction)
            from app.prediction.predictor import PredictionValidationError

            hard_fail_client = MockBedrockClient(always_malformed=True)
            hard_fail_engine = PredictionEngine(
                hard_fail_client,
                model_id="mock-hard-fail",
            )
            try:
                hard_fail_engine.predict(
                    migration_sql="CREATE INDEX idx4 ON users(email);",
                    snapshot=_sample_snapshot(users_rows=100),
                    policy=policy,
                    memories=memories,
                    scale_tier=ScaleTier.SMALL,
                )
                raise CheckError("expected PredictionValidationError after two failures")
            except PredictionValidationError:
                pass
            check(hard_fail_client._call_count == 2, "exactly one repair call")
            results["hard_failure_ok"] = True

            # Pipeline hard-fail marks run failed
            fail_run = await run_service.create_migration_run(
                "CREATE INDEX idx5 ON users(email);"
            )
            fail_run.schema_snapshot = _sample_snapshot(users_rows=100).model_dump(
                mode="json",
                by_alias=True,
            )
            fail_run.schema_discovery_status = SchemaDiscoveryStatus.SUCCEEDED
            await run_repo.update(fail_run)
            await session.commit()

            fail_pipeline = PredictionPipelineService(
                session=session,
                migration_run_repository=run_repo,
                prediction_repository=pred_repo,
                migration_run_service=run_service,
                bedrock_client=MockBedrockClient(always_malformed=True),
                prediction_model_id="mock-hard-fail",
                memory_retrieval=StubMemoryRetrieval(),
            )
            try:
                await fail_pipeline.run_prediction_pipeline(fail_run.id)
                raise CheckError("pipeline should hard-fail on double malformed output")
            except PredictionValidationError:
                pass
            failed_run = await run_repo.get_by_id_or_raise(
                fail_run.id,
                load_children=True,
            )
            check(
                failed_run.status == MigrationRunStatus.FAILED,
                f"hard-fail should mark failed, got {failed_run.status}",
            )
            check(failed_run.prediction is None, "no partial prediction persisted")
            results["pipeline_hard_fail_ok"] = True

            break
    finally:
        await db.close()

    return results


async def main() -> int:
    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    print("Phase 9 verification (mock Bedrock)")
    print(f"  database: {database_url.split('@')[-1] if '@' in database_url else '...'}")
    failures = 0

    try:
        print("\n[1] Policy YAML + sqlglot analysis")
        policy_result = verify_policy_layer()
        print(f"  [PASS] policy layer {policy_result}")
    except Exception as exc:
        failures += 1
        print(f"  [FAIL] policy layer: {exc}")
        traceback.print_exc()

    try:
        print("\n[2] Pipeline + approval gate (DB)")
        pipeline_result = await verify_pipeline_and_approval(database_url)
        print(f"  [PASS] pipeline/approval {pipeline_result}")
    except Exception as exc:
        failures += 1
        print(f"  [FAIL] pipeline/approval: {exc}")
        traceback.print_exc()

    print("\n" + ("=" * 60))
    if failures:
        print(f"RESULT: FAIL ({failures} section(s))")
        return 1
    print("RESULT: PASS — Phase 9 Definition of Done checks exercised")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
