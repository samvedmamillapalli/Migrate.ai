"""CrossCustomerPromotionService — docs/cross_customer.md §5/§6.

Covers the two call sites' shared logic: consent gating, best-effort
never-raises behavior, and the dedup "is this more extreme" wiring on
``try_promote``; plus ``preview`` (§6's live informed-consent example),
which must never write anything and must degrade to ``None`` exactly like
``try_promote`` on any failure.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.cross_customer_anonymizer import AnonymizedRecord
from app.services.cross_customer_promotion_service import (
    CrossCustomerPromotionService,
    _is_more_extreme,
)


def _make_run(*, owner_identity: str = "acct-1") -> MagicMock:
    run = MagicMock()
    run.id = uuid.uuid4()
    run.owner_identity = owner_identity
    run.migration_sql = "ALTER TABLE customers ADD COLUMN discount_pct INT;"
    run.parsed_statement_types = ["AlterTable"]
    run.risk_flags = []
    return run


def _make_grade(
    *, outcome_class: str = "clean_ok", scalar_accuracy_score: float | None = 1.0
) -> MagicMock:
    grade = MagicMock()
    grade.scale_tier = "small"
    grade.outcome_class = outcome_class
    grade.scalar_accuracy_score = scalar_accuracy_score
    grade.lessons_learned = "lessons"
    grade.surprise_notes = "surprises"
    return grade


def _make_record(shape_hash: str = "hash-1") -> AnonymizedRecord:
    return AnonymizedRecord(
        sql_shape_template="ALTER TABLE TABLE_1 ADD COLUMN COL_1 INT;",
        generalized_summary="Adds a nullable integer column.",
        generalized_risk_narrative="Low risk, no locking concerns.",
        generalized_lessons_learned="Completed within the expected band.",
        generalized_surprise_notes=None,
        risk_flags=[],
        shape_hash=shape_hash,
    )


_UNSET = object()


def _make_service(
    *,
    is_enabled: bool = True,
    embedding_client: object = _UNSET,
) -> tuple[CrossCustomerPromotionService, MagicMock, MagicMock]:
    cc_repo = MagicMock()
    cc_repo.get_by_shape_hash = AsyncMock(return_value=None)
    cc_repo.upsert_by_shape_hash = AsyncMock()
    cc_repo.update = AsyncMock(side_effect=lambda entity: entity)

    prefs = MagicMock()
    prefs.is_enabled = AsyncMock(return_value=is_enabled)

    session = MagicMock()
    session.commit = AsyncMock()

    service = CrossCustomerPromotionService(
        session=session,
        cross_customer_repository=cc_repo,
        sharing_preference_repository=prefs,
        bedrock_client=MagicMock(),
        bedrock_model_id="test-model",
        embedding_client=MagicMock() if embedding_client is _UNSET else embedding_client,
        embedding_model_id="titan-test",
    )
    return service, cc_repo, prefs


# ----------------------------------------------------------------- consent


@pytest.mark.asyncio
async def test_try_promote_returns_none_when_not_consented() -> None:
    service, cc_repo, prefs = _make_service(is_enabled=False)
    result = await service.try_promote(
        run=_make_run(), prediction=None, grade=_make_grade()
    )
    assert result is None
    prefs.is_enabled.assert_awaited_once()
    cc_repo.upsert_by_shape_hash.assert_not_awaited()


@pytest.mark.asyncio
async def test_try_promote_force_bypasses_consent_check() -> None:
    # embedding_client=None here so this test only exercises the consent
    # bypass, not the embedding step (covered separately below).
    service, cc_repo, prefs = _make_service(is_enabled=False, embedding_client=None)
    entity = MagicMock(id=uuid.uuid4(), shape_hash="hash-1", contributor_count=1)
    entity.embedding_status = "pending"
    cc_repo.upsert_by_shape_hash = AsyncMock(return_value=(entity, True))

    with patch(
        "app.services.cross_customer_promotion_service.anonymize_migration_for_sharing",
        return_value=_make_record(),
    ):
        result = await service.try_promote(
            run=_make_run(), prediction=None, grade=_make_grade(), force=True
        )

    assert result is not None
    prefs.is_enabled.assert_not_awaited()


# ------------------------------------------------------- anonymization gate


@pytest.mark.asyncio
async def test_try_promote_returns_none_when_anonymization_rejects() -> None:
    service, cc_repo, _ = _make_service()
    with patch(
        "app.services.cross_customer_promotion_service.anonymize_migration_for_sharing",
        return_value=None,
    ):
        result = await service.try_promote(
            run=_make_run(), prediction=None, grade=_make_grade()
        )
    assert result is None
    cc_repo.upsert_by_shape_hash.assert_not_awaited()


# --------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_try_promote_new_shape_embeds_and_returns_result() -> None:
    service, cc_repo, _ = _make_service()
    entity = MagicMock(id=uuid.uuid4(), shape_hash="hash-1", contributor_count=1)
    entity.embedding_status = "pending"
    entity.generalized_summary = "Adds a nullable integer column."
    entity.generalized_risk_narrative = "Low risk, no locking concerns."
    entity.generalized_lessons_learned = "Completed within the expected band."
    entity.generalized_surprise_notes = None
    entity.sql_shape_template = "ALTER TABLE TABLE_1 ADD COLUMN COL_1 INT;"
    cc_repo.upsert_by_shape_hash = AsyncMock(return_value=(entity, True))
    embed_client = MagicMock()
    embed_client.embed = MagicMock(return_value=[0.1, 0.2, 0.3])
    service._embed = embed_client  # noqa: SLF001 - simplest way to swap post-construction

    with patch(
        "app.services.cross_customer_promotion_service.anonymize_migration_for_sharing",
        return_value=_make_record(),
    ):
        result = await service.try_promote(
            run=_make_run(), prediction=None, grade=_make_grade()
        )

    assert result == {
        "cross_customer_memory_id": str(entity.id),
        "shape_hash": "hash-1",
        "created": True,
        "contributor_count": 1,
    }
    embed_client.embed.assert_called_once()
    cc_repo.update.assert_awaited_once()
    assert entity.embedding_status == "ready"


@pytest.mark.asyncio
async def test_try_promote_embedding_failure_still_returns_result() -> None:
    """Embedding is enrichment on top of enrichment — a Titan failure must
    not turn a successful anonymized promotion into a failed one; the row
    is left pending for later repair, same posture as the private-tier
    write in app/memory/writer.py."""
    service, cc_repo, _ = _make_service()
    entity = MagicMock(id=uuid.uuid4(), shape_hash="hash-1", contributor_count=1)
    entity.embedding_status = "pending"
    entity.generalized_summary = "s"
    entity.generalized_risk_narrative = "r"
    entity.generalized_lessons_learned = "l"
    entity.generalized_surprise_notes = None
    entity.sql_shape_template = "t"
    cc_repo.upsert_by_shape_hash = AsyncMock(return_value=(entity, True))
    embed_client = MagicMock()
    embed_client.embed = MagicMock(side_effect=RuntimeError("titan down"))
    service._embed = embed_client  # noqa: SLF001

    with patch(
        "app.services.cross_customer_promotion_service.anonymize_migration_for_sharing",
        return_value=_make_record(),
    ):
        result = await service.try_promote(
            run=_make_run(), prediction=None, grade=_make_grade()
        )

    assert result is not None
    assert entity.embedding_status == "pending"
    assert entity.embedding_error is not None


@pytest.mark.asyncio
async def test_try_promote_dedup_hit_computes_is_more_extreme_from_existing_row() -> None:
    """A dedup hit must compare against the *existing* stored row, not
    assume True — regression coverage for the exact wiring, since a bug
    here would silently make every dedup hit look "more extreme" and churn
    re-embeds for nothing."""
    service, cc_repo, _ = _make_service()
    existing = MagicMock(outcome_class="clean_ok", scalar_accuracy_score=1.0)
    cc_repo.get_by_shape_hash = AsyncMock(return_value=existing)
    entity = MagicMock(id=uuid.uuid4(), shape_hash="hash-1", contributor_count=2)
    entity.embedding_status = "ready"
    cc_repo.upsert_by_shape_hash = AsyncMock(return_value=(entity, False))

    with patch(
        "app.services.cross_customer_promotion_service.anonymize_migration_for_sharing",
        return_value=_make_record(),
    ):
        await service.try_promote(
            run=_make_run(), prediction=None, grade=_make_grade(outcome_class="clean_ok")
        )

    _, kwargs = cc_repo.upsert_by_shape_hash.call_args
    # Same severity, same score as the existing row -> not more extreme.
    assert kwargs["is_more_extreme_outcome"] is False


# --------------------------------------------------------- never-raises


@pytest.mark.asyncio
async def test_try_promote_never_raises_on_unexpected_repository_error() -> None:
    service, cc_repo, _ = _make_service()
    cc_repo.get_by_shape_hash = AsyncMock(side_effect=RuntimeError("db exploded"))

    with patch(
        "app.services.cross_customer_promotion_service.anonymize_migration_for_sharing",
        return_value=_make_record(),
    ):
        result = await service.try_promote(
            run=_make_run(), prediction=None, grade=_make_grade()
        )

    assert result is None


# --------------------------------------------------------------------- preview


def test_preview_returns_generalized_fields_and_writes_nothing() -> None:
    service, cc_repo, _ = _make_service()
    with patch(
        "app.services.cross_customer_promotion_service.anonymize_migration_for_sharing",
        return_value=_make_record(),
    ):
        result = service.preview(run=_make_run(), prediction=None, grade=_make_grade())

    assert result is not None
    assert result["sql_shape_template"] == "ALTER TABLE TABLE_1 ADD COLUMN COL_1 INT;"
    assert result["generalized_summary"] == "Adds a nullable integer column."
    cc_repo.upsert_by_shape_hash.assert_not_awaited()
    cc_repo.get_by_shape_hash.assert_not_awaited()


def test_preview_returns_none_when_anonymization_rejects() -> None:
    service, _, _ = _make_service()
    with patch(
        "app.services.cross_customer_promotion_service.anonymize_migration_for_sharing",
        return_value=None,
    ):
        result = service.preview(run=_make_run(), prediction=None, grade=_make_grade())
    assert result is None


def test_preview_never_raises_on_unexpected_error() -> None:
    service, _, _ = _make_service()
    with patch(
        "app.services.cross_customer_promotion_service.anonymize_migration_for_sharing",
        side_effect=RuntimeError("bedrock exploded"),
    ):
        result = service.preview(run=_make_run(), prediction=None, grade=_make_grade())
    assert result is None


# --------------------------------------------------------- _is_more_extreme


def test_is_more_extreme_worse_outcome_class_wins() -> None:
    assert _is_more_extreme(
        new_outcome_class="bad",
        new_score=0.9,
        existing_outcome_class="clean_ok",
        existing_score=0.1,
    ) is True


def test_is_more_extreme_same_severity_lower_score_wins() -> None:
    assert _is_more_extreme(
        new_outcome_class="clean_ok",
        new_score=0.2,
        existing_outcome_class="clean_ok",
        existing_score=0.9,
    ) is True


def test_is_more_extreme_same_severity_higher_score_loses() -> None:
    assert _is_more_extreme(
        new_outcome_class="clean_ok",
        new_score=0.9,
        existing_outcome_class="clean_ok",
        existing_score=0.2,
    ) is False
