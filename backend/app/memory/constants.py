"""Agentic memory constants and helpers for Phase 10."""

# Reserved identity for the shared seeded corpus (Phase 12 writes under this).
# Never a real user. Retrieval always includes this scope alongside the owner.
CORPUS_OWNER_IDENTITY = "__migration_oracle_corpus__"

EMBEDDING_DIMENSIONS = 1024
EMBEDDING_STATUS_PENDING = "pending"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_FAILED = "failed"

DEFAULT_TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"
# Documented example value for BEDROCK_EMBEDDING_MODEL_ID (.env.example / SAM).
# Prefer settings.bedrock_embedding_model_id at runtime — do not invent another id.
