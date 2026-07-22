"""Memory browser + corpus health HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session
from app.memory.constants import CORPUS_OWNER_IDENTITY
from app.memory.corpus_health import fetch_corpus_health, list_memories
from app.schemas.observability import MemoryListItem, MemoryListResponse

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("/health")
async def get_corpus_health(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Structured corpus health for terminal + UI. Loud about problems."""
    return await fetch_corpus_health(session)


@router.get("", response_model=MemoryListResponse)
async def browse_memories(
    session: AsyncSession = Depends(get_db_session),
    owner_identity: str | None = Query(
        default=None,
        description=(
            "Filter by owner. Use __migration_oracle_corpus__ for the reserved "
            "shared corpus identity."
        ),
    ),
    embedding_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MemoryListResponse:
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


@router.get("/corpus-identity")
async def get_corpus_identity() -> dict[str, str]:
    """Expose the reserved corpus owner constant for UI filters."""
    return {"corpus_owner_identity": CORPUS_OWNER_IDENTITY}
