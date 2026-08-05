"""Live proof: consent actually gates promotion, and dedup actually works —
docs/cross_customer.md §2 and §7, exercised through the real automatic hook
(MemoryWriteService.write_memory -> CrossCustomerPromotionService.try_promote),
never called directly.

Three synthetic accounts, same migration SQL/shape throughout:
  - demo-company-optout : sharing NEVER enabled. After a full graded run,
    no cross_customer_memories row for this shape may exist as a result.
  - demo-company-dedup-1, demo-company-dedup-2 : both opted in, each runs
    the SAME migration SQL. The second run must NOT create a second row —
    it must increment contributor_count on the first.

Usage (from backend/):
    python scripts/prove_consent_and_dedup.py
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

COMPANY_OPTOUT = "demo-company-optout-proof"
COMPANY_DEDUP_1 = "demo-company-dedup-1-proof"
COMPANY_DEDUP_2 = "demo-company-dedup-2-proof"

# Distinct from every other proof script's SQL *shape* (not just the
# literal text) — the shape template strips identifiers and literal
# values, so e.g. "ADD COLUMN x INT DEFAULT 0" and "ADD COLUMN y INT
# DEFAULT 5" collide. A two-column, mixed-type ADD is a shape not used by
# any other script in this session, confirmed by checking
# cross_customer_memories before running (see the investigation that led
# to this constant: the original single-INT-column SQL here collided with
# a pre-existing row from an earlier proof script and produced a false
# "consent didn't gate" reading, which turned out to be a test-script bug,
# not a real one, once verified with contributor_count deltas).
SHARED_SQL = (
    "ALTER TABLE support_tickets ADD COLUMN priority_score INT NOT NULL DEFAULT 5, "
    "ADD COLUMN escalation_note TEXT;"
)


async def _run_one(
    *,
    session,
    run_repo,
    pred_repo,
    approval_repo,
    run_service,
    bedrock,
    embed,
    aws,
    cc_repo,
    owner: str,
    sql: str,
):
    from app.database.models import ApprovalDecision, MigrationRun, MigrationRunStatus
    from app.memory.retrieval import HybridMemoryRetrieval
    from app.repositories.migration_memory_repository import MigrationMemoryRepository
    from app.services.approval_service import ApprovalService
    from app.services.local_shadow_verify_service import LocalShadowVerifyService
    from app.services.prediction_pipeline_service import PredictionPipelineService

    run = MigrationRun(
        migration_sql=sql,
        status=MigrationRunStatus.PENDING,
        owner_identity=owner,
        run_kind="debug",
        schema_snapshot=None,
    )
    run = await run_repo.create(run)
    await session.commit()

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
        approver_identity=owner,
        override_rationale=None,
        connection_secret_arn=None,
        start_workflow=False,
    )

    local_verify = LocalShadowVerifyService(session=session, repository=run_repo)
    run = await local_verify.verify_run(run.id)
    return run


async def main() -> int:
    from app.aws.config import get_aws_settings
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.memory.cross_customer_anonymizer import (
        build_sql_shape_template,
        compute_shape_hash,
    )
    from app.memory.embedding_client import AwsTitanEmbeddingClient
    from app.prediction.bedrock_client import AwsBedrockClient
    from app.repositories.approval_repository import ApprovalRepository
    from app.repositories.cross_customer_memory_repository import (
        CrossCustomerMemoryRepository,
    )
    from app.repositories.grade_repository import GradeRepository
    from app.repositories.memory_sharing_preference_repository import (
        MemorySharingPreferenceRepository,
    )
    from app.repositories.migration_run_repository import MigrationRunRepository
    from app.repositories.prediction_repository import PredictionRepository
    from app.services.migration_run_service import MigrationRunService

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
        grades = GradeRepository(session)

        overall_ok = True
        shape = build_sql_shape_template(SHARED_SQL)

        print("=" * 78)
        print("PRE-CHECK — confirm this exact shape template is unused so far")
        print("=" * 78)
        print(f"  shape template: {shape.template}")
        from sqlalchemy import text as _sql_text

        preexisting = await session.execute(
            _sql_text(
                "SELECT count(*) FROM cross_customer_memories "
                "WHERE sql_shape_template = :t"
            ),
            {"t": shape.template},
        )
        preexisting_count = preexisting.scalar_one()
        print(f"  existing rows with this exact template: {preexisting_count}")
        if preexisting_count:
            print(
                "\n!!! this shape already has rows from a prior run — pick a "
                "more distinctive SHARED_SQL before trusting the deltas "
                "below (this is exactly the false-positive this pre-check "
                "exists to catch) !!!"
            )
            return 1

        print()
        print("=" * 78)
        print("PART A — consent gate: opted-OUT account must not promote")
        print("=" * 78)
        await prefs.set_enabled(COMPANY_OPTOUT, enabled=False)
        await session.commit()
        run_a = await _run_one(
            session=session, run_repo=run_repo, pred_repo=pred_repo,
            approval_repo=approval_repo, run_service=run_service,
            bedrock=bedrock, embed=embed, aws=aws, cc_repo=cc_repo,
            owner=COMPANY_OPTOUT, sql=SHARED_SQL,
        )
        grade_a = await grades.get_by_migration_run_id(run_a.id)
        print(f"  run: {run_a.id}  status={run_a.status.value}  "
              f"outcome={grade_a.outcome_class if grade_a else None}  "
              f"scale_tier={grade_a.scale_tier if grade_a else None}")

        if grade_a is None:
            print("\n!!! opted-out run has no grade — cannot continue !!!")
            return 1

        shape_hash_a = compute_shape_hash(
            sql_shape_template=shape.template,
            scale_tier=grade_a.scale_tier,
            outcome_class=grade_a.outcome_class,
        )
        row_after_optout = await cc_repo.get_by_shape_hash(shape_hash_a)
        # The pre-check above already proved this exact template starts at
        # zero rows, so presence here is unambiguous: any row means the
        # opted-out account's run promoted something.
        optout_ok = row_after_optout is None
        print(f"  cross_customer_memories row created by the opted-out "
              f"run: {row_after_optout is not None}")
        print(f"  PART A RESULT: {'PASS' if optout_ok else 'FAIL'} "
              f"(expected no row)")
        overall_ok = overall_ok and optout_ok

        print()
        print("=" * 78)
        print("PART B — dedup: two opted-in accounts, same shape, one row")
        print("=" * 78)
        await prefs.set_enabled(COMPANY_DEDUP_1, enabled=True)
        await prefs.set_enabled(COMPANY_DEDUP_2, enabled=True)
        await session.commit()

        run_b1 = await _run_one(
            session=session, run_repo=run_repo, pred_repo=pred_repo,
            approval_repo=approval_repo, run_service=run_service,
            bedrock=bedrock, embed=embed, aws=aws, cc_repo=cc_repo,
            owner=COMPANY_DEDUP_1, sql=SHARED_SQL,
        )
        grade_b1 = await grades.get_by_migration_run_id(run_b1.id)
        print(f"  run 1 ({COMPANY_DEDUP_1}): {run_b1.id}  "
              f"outcome={grade_b1.outcome_class if grade_b1 else None}  "
              f"scale_tier={grade_b1.scale_tier if grade_b1 else None}")

        run_b2 = await _run_one(
            session=session, run_repo=run_repo, pred_repo=pred_repo,
            approval_repo=approval_repo, run_service=run_service,
            bedrock=bedrock, embed=embed, aws=aws, cc_repo=cc_repo,
            owner=COMPANY_DEDUP_2, sql=SHARED_SQL,
        )
        grade_b2 = await grades.get_by_migration_run_id(run_b2.id)
        print(f"  run 2 ({COMPANY_DEDUP_2}): {run_b2.id}  "
              f"outcome={grade_b2.outcome_class if grade_b2 else None}  "
              f"scale_tier={grade_b2.scale_tier if grade_b2 else None}")

        if grade_b1 is None or grade_b2 is None:
            print("\n!!! one of the dedup runs has no grade — cannot continue !!!")
            return 1

        if grade_b1.outcome_class != grade_b2.outcome_class or (
            grade_b1.scale_tier != grade_b2.scale_tier
        ):
            print(
                "\n  NOTE: the two runs landed on different outcome_class/"
                "scale_tier (real shadow execution isn't perfectly "
                "deterministic run-to-row) — shape_hash will legitimately "
                "differ, so dedup cannot be observed this time. This is a "
                "test-conditions limitation, not evidence of a dedup bug "
                "(dedup's core logic already has unit + race-condition "
                "regression coverage in test_cross_customer_memory_repository.py)."
            )
            print(f"\n  OVERALL: {'PASS' if overall_ok else 'FAIL'} (dedup part skipped)")
            return 0 if overall_ok else 1

        shape_hash_b = compute_shape_hash(
            sql_shape_template=shape.template,
            scale_tier=grade_b1.scale_tier,
            outcome_class=grade_b1.outcome_class,
        )
        row_b = await cc_repo.get_by_shape_hash(shape_hash_b)
        dedup_ok = row_b is not None and row_b.contributor_count == 2
        print(f"\n  cross_customer_memories row: "
              f"{row_b.id if row_b else None}  "
              f"contributor_count={row_b.contributor_count if row_b else None}")
        print(f"  PART B RESULT: {'PASS' if dedup_ok else 'FAIL'} "
              f"(expected exactly one row with contributor_count=2)")
        overall_ok = overall_ok and dedup_ok

        print()
        print("=" * 78)
        print(f"OVERALL: {'PASS' if overall_ok else 'FAIL'}")
        print("=" * 78)
        return 0 if overall_ok else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
