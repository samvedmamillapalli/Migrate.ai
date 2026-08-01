"""vector_index_prefix_columns

Make the CockroachDB Distributed Vector Index actually reachable by the queries
this app issues.

``ix_migration_memories_embedding`` (added in h3c9f6a2b041) was created with no
prefix columns and no partial predicate. A CockroachDB vector index only accepts
equality predicates on its *prefix* columns, so any query carrying a WHERE
clause is structurally ineligible — and every query in this app carries one
(tenancy scoping on ``owner_identity``, readiness on ``embedding_status``). The
planner silently fell back to a filtered scan plus a brute-force top-k sort;
forcing the index raised "index ... cannot be used for this query".

Two replacement indexes, one per query shape the app actually issues:

* ``ix_migration_memories_embedding_scoped`` — owner-scoped hybrid retrieval
  (``MigrationMemoryRepository.vector_candidates``). ``owner_identity`` is a
  prefix column, so ``owner_identity IN (owner, corpus)`` becomes one prefix
  span per value.
* ``ix_migration_memories_embedding_ready`` — corpus-wide semantic search, which
  has no owner predicate but still must exclude non-ready embeddings.

Both carry ``WHERE embedding_status = 'ready'`` as a partial-index predicate,
which is how the readiness filter stops disqualifying the index.

Revision ID: m8h4e1f7a596
Revises: l7g3d0e6f485
Create Date: 2026-07-31 21:30:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone and
is guarded by an existence check — a killed or partial run can be re-run safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m8h4e1f7a596"
down_revision: Union[str, Sequence[str], None] = "l7g3d0e6f485"
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
    # Owner-scoped retrieval: prefix column + partial predicate.
    if not _index_exists("ix_migration_memories_embedding_scoped"):
        op.execute(
            """
            CREATE VECTOR INDEX IF NOT EXISTS ix_migration_memories_embedding_scoped
            ON migration_memories (owner_identity, embedding vector_cosine_ops)
            WHERE embedding_status = 'ready'
            """
        )

    # Corpus-wide semantic search: no owner predicate, same readiness predicate.
    if not _index_exists("ix_migration_memories_embedding_ready"):
        op.execute(
            """
            CREATE VECTOR INDEX IF NOT EXISTS ix_migration_memories_embedding_ready
            ON migration_memories (embedding vector_cosine_ops)
            WHERE embedding_status = 'ready'
            """
        )

    # NOTE: ix_migration_memories_embedding (unscoped, non-partial) is
    # deliberately left in place by this migration. It is now redundant — every
    # query in the app filters on embedding_status, so none of them can use it —
    # but dropping a vector index is a separate, heavier decision than adding
    # two. Drop it once corpus-wide search is confirmed running on
    # ix_migration_memories_embedding_ready; three cspann indexes on one table
    # is real write amplification on a memory layer that writes per graded run.


def downgrade() -> None:
    if _index_exists("ix_migration_memories_embedding_ready"):
        op.execute(
            "DROP INDEX IF EXISTS ix_migration_memories_embedding_ready CASCADE"
        )
    if _index_exists("ix_migration_memories_embedding_scoped"):
        op.execute(
            "DROP INDEX IF EXISTS ix_migration_memories_embedding_scoped CASCADE"
        )
