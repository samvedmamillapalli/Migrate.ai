#!/usr/bin/env python3
"""Seed curated open-source migration memories + verify hybrid retrieval.

Run from backend/:
  python scripts/seed_open_source_corpus.py
  python scripts/seed_open_source_corpus.py --verify-retrieval
  python scripts/seed_open_source_corpus.py --demo-predict
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def _verify_retrieval(sql: str, label: str) -> None:
    from app.aws.config import get_aws_settings
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.memory.embedding_client import AwsTitanEmbeddingClient
    from app.memory.retrieval import HybridMemoryRetrieval
    from app.repositories.migration_memory_repository import MigrationMemoryRepository

    settings = get_settings()
    aws = get_aws_settings()
    db = DatabaseSessionManager(settings.database_url.get_secret_value())
    async for session in db.session():
        embed = AwsTitanEmbeddingClient(settings=aws)
        retrieval = HybridMemoryRetrieval(
            session=session,
            embedding_client=embed,
            repository=MigrationMemoryRepository(session),
            owner_identity="fresh-owner-no-history",
        )
        result = await retrieval.retrieve(
            migration_sql=sql,
            statement_types=["CreateIndex"] if "INDEX" in sql.upper() else ["AlterTable"],
            scale_tier="medium",
            limit=5,
        )
        print(f"\n=== Retrieval: {label} ===")
        print(f"SQL: {sql}")
        print(f"retrieved_count: {len(result.memories)}")
        for i, mem in enumerate(result.memories, start=1):
            print(
                f"  [{i}] sim={mem.similarity_score:.3f} tier={mem.scale_tier} "
                f"origin={mem.memory_origin} graded={not mem.not_a_graded_run}"
            )
            print(f"       summary: {mem.migration_summary[:140]}")
            if mem.source_url:
                print(f"       source: {mem.source_url}")
            if mem.lessons_learned:
                print(f"       lessons: {mem.lessons_learned[:120]}…")
        if not result.memories:
            print("  WARN: no memories retrieved")
        break
    await db.close()


async def _demo_predict() -> None:
    """Fresh owner predict path — proves retrieval feeds the prediction pipeline."""
    from datetime import datetime, timezone

    from app.aws.config import get_aws_settings
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.database.models import SchemaDiscoveryStatus
    from app.memory.embedding_client import AwsTitanEmbeddingClient
    from app.memory.retrieval import HybridMemoryRetrieval
    from app.prediction.bedrock_client import AwsBedrockClient
    from app.repositories.migration_memory_repository import MigrationMemoryRepository
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

    settings = get_settings()
    aws = get_aws_settings()
    client = AwsBedrockClient(settings=aws)
    db = DatabaseSessionManager(settings.database_url.get_secret_value())
    sql = "CREATE INDEX idx_orders_region ON orders (region);"
    orders = TableMetadata(
        name="orders",
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
                name="region",
                data_type="string",
                is_nullable=True,
                column_default=None,
                ordinal_position=2,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[],
        indexes=[],
        constraints=[],
        estimated_row_count=100_000,
    )
    snapshot = DatabaseMetadata(
        database_name="demo",
        server_version="CockroachDB",
        schemas=[SchemaMetadata(name="public", tables=[orders], table_count=1)],
        schema_count=1,
        table_count=1,
        inspected_at=datetime.now(timezone.utc),
    )

    async for session in db.session():
        run_repo = MigrationRunRepository(session)
        pred_repo = PredictionRepository(session)
        run_service = MigrationRunService(repository=run_repo, session=session)
        memory = HybridMemoryRetrieval(
            session=session,
            embedding_client=AwsTitanEmbeddingClient(settings=aws),
            repository=MigrationMemoryRepository(session),
            owner_identity="fresh-demo-owner",
        )
        pipeline = PredictionPipelineService(
            session=session,
            migration_run_repository=run_repo,
            prediction_repository=pred_repo,
            migration_run_service=run_service,
            bedrock_client=client,
            prediction_model_id=aws.bedrock_prediction_model_id or "mock",
            recommendation_model_id=aws.bedrock_recommendation_model_id,
            memory_retrieval=memory,
        )
        run = await run_service.create_migration_run(
            sql,
            owner_identity="fresh-demo-owner",
        )
        run.schema_snapshot = snapshot.model_dump(mode="json", by_alias=True)
        run.schema_discovery_status = SchemaDiscoveryStatus.SUCCEEDED
        await run_repo.update(run)
        await session.commit()

        updated = await pipeline.run_prediction_pipeline(
            run.id,
            scale_tier=ScaleTier.MEDIUM,
        )
        mem_x = (updated.explainability or {}).get("memory") or {}
        print("\n=== Demo predict (fresh owner) ===")
        print(f"run={updated.id} status={updated.status}")
        print(f"retrieved_count={mem_x.get('retrieved_count')}")
        for m in mem_x.get("memories") or []:
            print(
                f"  - sim={m.get('similarity_score')} origin={m.get('memory_origin')} "
                f"url={m.get('source_url')}"
            )
            print(f"    {str(m.get('migration_summary'))[:140]}")
        break
    await db.close()


async def main(verify: bool, demo_predict: bool) -> int:
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.memory.open_source_corpus import ensure_open_source_corpus, load_open_source_records
    from app.memory.embed_text import compose_embed_text

    records = load_open_source_records()
    print(f"JSON corpus files loaded: {len(records)}")
    if records:
        sample = records[0]
        emb = compose_embed_text(
            migration_summary=sample.migration_summary,
            risk_narrative=sample.risk_narrative,
            lessons_learned=sample.lessons_learned,
            surprise_notes=sample.surprise_notes,
            migration_sql=sample.migration_sql,
        )
        print("--- sample composed embed_text (first record) ---")
        print(emb[:800])
        print("--- end sample ---")

    settings = get_settings()
    db = DatabaseSessionManager(settings.database_url.get_secret_value())
    async for session in db.session():
        result = await ensure_open_source_corpus(session)
        print("Open-source corpus seed result:")
        for row in result.get("records", []):
            print(f"  - {row}")
        print(
            f"seeded={result.get('seeded')} skipped={result.get('skipped')} "
            f"repaired_embeddings={result.get('repaired_embeddings')} "
            f"rekeyed_demo_corpus={result.get('rekeyed_demo_corpus')}"
        )
        # Confirm at least one ready embedding exists
        ready = [
            r
            for r in result.get("records", [])
            if r.get("embedding_status") == "ready"
            or r.get("status") in {"exists", "updated", "seeded"}
        ]
        if result.get("seeded", 0) + result.get("repaired_embeddings", 0) == 0 and not any(
            r.get("status") == "exists" for r in result.get("records", [])
        ):
            print("ERROR: no corpus rows seeded/updated/exist — aborting")
            return 1
        break
    await db.close()

    if verify:
        await _verify_retrieval(
            "CREATE INDEX idx_orders_region ON orders (region);",
            "index (expect Temporal hot-table / blocking index)",
        )
        await _verify_retrieval(
            "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active';",
            "NOT NULL default (expect backfill / rewrite mechanism)",
        )
    if demo_predict:
        await _demo_predict()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-retrieval",
        action="store_true",
        help="After seeding, run hybrid retrieval for index + NOT NULL demos",
    )
    parser.add_argument(
        "--demo-predict",
        action="store_true",
        help="Run a fresh-owner prediction and print memory explainability",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.verify_retrieval, args.demo_predict)))
