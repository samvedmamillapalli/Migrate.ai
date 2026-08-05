from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.database.models import CrossCustomerMemory
from app.memory.constants import EMBEDDING_STATUS_READY
from app.repositories.base import BaseRepository

# CockroachDB / PostgreSQL unique_violation. Distinct from the
# serialization-failure (40001) app.database.retry.with_txn_retry already
# handles — a unique-constraint hit is not a transient conflict to retry
# as-is, it means "someone else already inserted this row", which
# upsert_by_shape_hash below turns into "fall back to the increment path"
# rather than raising.
_UNIQUE_VIOLATION_SQLSTATE = "23505"


def _is_unique_violation(exc: BaseException) -> bool:
    if isinstance(exc, DBAPIError) and exc.orig is not None:
        sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(
            exc.orig, "pgcode", None
        )
        if sqlstate:
            return str(sqlstate) == _UNIQUE_VIOLATION_SQLSTATE
    return isinstance(exc, IntegrityError) and "unique" in str(exc).lower()


class CrossCustomerMemoryRepository(BaseRepository[CrossCustomerMemory]):
    """Persistence for the anonymized, opt-in cross-tenant memory pool.

    See docs/cross_customer.md §1 — this table carries no owner/tenant
    identity of any kind, by design; nothing here should ever gain such a
    column.
    """

    model = CrossCustomerMemory

    @staticmethod
    def vector_candidates_sql(*, index_hint: str | None = None) -> str:
        """The nearest-neighbor SQL this repository issues, exposed as a
        string for the same reason ``MigrationMemoryRepository`` exposes
        its own — so a verification script or health check can ``EXPLAIN``
        the *exact* query, not a hand-copied approximation. See
        ``MigrationMemoryRepository.vector_candidates_sql`` and
        ``tests/unit/test_memory_vector_search.py``.

        Only ``embedding_status`` may appear in the WHERE clause: it is the
        partial-index predicate for
        ``ix_cross_customer_memories_embedding_ready``. There is no owner
        prefix column on this table (there is no owner column at all), so
        unlike the owner-scoped migration-memory query this one has nothing
        else to filter on structurally.
        """
        table = "cross_customer_memories"
        if index_hint:
            table = f"{table}@{index_hint}"
        return f"""
            SELECT
                id,
                (embedding <=> CAST(:qv AS VECTOR(1024))) AS distance
            FROM {table}
            WHERE embedding_status = :ready
            ORDER BY embedding <=> CAST(:qv AS VECTOR(1024))
            LIMIT :lim
            """

    async def vector_candidates(
        self,
        *,
        query_vector_literal: str,
        limit: int,
    ) -> list[tuple[CrossCustomerMemory, float]]:
        """Nearest neighbors via the Distributed Vector Index. Mirrors
        ``MigrationMemoryRepository.vector_candidates`` — see that method
        for why there's no ``embedding IS NOT NULL`` predicate (rows with a
        NULL vector aren't in the index at all, so the filter would only
        ever run after the top-k, shrinking the candidate pool below
        ``limit`` for nothing)."""
        sql = text(self.vector_candidates_sql())
        params: dict[str, object] = {
            "qv": query_vector_literal,
            "ready": EMBEDDING_STATUS_READY,
            "lim": limit,
        }
        result = await self._session.execute(sql, params)
        rows = result.all()
        if not rows:
            return []

        ids = [row[0] for row in rows]
        distance_by_id = {row[0]: float(row[1]) for row in rows}
        memories = await self._session.execute(
            select(CrossCustomerMemory).where(CrossCustomerMemory.id.in_(ids))
        )
        by_id = {m.id: m for m in memories.scalars().all()}
        ordered: list[tuple[CrossCustomerMemory, float]] = []
        for mid in ids:
            mem = by_id.get(mid)
            if mem is None:
                continue
            dist = distance_by_id[mid]
            similarity = max(0.0, min(1.0, 1.0 - dist))
            ordered.append((mem, similarity))
        return ordered

    async def get_by_shape_hash(self, shape_hash: str) -> CrossCustomerMemory | None:
        result = await self._session.execute(
            select(CrossCustomerMemory).where(
                CrossCustomerMemory.shape_hash == shape_hash
            )
        )
        return result.scalar_one_or_none()

    async def upsert_by_shape_hash(
        self,
        *,
        shape_hash: str,
        migration_type: str,
        scale_tier: str,
        parsed_statement_types: list[str],
        generalized_summary: str,
        generalized_risk_narrative: str,
        generalized_lessons_learned: str,
        generalized_surprise_notes: str | None,
        sql_shape_template: str,
        risk_flags: list[dict[str, Any]],
        outcome_class: str,
        scalar_accuracy_score: float | None,
        is_more_extreme_outcome: bool,
    ) -> tuple[CrossCustomerMemory, bool]:
        """Insert-vs-increment dedup, per docs/cross_customer.md §7.

        Returns ``(row, created)`` — ``created=True`` for a brand-new shape,
        ``False`` when an existing row's ``contributor_count`` was
        incremented instead. On a dedup hit, the stored generalized text is
        only replaced when ``is_more_extreme_outcome`` is True — a routine
        clean success replacing an existing routine clean success teaches
        future users nothing new; a worse outcome than what's stored is
        worth surfacing instead.

        Race-safe against two concurrent promotions computing the same
        ``shape_hash`` (a real scenario once promotion is wired into
        write_memory rather than driven by a single manual script — see
        migration s2n0k7f1j9e0): the check-then-insert below can still lose
        a race between the SELECT and the INSERT, so a unique-violation on
        insert is caught and treated as "someone else won, fall back to the
        increment path" rather than raised.
        """
        existing = await self.get_by_shape_hash(shape_hash)
        now = datetime.now(UTC)

        if existing is None:
            entity = CrossCustomerMemory(
                shape_hash=shape_hash,
                migration_type=migration_type,
                scale_tier=scale_tier,
                parsed_statement_types=parsed_statement_types,
                generalized_summary=generalized_summary,
                generalized_risk_narrative=generalized_risk_narrative,
                generalized_lessons_learned=generalized_lessons_learned,
                generalized_surprise_notes=generalized_surprise_notes,
                sql_shape_template=sql_shape_template,
                risk_flags=risk_flags,
                outcome_class=outcome_class,
                scalar_accuracy_score=scalar_accuracy_score,
                contributor_count=1,
            )
            try:
                entity = await self.create(entity)
                return entity, True
            except Exception as exc:  # noqa: BLE001 - narrowed immediately below
                if not _is_unique_violation(exc):
                    raise
                # Lost the race: roll back our failed insert so the session
                # is usable again, then fall through to the increment path
                # against the row that won.
                await self._session.rollback()
                existing = await self.get_by_shape_hash(shape_hash)
                if existing is None:
                    raise RuntimeError(
                        f"upsert_by_shape_hash: lost a unique-violation race "
                        f"for shape_hash={shape_hash!r} but the re-fetch "
                        "found no row — investigate rather than retry blindly"
                    ) from exc

        existing.contributor_count += 1
        existing.last_contributed_at = now
        if is_more_extreme_outcome:
            existing.generalized_summary = generalized_summary
            existing.generalized_risk_narrative = generalized_risk_narrative
            existing.generalized_lessons_learned = generalized_lessons_learned
            existing.generalized_surprise_notes = generalized_surprise_notes
            existing.sql_shape_template = sql_shape_template
            existing.risk_flags = risk_flags
            existing.outcome_class = outcome_class
            existing.scalar_accuracy_score = scalar_accuracy_score
            # A replaced generalized text needs a fresh embedding — caller
            # (the promotion script) is responsible for re-embedding and
            # setting embedding_status back to pending here when this flag
            # is True; this repository method only owns the row's columns.
            existing.embedding_status = "pending"
        existing = await self.update(existing)
        return existing, False
