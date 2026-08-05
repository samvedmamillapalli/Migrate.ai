#!/usr/bin/env python3
"""Manual cross-customer memory promotion — docs/cross_customer.md.

MemoryWriteService.write_memory() now also promotes automatically after
every graded run (§5, Phase 2) via the same CrossCustomerPromotionService
this script drives by hand. Use this script for one-off backfills of runs
graded before the hook existed, re-running a run that failed anonymization
the first time, or the synthetic-account proof in §9 — not as the primary
path, which is automatic.

Usage (from backend/):
  python scripts/promote_cross_customer_memory.py <migration_run_id>
  python scripts/promote_cross_customer_memory.py <migration_run_id> --force
    (bypass the memory_sharing_preferences consent check — for the
    synthetic-account proof in §9 only; never use --force against a real
    account's run)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def _promote(run_id: uuid.UUID, *, force: bool) -> dict[str, object]:
    # Promotion logic itself (consent check, anonymization call, dedup
    # upsert, embedding) lives in CrossCustomerPromotionService — shared
    # with the automatic write_memory hook (§5) so there is exactly one
    # implementation to trust, not two that can drift apart. This script's
    # job is just: drive it for one run by hand, then do its own
    # belt-and-braces re-verification of the result before printing it.
    from app.aws.config import get_aws_settings
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.memory.cross_customer_anonymizer import (
        build_sql_shape_template,
        find_leaked_identifiers,
    )
    from app.memory.embedding_client import AwsTitanEmbeddingClient
    from app.prediction.bedrock_client import AwsBedrockClient
    from app.repositories.cross_customer_memory_repository import (
        CrossCustomerMemoryRepository,
    )
    from app.repositories.grade_repository import GradeRepository
    from app.repositories.memory_sharing_preference_repository import (
        MemorySharingPreferenceRepository,
    )
    from app.repositories.migration_run_repository import MigrationRunRepository
    from app.repositories.prediction_repository import PredictionRepository
    from app.services.cross_customer_promotion_service import (
        CrossCustomerPromotionService,
    )

    settings = get_settings()
    aws = get_aws_settings()
    db = DatabaseSessionManager(settings.database_url.get_secret_value())

    async for session in db.session():
        runs = MigrationRunRepository(session)
        run = await runs.get_by_id_or_raise(run_id)

        grades = GradeRepository(session)
        grade = await grades.get_by_migration_run_id(run_id)
        if grade is None:
            return {"promoted": False, "reason": "run has no grade yet — not eligible"}

        preds = PredictionRepository(session)
        prediction = await preds.get_by_migration_run_id(run_id)

        prefs = MemorySharingPreferenceRepository(session)
        if not force and not await prefs.is_enabled(run.owner_identity):
            return {
                "promoted": False,
                "reason": (
                    f"owner_identity={run.owner_identity!r} has not opted into "
                    "cross-customer sharing (memory_sharing_preferences); "
                    "pass --force only for the synthetic-account proof in §9"
                ),
            }

        bedrock_model_id = (
            aws.bedrock_recommendation_model_id or aws.bedrock_prediction_model_id
        )
        if not bedrock_model_id:
            return {"promoted": False, "reason": "no Bedrock model configured"}

        cc_repo = CrossCustomerMemoryRepository(session)
        service = CrossCustomerPromotionService(
            session=session,
            cross_customer_repository=cc_repo,
            sharing_preference_repository=prefs,
            bedrock_client=AwsBedrockClient(settings=aws),
            bedrock_model_id=bedrock_model_id,
            embedding_client=AwsTitanEmbeddingClient(settings=aws),
            embedding_model_id=aws.bedrock_embedding_model_id,
        )

        result = await service.try_promote(
            run=run, prediction=prediction, grade=grade, force=force
        )
        await session.commit()
        if result is None:
            return {
                "promoted": False,
                "reason": (
                    "promotion did not happen — the run was already checked "
                    "for a grade and consent above, so this means the "
                    "anonymization pipeline rejected it (parse failure, "
                    "Bedrock failure, or identifier leak) or embedding "
                    "failed; see server logs for the specific reason"
                ),
            }

        # Belt-and-braces: re-verify the row that was just written against
        # the exact identifiers a fresh, independent shape-template call
        # extracts from the same SQL — this script doesn't trust the
        # service's own internal check implicitly.
        entity = await cc_repo.get_by_shape_hash(result["shape_hash"])
        shape = build_sql_shape_template(run.migration_sql)
        final_leak_check = find_leaked_identifiers(
            "\n".join(
                [
                    entity.sql_shape_template,
                    entity.generalized_summary,
                    entity.generalized_risk_narrative,
                    entity.generalized_lessons_learned,
                    entity.generalized_surprise_notes or "",
                ]
            ),
            shape.identifiers,
        )

        return {
            "promoted": True,
            "created": result["created"],
            "cross_customer_memory_id": result["cross_customer_memory_id"],
            "shape_hash": result["shape_hash"],
            "contributor_count": result["contributor_count"],
            "embedding_status": entity.embedding_status,
            "sql_shape_template": entity.sql_shape_template,
            "generalized_summary": entity.generalized_summary,
            "generalized_risk_narrative": entity.generalized_risk_narrative,
            "generalized_lessons_learned": entity.generalized_lessons_learned,
            "final_leak_check_identifiers": sorted(shape.identifiers),
            "final_leak_check_result": final_leak_check,
        }

    return {"promoted": False, "reason": "no database session available"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=str, help="migration_runs.id to promote")
    parser.add_argument(
        "--force",
        action="store_true",
        help="bypass consent check — synthetic-account proof only, never for a real account",
    )
    args = parser.parse_args()

    try:
        run_id = uuid.UUID(args.run_id)
    except ValueError:
        print(f"Not a valid UUID: {args.run_id}", file=sys.stderr)
        return 2

    result = asyncio.run(_promote(run_id, force=args.force))

    print("\n=== Cross-customer promotion result ===")
    for key, value in result.items():
        print(f"{key}: {value}")

    if not result.get("promoted"):
        return 1
    if result.get("final_leak_check_result"):
        print(
            "\n*** WARNING: final_leak_check_result is non-empty — a real "
            "identifier may have survived. This should never happen; the "
            "pipeline's own Step 4 should have rejected this promotion. "
            "Investigate before trusting this row. ***",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
