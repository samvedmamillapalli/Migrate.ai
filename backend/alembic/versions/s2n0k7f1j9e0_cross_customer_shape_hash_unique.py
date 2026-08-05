"""cross_customer_shape_hash_unique

Bug fix, found in adversarial review before adding concurrent auto-promotion
(Phase 2): ``cross_customer_memories.shape_hash`` had a plain (non-unique)
index (r1m9j6e0i8d9), and ``CrossCustomerMemoryRepository.upsert_by_shape_hash``
did a check-then-insert (fetch by shape_hash, insert if absent) with no
constraint to make that atomic. Two promotions computing the same shape_hash
concurrently could both observe "no existing row" and both insert, producing
duplicate rows for the same shape — silently breaking the dedup/aggregation
story in docs/cross_customer.md §7 (contributor_count would undercount), and
making a later call to ``get_by_shape_hash`` (which uses
``scalar_one_or_none()``) raise ``MultipleResultsFound`` outright.

This was low-risk while promotion was only ever driven by the single-threaded
manual script (Phase 1), but Phase 2 wires promotion into write_memory,
which runs per graded run across concurrent requests — the race becomes
real. Fixing the constraint here; the repository's insert path is updated in
the same change to catch the resulting unique-violation and fall back to the
increment path instead of raising.

Revision ID: s2n0k7f1j9e0
Revises: r1m9j6e0i8d9
Create Date: 2026-08-04 10:00:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone
and is guarded by an existence check — a killed or partial run can be re-run
safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s2n0k7f1j9e0"
down_revision: Union[str, Sequence[str], None] = "r1m9j6e0i8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(index: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = current_schema() AND indexname = :i"
        ),
        {"i": index},
    ).first()
    return row is not None


def upgrade() -> None:
    # Drop the old plain index and replace it with a unique one. CockroachDB
    # has no ADD CONSTRAINT ... UNIQUE USING INDEX shortcut here, so this
    # is a straightforward drop-then-recreate — safe because the only row
    # in the table as of this migration (from the docs/cross_customer.md §9
    # synthetic proof) is already unique by construction (one shape_hash per
    # distinct migration shape).
    if _index_exists("ix_cross_customer_memories_shape_hash") and not _index_exists(
        "uq_cross_customer_memories_shape_hash"
    ):
        op.execute(
            "DROP INDEX IF EXISTS ix_cross_customer_memories_shape_hash CASCADE"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_cross_customer_memories_shape_hash "
            "ON cross_customer_memories (shape_hash)"
        )


def downgrade() -> None:
    if _index_exists("uq_cross_customer_memories_shape_hash"):
        op.execute(
            "DROP INDEX IF EXISTS uq_cross_customer_memories_shape_hash CASCADE"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cross_customer_memories_shape_hash "
            "ON cross_customer_memories (shape_hash)"
        )
