#!/usr/bin/env python3
"""OFFLINE-ONLY helper: seed graded memories for retrieval plumbing tests.

WARNING (Phase 10 / Phase 11): This creates *synthetic* completed runs without a
real shadow verify. Do NOT use these rows for the hackathon demo accuracy curve
or as evidence of learning. Prefer real closed-loop graded runs.

Phase 10 fix: owner_identity must be CORPUS_OWNER_IDENTITY from
app.memory.constants (never the legacy string "demo-corpus"), or hybrid
retrieval will never treat the rows as shared corpus.

Embeddings stay pending until POST /runs/memories/repair-embeddings (or live Titan).
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

from app.memory.constants import CORPUS_OWNER_IDENTITY  # noqa: E402

OWNER = CORPUS_OWNER_IDENTITY
SEED_SQL = [
    ("CREATE INDEX idx_users_email ON users (email);", "small"),
    ("CREATE INDEX idx_orders_created_at ON orders (created_at);", "medium"),
    ("ALTER TABLE users ADD COLUMN last_login TIMESTAMPTZ;", "small"),
    ("ALTER TABLE orders ADD COLUMN notes STRING;", "medium"),
    ("CREATE UNIQUE INDEX idx_users_username ON users (username);", "large"),
]


async def main() -> int:
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.database.models import (
        ExecutionResult,
        Grade,
        MigrationMemory,
        MigrationRun,
        MigrationRunStatus,
        Prediction,
        RollbackRisk,
    )
    from app.memory.constants import EMBEDDING_STATUS_PENDING
    from app.memory.embed_text import (
        classify_migration_type,
        compose_embed_text,
        summarize_migration,
        summarize_schema,
    )

    settings = get_settings()
    database = DatabaseSessionManager(settings.database_url.get_secret_value())
    created = 0

    async for session in database.session():
        for sql, tier in SEED_SQL:
            stmt_types = (
                ["CreateIndex"] if "INDEX" in sql.upper() else ["AlterTable"]
            )
            run = MigrationRun(
                migration_sql=sql,
                status=MigrationRunStatus.COMPLETED,
                owner_identity=OWNER,
                prediction_scale_tier=tier,
                parsed_statement_types=stmt_types,
            )
            session.add(run)
            await session.flush()

            pred = Prediction(
                migration_run_id=run.id,
                estimated_duration_seconds=12.0,
                estimated_storage_mb=8.0,
                rollback_risk=RollbackRisk.LOW,
                confidence_score=0.68,
                raw_confidence_score=0.72,
                confidence_adjustments=[],
                reasoning="Seeded demo prediction for hybrid retrieval demos.",
                key_assumptions=["seed"],
                uncertainty_notes=[],
                model_version="seed-demo/v1",
                prompt_template_version="prediction_v1",
            )
            exec_row = ExecutionResult(
                migration_run_id=run.id,
                success=True,
                actual_duration_seconds=14.5,
                actual_storage_mb=7.2,
                rollback_required=False,
                timed_out=False,
            )
            grade = Grade(
                migration_run_id=run.id,
                scale_tier=tier,
                timed_out=False,
                duration_abs_error_seconds=2.5,
                duration_pct_error=0.2,
                duration_within_band=True,
                duration_unverifiable=False,
                storage_abs_error_mb=0.8,
                storage_pct_error=0.1,
                storage_within_band=True,
                rollback_predicted="low",
                rollback_actual_class="none",
                rollback_consistent=True,
                rollback_within_band=True,
                outcome_class="success",
                high_risk_flags_present=False,
                adjusted_confidence=0.68,
                scalar_accuracy_score=0.82,
                dimension_details={"seed": True},
                surprise_notes="Seeded demo memory — small duration under-estimate.",
                lessons_learned=(
                    f"Index/alter on tier {tier}: expect ~15s; storage delta small."
                ),
                prose_status="seed",
            )
            mig_type = classify_migration_type(stmt_types, sql)
            mig_sum = summarize_migration(sql, mig_type)
            schema_sum, idx_count, complexity = summarize_schema(None)
            embed_text = compose_embed_text(
                migration_summary=mig_sum,
                risk_narrative="Low rollback risk additive DDL (seed).",
                lessons_learned=grade.lessons_learned,
                surprise_notes=grade.surprise_notes,
                migration_sql=sql,
            )
            memory = MigrationMemory(
                migration_run_id=run.id,
                owner_identity=OWNER,
                scale_tier=tier,
                migration_type=mig_type,
                migration_summary=mig_sum,
                schema_summary=schema_sum,
                risk_flags=[],
                prediction_summary={
                    "estimated_duration_seconds": 12.0,
                    "estimated_storage_mb": 8.0,
                },
                recommendation_summary=None,
                approval_summary={"decision": "proceed", "seed": True},
                execution_summary={
                    "success": True,
                    "actual_duration_seconds": 14.5,
                    "actual_storage_mb": 7.2,
                },
                grade_summary={
                    "scalar_accuracy_score": grade.scalar_accuracy_score,
                    "outcome_class": grade.outcome_class,
                    "seed": True,
                },
                lessons_learned=grade.lessons_learned,
                surprise_notes=grade.surprise_notes,
                embed_text=embed_text,
                embedding_status=EMBEDDING_STATUS_PENDING,
                index_count=idx_count,
                table_complexity=complexity,
            )
            session.add_all([pred, exec_row, grade, memory])
            created += 1

        await session.commit()
        break

    await database.close()
    print(f"Seeded {created} graded memories for owner_identity={OWNER!r}")
    print("Optional: POST /runs/memories/repair-embeddings to fill Titan vectors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
