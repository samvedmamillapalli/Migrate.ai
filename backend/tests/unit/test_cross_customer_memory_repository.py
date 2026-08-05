"""CrossCustomerMemoryRepository.upsert_by_shape_hash — dedup + the race fix.

The test that matters here: two "concurrent" promotions of the same
shape_hash must never both succeed as inserts. Found in adversarial review
(migration s2n0k7f1j9e0) — the original check-then-insert had a real gap
between the SELECT and the INSERT.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.database.models import CrossCustomerMemory
from app.repositories.cross_customer_memory_repository import (
    CrossCustomerMemoryRepository,
    _is_unique_violation,
)


class _FakeOrigWithSqlstate:
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


def _make_unique_violation() -> IntegrityError:
    return IntegrityError(
        "duplicate key value violates unique constraint",
        params=None,
        orig=_FakeOrigWithSqlstate("23505"),
    )


def _make_other_integrity_error() -> IntegrityError:
    return IntegrityError(
        "some other constraint",
        params=None,
        orig=_FakeOrigWithSqlstate("23503"),  # foreign_key_violation
    )


def test_is_unique_violation_detects_23505() -> None:
    assert _is_unique_violation(_make_unique_violation()) is True


def test_is_unique_violation_rejects_other_sqlstate() -> None:
    assert _is_unique_violation(_make_other_integrity_error()) is False


def _existing_row(shape_hash: str) -> CrossCustomerMemory:
    return CrossCustomerMemory(
        id=uuid.uuid4(),
        shape_hash=shape_hash,
        migration_type="add_column",
        scale_tier="small",
        parsed_statement_types=["AlterTable"],
        generalized_summary="old summary",
        generalized_risk_narrative="old risk",
        generalized_lessons_learned="old lessons",
        generalized_surprise_notes=None,
        sql_shape_template="ALTER TABLE TABLE_1 ADD COLUMN COL_1 INT",
        risk_flags=[],
        outcome_class="clean_ok",
        scalar_accuracy_score=1.0,
        contributor_count=1,
        last_contributed_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_upsert_creates_new_row_when_no_existing() -> None:
    session = AsyncMock()
    repo = CrossCustomerMemoryRepository(session)
    repo.get_by_shape_hash = AsyncMock(return_value=None)
    repo.create = AsyncMock(side_effect=lambda entity: entity)

    entity, created = await repo.upsert_by_shape_hash(
        shape_hash="abc123",
        migration_type="add_column",
        scale_tier="small",
        parsed_statement_types=["AlterTable"],
        generalized_summary="s",
        generalized_risk_narrative="r",
        generalized_lessons_learned="l",
        generalized_surprise_notes=None,
        sql_shape_template="t",
        risk_flags=[],
        outcome_class="clean_ok",
        scalar_accuracy_score=1.0,
        is_more_extreme_outcome=True,
    )
    assert created is True
    assert entity.shape_hash == "abc123"
    repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_increments_existing_without_replacing_text_when_not_more_extreme() -> None:
    session = AsyncMock()
    repo = CrossCustomerMemoryRepository(session)
    existing = _existing_row("abc123")
    repo.get_by_shape_hash = AsyncMock(return_value=existing)
    repo.update = AsyncMock(side_effect=lambda entity: entity)

    entity, created = await repo.upsert_by_shape_hash(
        shape_hash="abc123",
        migration_type="add_column",
        scale_tier="small",
        parsed_statement_types=["AlterTable"],
        generalized_summary="new summary",
        generalized_risk_narrative="new risk",
        generalized_lessons_learned="new lessons",
        generalized_surprise_notes=None,
        sql_shape_template="new template",
        risk_flags=[],
        outcome_class="clean_ok",
        scalar_accuracy_score=1.0,
        is_more_extreme_outcome=False,
    )
    assert created is False
    assert entity.contributor_count == 2
    # Text NOT replaced — this contribution wasn't more extreme than what's stored.
    assert entity.generalized_summary == "old summary"


@pytest.mark.asyncio
async def test_upsert_replaces_text_when_more_extreme() -> None:
    session = AsyncMock()
    repo = CrossCustomerMemoryRepository(session)
    existing = _existing_row("abc123")
    repo.get_by_shape_hash = AsyncMock(return_value=existing)
    repo.update = AsyncMock(side_effect=lambda entity: entity)

    entity, created = await repo.upsert_by_shape_hash(
        shape_hash="abc123",
        migration_type="add_column",
        scale_tier="small",
        parsed_statement_types=["AlterTable"],
        generalized_summary="new summary",
        generalized_risk_narrative="new risk",
        generalized_lessons_learned="new lessons",
        generalized_surprise_notes=None,
        sql_shape_template="new template",
        risk_flags=[],
        outcome_class="bad",
        scalar_accuracy_score=0.1,
        is_more_extreme_outcome=True,
    )
    assert created is False
    assert entity.contributor_count == 2
    assert entity.generalized_summary == "new summary"
    assert entity.embedding_status == "pending"  # needs re-embedding


@pytest.mark.asyncio
async def test_upsert_falls_back_to_increment_on_lost_race() -> None:
    """The regression test: get_by_shape_hash first says "no row" (this
    caller's own read), but create() then hits a real unique-violation
    because a concurrent promotion won the race in between. Must recover
    by rolling back and incrementing the row that won — never raise, never
    leave two rows for the same shape_hash."""
    session = AsyncMock()
    repo = CrossCustomerMemoryRepository(session)

    winner_row = _existing_row("abc123")
    # First call: "no existing row" (this caller's own read, before losing
    # the race). Second call: the re-fetch after catching the conflict,
    # which finds the row the other promotion just committed.
    repo.get_by_shape_hash = AsyncMock(side_effect=[None, winner_row])
    repo.create = AsyncMock(side_effect=_make_unique_violation())
    repo.update = AsyncMock(side_effect=lambda entity: entity)

    entity, created = await repo.upsert_by_shape_hash(
        shape_hash="abc123",
        migration_type="add_column",
        scale_tier="small",
        parsed_statement_types=["AlterTable"],
        generalized_summary="new summary",
        generalized_risk_narrative="new risk",
        generalized_lessons_learned="new lessons",
        generalized_surprise_notes=None,
        sql_shape_template="new template",
        risk_flags=[],
        outcome_class="clean_ok",
        scalar_accuracy_score=1.0,
        is_more_extreme_outcome=False,
    )

    assert created is False
    assert entity.contributor_count == 2  # incremented the winner's row
    session.rollback.assert_awaited_once()  # recovered the failed insert
    repo.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_reraises_non_unique_violation_errors() -> None:
    session = AsyncMock()
    repo = CrossCustomerMemoryRepository(session)
    repo.get_by_shape_hash = AsyncMock(return_value=None)
    repo.create = AsyncMock(side_effect=_make_other_integrity_error())

    with pytest.raises(IntegrityError):
        await repo.upsert_by_shape_hash(
            shape_hash="abc123",
            migration_type="add_column",
            scale_tier="small",
            parsed_statement_types=["AlterTable"],
            generalized_summary="s",
            generalized_risk_narrative="r",
            generalized_lessons_learned="l",
            generalized_surprise_notes=None,
            sql_shape_template="t",
            risk_flags=[],
            outcome_class="clean_ok",
            scalar_accuracy_score=1.0,
            is_more_extreme_outcome=True,
        )
