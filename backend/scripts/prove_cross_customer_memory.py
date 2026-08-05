"""Live 4-step synthetic-account proof — docs/cross_customer.md §9.

Drives real service-layer calls directly (bypassing HTTP/auth, same pattern
as scripts/seed_open_source_corpus.py's _demo_predict) because the real API
forces owner_identity to the caller's authenticated identity — there is no
way to create runs under two distinct synthetic accounts (demo-company-a,
demo-company-b) through the authenticated HTTP surface, only through direct
service calls.

Usage (from backend/):
    python scripts/prove_cross_customer_memory.py
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
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

COMPANY_A = "demo-company-a"
COMPANY_B = "demo-company-b"

# Real, distinctive migrations — same mechanism (ADD COLUMN ... NOT NULL
# DEFAULT, a backfill-heavy pattern), different real table/column names, so
# the two are "shaped-similarly but not identical" per §9 step 4, and any
# leak of Company A's real names into what Company B sees would be
# immediately obvious in the printed evidence below.
SQL_COMPANY_A = (
    "ALTER TABLE billing_accounts ADD COLUMN dunning_stage INT NOT NULL DEFAULT 0;"
)
SQL_COMPANY_B = (
    "ALTER TABLE subscriptions ADD COLUMN renewal_attempt_count INT NOT NULL DEFAULT 0;"
)


async def main() -> int:
    from app.aws.config import get_aws_settings
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.database.models import ApprovalDecision, MigrationRun, MigrationRunStatus
    from app.memory.cross_customer_anonymizer import find_leaked_identifiers
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

    from promote_cross_customer_memory import _promote  # same dir on sys.path

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

        print("=" * 78)
        print("STEP 1 — opt both synthetic accounts into cross-customer sharing")
        print("=" * 78)
        await prefs.set_enabled(COMPANY_A, enabled=True)
        await prefs.set_enabled(COMPANY_B, enabled=True)
        await session.commit()
        print(f"  {COMPANY_A}: enabled")
        print(f"  {COMPANY_B}: enabled")

        print()
        print("=" * 78)
        print("STEP 2 — real graded migration under Company A")
        print("=" * 78)
        print(f"  SQL: {SQL_COMPANY_A}")

        run_a = MigrationRun(
            migration_sql=SQL_COMPANY_A,
            status=MigrationRunStatus.PENDING,
            owner_identity=COMPANY_A,
            run_kind="debug",
            schema_snapshot=None,
        )
        run_a = await run_repo.create(run_a)
        await session.commit()
        print(f"  run_id: {run_a.id}")

        memory = HybridMemoryRetrieval(
            session=session,
            embedding_client=embed,
            repository=MigrationMemoryRepository(session),
            cross_customer_repository=CrossCustomerMemoryRepository(session),
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
        run_a = await pipeline.run_prediction_pipeline(run_a.id)
        print(f"  predicted: status={run_a.status.value}")

        approvals = ApprovalService(
            session=session,
            migration_run_repository=run_repo,
            approval_repository=approval_repo,
            migration_run_service=run_service,
            workflow_orchestration=None,
            auto_start_workflow=False,
        )
        await approvals.approve(
            run_a.id,
            decision=ApprovalDecision.PROCEED,
            approver_identity=COMPANY_A,
            override_rationale=None,
            connection_secret_arn=None,
            start_workflow=False,
        )
        print("  approved: decision=proceed")

        local_verify = LocalShadowVerifyService(session=session, repository=run_repo)
        run_a = await local_verify.verify_run(run_a.id)
        print(f"  verified: status={run_a.status.value}")

        print()
        print("=" * 78)
        print("STEP 3 — promote Company A's graded run into the cross-customer pool")
        print("=" * 78)
        result = await _promote(run_a.id, force=False)
        for key, value in result.items():
            if key in {
                "sql_shape_template",
                "generalized_summary",
                "generalized_risk_narrative",
                "generalized_lessons_learned",
            }:
                print(f"  {key}: {value}")
            else:
                print(f"  {key}: {value}")

        if not result.get("promoted"):
            print("\n!!! PROMOTION FAILED — cannot continue proof !!!")
            return 1

        leak_check = result.get("final_leak_check_result")
        real_identifiers = result.get("final_leak_check_identifiers")
        print(f"\n  Real identifiers from Company A's migration: {real_identifiers}")
        print(f"  Leaked into the stored anonymized record: {leak_check}")
        if leak_check:
            print("\n!!! IDENTIFIER LEAK DETECTED — DO NOT TRUST THIS FEATURE !!!")
            return 1
        print("  CONFIRMED: no real identifier survived anonymization.")

        print()
        print("=" * 78)
        print("STEP 4 — Company B runs a shaped-similar migration, checks retrieval")
        print("=" * 78)
        print(f"  SQL: {SQL_COMPANY_B}")

        run_b = MigrationRun(
            migration_sql=SQL_COMPANY_B,
            status=MigrationRunStatus.PENDING,
            owner_identity=COMPANY_B,
            run_kind="debug",
            schema_snapshot=None,
        )
        run_b = await run_repo.create(run_b)
        await session.commit()
        print(f"  run_id: {run_b.id}")

        memory_b = HybridMemoryRetrieval(
            session=session,
            embedding_client=embed,
            repository=MigrationMemoryRepository(session),
            cross_customer_repository=CrossCustomerMemoryRepository(session),
        )
        pipeline_b = PredictionPipelineService(
            session=session,
            migration_run_repository=run_repo,
            prediction_repository=pred_repo,
            migration_run_service=run_service,
            bedrock_client=bedrock,
            prediction_model_id=aws.bedrock_prediction_model_id,
            recommendation_model_id=aws.bedrock_recommendation_model_id,
            memory_retrieval=memory_b,
        )
        run_b = await pipeline_b.run_prediction_pipeline(run_b.id)
        print(f"  predicted: status={run_b.status.value}")

        # Strongest evidence: what did Company B's *actual* prediction
        # pipeline retrieve and persist, not a side-channel query re-doing
        # the work? explainability["memory"] is
        # MemoryRetrievalResult.to_explainability()'s real, persisted output.
        run_b_full = await run_repo.get_by_id_or_raise(run_b.id, load_children=True)
        explain_memories = (
            (run_b_full.explainability or {}).get("memory", {}).get("memories", [])
        )
        pipeline_surfaced_cross_customer = any(
            m.get("memory_origin") == "cross_customer_anonymized"
            for m in explain_memories
        )
        print(
            f"\n  Company B's own prediction pipeline retrieved "
            f"{len(explain_memories)} memories total; "
            f"cross-customer entries among them: {pipeline_surfaced_cross_customer}"
        )

        # Direct, unambiguous evidence: query the cross-customer pool the
        # exact same way HybridMemoryRetrieval.retrieve() does internally,
        # so this check exercises the real query shape/index, not a
        # weaker approximation of it.
        cc_candidates = await CrossCustomerMemoryRepository(session).vector_candidates(
            query_vector_literal=_embed_query(embed, SQL_COMPANY_B),
            limit=5,
        )
        print(f"\n  Cross-customer candidates visible to Company B: {len(cc_candidates)}")
        found_company_a_pattern = False
        for mem, similarity in cc_candidates:
            print(f"    - similarity={similarity:.4f} contributor_count={mem.contributor_count}")
            print(f"      summary: {mem.generalized_summary}")
            print(f"      sql_shape_template: {mem.sql_shape_template}")
            if mem.shape_hash == result["shape_hash"]:
                found_company_a_pattern = True
                b_side_text = (
                    mem.generalized_summary
                    + mem.generalized_risk_narrative
                    + mem.generalized_lessons_learned
                    + mem.sql_shape_template
                )
                b_side_leak = find_leaked_identifiers(
                    b_side_text, frozenset(real_identifiers or [])
                )
                print(f"      >>> THIS IS COMPANY A's PROMOTED PATTERN <<<")
                print(f"      Leak check on what Company B can see: {b_side_leak}")

        print()
        print("=" * 78)
        print("PROOF RESULT")
        print("=" * 78)
        print(f"  Company A pattern promoted: {result['promoted']}")
        print(f"  No identifier leaked in stored record: {not leak_check}")
        print(f"  Company B's own prediction pipeline retrieved it: {pipeline_surfaced_cross_customer}")
        print(f"  Direct repo query confirms Company A's pattern present: {found_company_a_pattern}")
        print(f"  Company A run: {run_a.id}  |  Company B run: {run_b.id}")
        print(f"  Cross-customer memory row: {result['cross_customer_memory_id']}")

        overall_ok = (
            bool(result["promoted"])
            and not leak_check
            and found_company_a_pattern
            and pipeline_surfaced_cross_customer
        )
        print(f"\n  OVERALL: {'PASS' if overall_ok else 'FAIL'}")
        return 0 if overall_ok else 1

    return 1


def _embed_query(embed_client, sql: str) -> str:
    from app.memory.embedding_client import vector_to_literal

    vector = embed_client.embed(f"Migration type add_column. DDL: {sql}")
    return vector_to_literal(vector)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
