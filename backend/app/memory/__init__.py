"""Phase 10 agentic memory: embed, write, hybrid retrieve.

``retrieval.py`` and ``writer.py`` are deliberately NOT imported here (only
re-exported lazily via ``__getattr__`` below). Both modules reach into
``app.repositories.*``, and those repository modules import back from
``app.memory.constants`` — importing ``retrieval``/``writer`` eagerly at
package-init time makes ``app.memory`` and ``app.repositories`` a real
circular import pair, order-dependent on which side gets touched first.
Reproduced concretely: a bare ``import
app.repositories.cross_customer_memory_repository`` (nothing about
app.memory involved yet) crashed with a partial-init ``ImportError`` before
this fix, because *its* ``from app.memory.constants import ...`` triggered
this file, which used to import ``retrieval.py``, which imports the very
module still mid-import. ``constants.py`` and ``embedding_client.py`` have
no such cycle (dependency-free / aws-only) so they stay eager.
"""

from app.memory.constants import CORPUS_OWNER_IDENTITY, EMBEDDING_DIMENSIONS
from app.memory.embedding_client import (
    AwsTitanEmbeddingClient,
    EmbeddingAccessError,
    EmbeddingClient,
    EmbeddingInvocationError,
    MockEmbeddingClient,
    vector_to_literal,
)

__all__ = [
    "CORPUS_OWNER_IDENTITY",
    "EMBEDDING_DIMENSIONS",
    "AwsTitanEmbeddingClient",
    "EmbeddingAccessError",
    "EmbeddingClient",
    "EmbeddingInvocationError",
    "HybridMemoryRetrieval",
    "MemoryWriteService",
    "MockEmbeddingClient",
    "vector_to_literal",
]


def __getattr__(name: str):
    # PEP 562 lazy attribute access, so `from app.memory import
    # HybridMemoryRetrieval` (used by scripts/verify_phase10_grading_memory.py)
    # keeps working without paying the eager-import cycle above. Callers
    # inside the app itself import the submodules directly
    # (`app.memory.retrieval`, `app.memory.writer`) and never hit this path.
    if name == "HybridMemoryRetrieval":
        from app.memory.retrieval import HybridMemoryRetrieval

        return HybridMemoryRetrieval
    if name == "MemoryWriteService":
        from app.memory.writer import MemoryWriteService

        return MemoryWriteService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
