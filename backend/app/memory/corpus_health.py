"""Corpus / memory-store health aggregates for operator visibility."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import MigrationMemory
from app.memory.constants import (
    CORPUS_OWNER_IDENTITY,
    EMBEDDING_STATUS_FAILED,
    EMBEDDING_STATUS_PENDING,
    EMBEDDING_STATUS_READY,
    LEGACY_DEMO_CORPUS_OWNER,
)


async def fetch_corpus_health(session: AsyncSession) -> dict[str, Any]:
    """Structured health summary over migration_memories.

    Nonzero problem counts are intentional signal — callers should surface them
    loudly rather than rendering a clean empty state.
    """
    total = (
        await session.execute(select(func.count()).select_from(MigrationMemory))
    ).scalar_one()

    by_owner_rows = (
        await session.execute(
            select(
                MigrationMemory.owner_identity,
                func.count().label("n"),
            )
            .group_by(MigrationMemory.owner_identity)
            .order_by(func.count().desc())
        )
    ).all()

    by_status_rows = (
        await session.execute(
            select(
                MigrationMemory.embedding_status,
                func.count().label("n"),
            ).group_by(MigrationMemory.embedding_status)
        )
    ).all()

    missing_embedding = (
        await session.execute(
            select(func.count()).select_from(MigrationMemory).where(
                (MigrationMemory.embedding.is_(None))
                | (MigrationMemory.embedding_status != EMBEDDING_STATUS_READY)
            )
        )
    ).scalar_one()

    missing_scale_tier = (
        await session.execute(
            select(func.count()).select_from(MigrationMemory).where(
                (MigrationMemory.scale_tier.is_(None))
                | (MigrationMemory.scale_tier == "")
            )
        )
    ).scalar_one()

    missing_migration_type = (
        await session.execute(
            select(func.count()).select_from(MigrationMemory).where(
                (MigrationMemory.migration_type.is_(None))
                | (MigrationMemory.migration_type == "")
                | (MigrationMemory.migration_type == "unknown")
            )
        )
    ).scalar_one()

    wrong_seed_identity = (
        await session.execute(
            select(func.count()).select_from(MigrationMemory).where(
                MigrationMemory.owner_identity == LEGACY_DEMO_CORPUS_OWNER
            )
        )
    ).scalar_one()

    corpus_ready = (
        await session.execute(
            select(func.count()).select_from(MigrationMemory).where(
                MigrationMemory.owner_identity == CORPUS_OWNER_IDENTITY,
                MigrationMemory.embedding_status == EMBEDDING_STATUS_READY,
                MigrationMemory.embedding.is_not(None),
            )
        )
    ).scalar_one()

    problems: list[str] = []
    if int(missing_embedding or 0) > 0:
        problems.append(
            f"{int(missing_embedding)} memories missing a ready embedding "
            "(pending/failed/null vector)"
        )
    if int(missing_scale_tier or 0) > 0:
        problems.append(f"{int(missing_scale_tier)} memories missing scale_tier")
    if int(missing_migration_type or 0) > 0:
        problems.append(
            f"{int(missing_migration_type)} memories missing or unknown migration_type"
        )
    if int(wrong_seed_identity or 0) > 0:
        problems.append(
            f"{int(wrong_seed_identity)} memories still use legacy owner_identity "
            f"{LEGACY_DEMO_CORPUS_OWNER!r} instead of reserved "
            f"{CORPUS_OWNER_IDENTITY!r}"
        )
    if int(total or 0) == 0:
        problems.append(
            "Memory store is empty — no graded memories yet (expected until "
            "real closed-loop runs complete)"
        )
    elif int(corpus_ready or 0) == 0:
        problems.append(
            f"No retrieval-ready corpus rows under '{CORPUS_OWNER_IDENTITY}' "
            "with embedding_status=ready"
        )

    # Is the distributed vector index actually reachable by retrieval? This is
    # the check that would have caught the Phase 10 defect (index created but
    # structurally unusable) instead of it going unnoticed for a week.
    from app.grading.config import get_grading_file
    from app.memory.index_health import check_vector_index, vector_index_problems

    try:
        pool_size = get_grading_file().retrieval.candidate_pool_size
    except Exception:  # noqa: BLE001 - health must not depend on config loading
        pool_size = 20
    vector_index = await check_vector_index(session, pool_size=pool_size)
    problems.extend(vector_index_problems(vector_index))

    by_status = {str(row[0]): int(row[1]) for row in by_status_rows}
    return {
        # Empty store is not "healthy" for demo readiness — surface problems loudly.
        "healthy": len(problems) == 0,
        "empty": int(total or 0) == 0,
        "total_memories": int(total or 0),
        "by_owner_identity": [
            {"owner_identity": str(row[0]), "count": int(row[1])}
            for row in by_owner_rows
        ],
        "by_embedding_status": {
            EMBEDDING_STATUS_READY: int(by_status.get(EMBEDDING_STATUS_READY, 0)),
            EMBEDDING_STATUS_PENDING: int(by_status.get(EMBEDDING_STATUS_PENDING, 0)),
            EMBEDDING_STATUS_FAILED: int(by_status.get(EMBEDDING_STATUS_FAILED, 0)),
            **{
                k: v
                for k, v in by_status.items()
                if k
                not in {
                    EMBEDDING_STATUS_READY,
                    EMBEDDING_STATUS_PENDING,
                    EMBEDDING_STATUS_FAILED,
                }
            },
        },
        "missing_embeddings": int(missing_embedding or 0),
        "missing_scale_tier": int(missing_scale_tier or 0),
        "missing_migration_type": int(missing_migration_type or 0),
        "legacy_demo_corpus_owner_count": int(wrong_seed_identity or 0),
        "corpus_identity": CORPUS_OWNER_IDENTITY,
        "corpus_ready_count": int(corpus_ready or 0),
        # True when the distributed vector index CAN serve retrieval. Whether
        # the planner currently chooses it is a cost decision reported
        # separately under "vector_index" — see app/memory/index_health.py for
        # why conflating the two produces false alarms.
        "vector_index_used": vector_index.get("usable"),
        "vector_index": vector_index,
        "problems": problems,
    }


async def list_memories(
    session: AsyncSession,
    *,
    owner_identity: str | None = None,
    embedding_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_embed_text: bool = True,
    include_shared_corpus: bool = True,
) -> tuple[list[MigrationMemory], int]:
    filters = []
    if owner_identity:
        if (
            include_shared_corpus
            and owner_identity != CORPUS_OWNER_IDENTITY
        ):
            filters.append(
                MigrationMemory.owner_identity.in_(
                    [owner_identity, CORPUS_OWNER_IDENTITY]
                )
            )
        else:
            filters.append(MigrationMemory.owner_identity == owner_identity)
    if embedding_status:
        filters.append(MigrationMemory.embedding_status == embedding_status)

    count_q = select(func.count()).select_from(MigrationMemory)
    list_q = select(MigrationMemory).order_by(MigrationMemory.created_at.desc())
    if filters:
        count_q = count_q.where(*filters)
        list_q = list_q.where(*filters)

    total = (await session.execute(count_q)).scalar_one()
    rows = (
        await session.execute(list_q.limit(limit).offset(offset))
    ).scalars().all()
    # include_embed_text is always available on the ORM object; callers decide
    # whether to serialize it. Kept as an explicit parameter for API clarity.
    _ = include_embed_text
    return list(rows), int(total or 0)
