"""Memory browser + semantic search + corpus health HTTP routes."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import EmbeddingClientDep, get_db_session
from app.memory.constants import CORPUS_OWNER_IDENTITY
from app.memory.corpus_health import fetch_corpus_health, list_memories
from app.memory.embedding_client import vector_to_literal
from app.repositories.migration_memory_repository import MigrationMemoryRepository
from app.schemas.observability import (
    MemoryListItem,
    MemoryListResponse,
    MemorySearchHit,
    MemorySearchRequest,
    MemorySearchResponse,
)

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("/health")
async def get_corpus_health(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Structured corpus health for terminal + UI. Loud about problems."""
    return await fetch_corpus_health(session)


@router.get("", response_model=MemoryListResponse)
async def browse_memories(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    owner_identity: str | None = Query(
        default=None,
        description=(
            "Filter by owner. Use the reserved corpus owner identity "
            "(CORPUS_OWNER_IDENTITY) for the shared open-source corpus."
        ),
    ),
    embedding_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MemoryListResponse:
    from app.auth.tenancy import auth_enforced, session_owner

    if auth_enforced():
        owner_identity = session_owner(request)
    health = await fetch_corpus_health(session)
    rows, total = await list_memories(
        session,
        owner_identity=owner_identity,
        embedding_status=embedding_status,
        limit=limit,
        offset=offset,
        include_embed_text=True,
    )
    return MemoryListResponse(
        items=[MemoryListItem.from_orm_memory(m) for m in rows],
        total=total,
        limit=limit,
        offset=offset,
        health=health,
    )


@router.post("/search", response_model=MemorySearchResponse)
async def search_memories(
    request: Request,
    payload: MemorySearchRequest,
    embedding: EmbeddingClientDep,
    session: AsyncSession = Depends(get_db_session),
    owner_identity: str | None = Query(
        default=None,
        description=(
            "Owner to scope 'mine'/'all' to. Ignored when auth is enforced — "
            "the token's owner wins."
        ),
    ),
) -> MemorySearchResponse:
    """Semantic search over graded memories, on the CockroachDB distributed
    vector index.

    ``scope``:
      * ``corpus`` — the shared open-source corpus only (no owner predicate,
        rides the no-prefix partial index)
      * ``mine`` — this owner's graded runs only
      * ``all`` — both, which is what prediction-time retrieval uses
    """
    from app.auth.tenancy import auth_enforced, session_owner

    owner = session_owner(request) if auth_enforced() else owner_identity
    owner = (owner or "").strip()

    if payload.scope == "corpus":
        scopes: list[str] | None = [CORPUS_OWNER_IDENTITY]
    elif payload.scope == "mine":
        # Without an owner there is nothing personal to search. Return empty
        # rather than silently widening to the whole corpus.
        scopes = [owner] if owner else []
    else:  # "all" — owner + shared corpus, or corpus-wide when anonymous
        scopes = (
            list(dict.fromkeys([owner, CORPUS_OWNER_IDENTITY])) if owner else None
        )

    started = perf_counter()
    vector = embedding.embed(payload.query)
    repo = MigrationMemoryRepository(session)
    rows, index_used = await repo.semantic_search(
        query_vector_literal=vector_to_literal(vector),
        owner_identities=scopes,
        migration_type=payload.migration_type,
        scale_tier=payload.scale_tier,
        min_similarity=payload.min_similarity,
        limit=payload.limit,
    )
    took_ms = round((perf_counter() - started) * 1000.0, 2)

    return MemorySearchResponse(
        query=payload.query,
        scope=payload.scope,
        embedding_model_id=embedding.model_id,
        index_used=index_used,
        took_ms=took_ms,
        total=len(rows),
        results=[MemorySearchHit.from_orm_memory(m, s) for m, s in rows],
    )


@router.get("/corpus-identity")
async def get_corpus_identity() -> dict[str, str]:
    """Expose the reserved corpus owner constant for UI filters."""
    return {"corpus_owner_identity": CORPUS_OWNER_IDENTITY}
