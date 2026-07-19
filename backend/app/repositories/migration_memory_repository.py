from __future__ import annotations

import uuid

from sqlalchemy import select, text

from app.database.models import MigrationMemory
from app.memory.constants import EMBEDDING_STATUS_READY
from app.repositories.base import BaseRepository


class MigrationMemoryRepository(BaseRepository[MigrationMemory]):
    model = MigrationMemory

    async def get_by_migration_run_id(
        self,
        run_id: uuid.UUID,
    ) -> MigrationMemory | None:
        result = await self._session.execute(
            select(MigrationMemory).where(MigrationMemory.migration_run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_pending_embeddings(self, *, limit: int = 50) -> list[MigrationMemory]:
        result = await self._session.execute(
            select(MigrationMemory)
            .where(MigrationMemory.embedding_status == "pending")
            .order_by(MigrationMemory.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def vector_candidates(
        self,
        *,
        query_vector_literal: str,
        owner_identities: list[str],
        limit: int,
    ) -> list[tuple[MigrationMemory, float]]:
        """Nearest neighbors via CockroachDB VECTOR cosine distance.

        Uses the Distributed Vector Index on ``embedding``. Returns
        (memory, cosine_similarity) where similarity = 1 - cosine_distance.
        """
        if not owner_identities:
            return []

        # Build a safe IN list for owner scoping (owner + corpus).
        owner_params = {f"o{i}": owner for i, owner in enumerate(owner_identities)}
        owner_placeholders = ", ".join(f":o{i}" for i in range(len(owner_identities)))
        sql = text(
            f"""
            SELECT
                id,
                (embedding <=> CAST(:qv AS VECTOR(1024))) AS distance
            FROM migration_memories
            WHERE embedding IS NOT NULL
              AND embedding_status = :ready
              AND owner_identity IN ({owner_placeholders})
            ORDER BY embedding <=> CAST(:qv AS VECTOR(1024))
            LIMIT :lim
            """
        )
        params: dict[str, object] = {
            "qv": query_vector_literal,
            "ready": EMBEDDING_STATUS_READY,
            "lim": limit,
            **owner_params,
        }
        result = await self._session.execute(sql, params)
        rows = result.all()
        if not rows:
            return []

        ids = [row[0] for row in rows]
        distance_by_id = {row[0]: float(row[1]) for row in rows}
        memories = await self._session.execute(
            select(MigrationMemory).where(MigrationMemory.id.in_(ids))
        )
        by_id = {m.id: m for m in memories.scalars().all()}
        ordered: list[tuple[MigrationMemory, float]] = []
        for mid in ids:
            mem = by_id.get(mid)
            if mem is None:
                continue
            dist = distance_by_id[mid]
            similarity = max(0.0, min(1.0, 1.0 - dist))
            ordered.append((mem, similarity))
        return ordered

    async def create(self, entity: MigrationMemory) -> MigrationMemory:
        return await super().create(entity)

    async def update(self, entity: MigrationMemory) -> MigrationMemory:
        return await super().update(entity)
