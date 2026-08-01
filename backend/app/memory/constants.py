"""Agentic memory constants and helpers for Phase 10."""

# Reserved identity for the shared seeded corpus (Phase 12 writes under this).
# Never a real user. Retrieval always includes this scope alongside the owner.
# This string literal must appear ONLY in this module; import CORPUS_OWNER_IDENTITY elsewhere.
CORPUS_OWNER_IDENTITY = "__migration_oracle_corpus__"

# Legacy mistaken owner used by an early seed script; re-keyed at startup.
LEGACY_DEMO_CORPUS_OWNER = "demo-corpus"

# memory_origin / integrity.kind values
MEMORY_ORIGIN_GRADED_SHADOW = "graded_shadow"
MEMORY_ORIGIN_OPEN_SOURCE_INCIDENT = "open_source_documented_incident"
MEMORY_ORIGIN_SYNTHETIC_SEED = "synthetic_seed"

EMBEDDING_DIMENSIONS = 1024
EMBEDDING_STATUS_PENDING = "pending"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_FAILED = "failed"

# CockroachDB Distributed Vector Index names (Alembic m8h4e1f7a596). Both are
# partial indexes on `embedding_status = 'ready'`; the scoped one additionally
# carries `owner_identity` as a prefix column so tenant-scoped retrieval stays
# on the index. Declared here (a dependency-free module) so both the repository
# and app.memory.index_health can use them without an import cycle.
VECTOR_INDEX_SCOPED = "ix_migration_memories_embedding_scoped"
VECTOR_INDEX_READY = "ix_migration_memories_embedding_ready"

DEFAULT_TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"
# Documented example value for BEDROCK_EMBEDDING_MODEL_ID (.env.example / SAM).
# Prefer settings.bedrock_embedding_model_id at runtime — do not invent another id.
