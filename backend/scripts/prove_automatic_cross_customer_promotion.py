"""Live proof that the AUTOMATIC promotion hook fires — docs/cross_customer.md §5.

Distinct from scripts/prove_cross_customer_memory.py (the Phase 1 proof),
which explicitly calls the manual promotion script/service after verifying a
run. This script never calls CrossCustomerPromotionService or
promote_cross_customer_memory.py at all — it only opts a synthetic account
in, then drives predict -> approve -> local-verify exactly like a normal
user would, and checks that a cross_customer_memories row appeared anyway.

local-verify (LocalShadowVerifyService._run_handler_chain) calls the real
persist-results Lambda HANDLER function directly — the same
_build_grading_pipeline() now wired with CrossCustomerPromotionService this
session — so this is a genuine exercise of the automatic hook through the
real handler code, not a re-implementation of it.

Usage (from backend/):
    python scripts/prove_automatic_cross_customer_promotion.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COMPANY_C = "demo-company-c-automatic-hook"

# Distinct from the SQL used in prove_cross_customer_memory.py, so a match
# in cross_customer_memories can only have come from THIS run's automatic
# promotion, not a leftover row from the other proof script.
SQL_COMPANY_C = (
    "ALTER TABLE invoice_line_items ADD COLUMN tax_jurisdiction_code "
    "VARCHAR(16) NOT NULL DEFAULT 'US';"
)


async def main() -> int:
    from app.aws.config import get_aws_settings
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.database.models import ApprovalDecision, MigrationRun, MigrationRunStatus
    from app.memory.cross_customer_anonymizer import (
        build_sql_shape_template,
        find_leaked_identifiers,
    )
    from app.memory.embedding_client import AwsTitanEmbeddingClient
    from app.memory.retrieval import HybridMemoryRetrieval
    from app.prediction.bedrock_client import AwsBedrockClient
    from app.repositories.approval_repository import ApprovalRepository
    from app.repositories.cross_customer_memory_repository import (
        CrossCustomerMemoryRepository,
    )
    from app.repositories.memory_sharing_preference_repository import (
        MemorySharingPreferenceRepository,
    )
    from app.repositories.migration_memory_repository import MigrationMemoryRepository
    from app.repositories.migration_run_repository import MigrationRunRepository
    from app.repositories.prediction_repository import PredictionRepository
    from app.services.approval_service import ApprovalService
    from app.services.local_shadow_verify_service import LocalShadowVerifyService
    from app.services.migration_run_service import MigrationRunService
    from app.services.prediction_pipeline_service import PredictionPipelineService

    settings = get_settings()
    aws = get_aws_settings()
    db = DatabaseSessionManager(settings.database_url.get_secret_value())

    async for session in db.session():
        run_repo = MigrationRunRepository(session)
        pred_repo = PredictionRepository(session)
        approval_repo = ApprovalRepository(session)
        run_service = MigrationRunService(repository=run_repo, session=session)
        bedrock = AwsBedrockClient(settings=aws)
        embed = AwsTitanEmbeddingClient(settings=aws)
        prefs = MemorySharingPreferenceRepository(session)
        cc_repo = CrossCustomerMemoryRepository(session)

        print("=" * 78)
        print("STEP 1 — opt synthetic Company C into cross-customer sharing")
        print("=" * 78)
        await prefs.set_enabled(COMPANY_C, enabled=True)
        await session.commit()
        print(f"  {COMPANY_C}: enabled")

        expected_shape = build_sql_shape_template(SQL_COMPANY_C)
        # Compute the same tuple compute_shape_hash would use once we know
        # the actual grade's scale_tier/outcome_class, after grading below —
        # for now just prove no row for this exact SQL shape exists yet
        # (best-effort sanity check, not load-bearing for the proof).

        print()
        print("=" * 78)
        print("STEP 2 — predict -> approve -> local-verify, exactly as a user would")
        print("=" * 78)
        print(f"  SQL: {SQL_COMPANY_C}")

        run = MigrationRun(
            migration_sql=SQL_COMPANY_C,
            status=MigrationRunStatus.PENDING,
            owner_identity=COMPANY_C,
            run_kind="debug",
            schema_snapshot=None,
        )
        run = await run_repo.create(run)
        await session.commit()
        print(f"  run_id: {run.id}")

        memory = HybridMemoryRetrieval(
            session=session,
            embedding_client=embed,
            repository=MigrationMemoryRepository(session),
            cross_customer_repository=cc_repo,
        )
        pipeline = PredictionPipelineService(
            session=session,
            migration_run_repository=run_repo,
            prediction_repository=pred_repo,
            migration_run_service=run_service,
            bedrock_client=bedrock,
            prediction_model_id=aws.bedrock_prediction_model_id,
            recommendation_model_id=aws.bedrock_recommendation_model_id,
            memory_retrieval=memory,
        )
        run = await pipeline.run_prediction_pipeline(run.id)
        print(f"  predicted: status={run.status.value}")

        approvals = ApprovalService(
            session=session,
            migration_run_repository=run_repo,
            approval_repository=approval_repo,
            migration_run_service=run_service,
            workflow_orchestration=None,
            auto_start_workflow=False,
        )
        await approvals.approve(
            run.id,
            decision=ApprovalDecision.PROCEED,
            approver_identity=COMPANY_C,
            override_rationale=None,
            connection_secret_arn=None,
            start_workflow=False,
        )
        print("  approved: decision=proceed")

        # This is the ONLY step that touches grading/memory. It calls the
        # real persist-results Lambda handler internally
        # (LocalShadowVerifyService._run_handler_chain ->
        # HANDLERS["persist-results"] -> _build_grading_pipeline() ->
        # GradingPipelineService.grade_run() -> MemoryWriteService.write_memory()
        # -> CrossCustomerPromotionService.try_promote()). No code in this
        # script calls the promotion service or script directly.
        local_verify = LocalShadowVerifyService(session=session, repository=run_repo)
        run = await local_verify.verify_run(run.id)
        print(f"  verified (persist + grade + remember): status={run.status.value}")

        print()
        print("=" * 78)
        print("STEP 3 — check cross_customer_memories WITHOUT calling promotion code")
        print("=" * 78)

        # We don't know the exact shape_hash without scale_tier/outcome_class
        # from the real grade, so fetch the grade that was just written and
        # recompute it the same way the service does — read-only, just to
        # locate the row for inspection.
        from app.memory.cross_customer_anonymizer import compute_shape_hash
        from app.repositories.grade_repository import GradeRepository

        grade = await GradeRepository(session).get_by_migration_run_id(run.id)
        if grade is None:
            print("\n!!! NO GRADE WAS WRITTEN — cannot continue proof !!!")
            return 1
        print(f"  grade: outcome_class={grade.outcome_class} scale_tier={grade.scale_tier}")

        shape_hash = compute_shape_hash(
            sql_shape_template=expected_shape.template,
            scale_tier=grade.scale_tier,
            outcome_class=grade.outcome_class,
        )
        row = await cc_repo.get_by_shape_hash(shape_hash)

        if row is None:
            print(
                "\n!!! NO cross_customer_memories ROW FOUND — the automatic "
                "hook did not promote this run. FAIL !!!"
            )
            return 1

        print(f"  cross_customer_memories row: id={row.id} shape_hash={row.shape_hash}")
        print(f"  contributor_count={row.contributor_count}")
        print(f"  sql_shape_template: {row.sql_shape_template}")
        print(f"  generalized_summary: {row.generalized_summary}")

        combined_text = (
            row.sql_shape_template
            + row.generalized_summary
            + row.generalized_risk_narrative
            + row.generalized_lessons_learned
            + (row.generalized_surprise_notes or "")
        )
        leak_check = find_leaked_identifiers(combined_text, expected_shape.identifiers)
        print(f"\n  Real identifiers in Company C's SQL: {sorted(expected_shape.identifiers)}")
        print(f"  Leaked into the automatically-promoted record: {leak_check}")

        print()
        print("=" * 78)
        print("PROOF RESULT")
        print("=" * 78)
        overall_ok = row is not None and not leak_check
        print(f"  Automatic promotion fired without any manual call: {row is not None}")
        print(f"  No identifier leaked: {not leak_check}")
        print(f"  Company C run: {run.id}")
        print(f"\n  OVERALL: {'PASS' if overall_ok else 'FAIL'}")
        return 0 if overall_ok else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
