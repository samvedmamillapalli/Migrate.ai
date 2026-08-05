"""Promote a graded run into the anonymized cross-customer pool.

Shared by two callers with different urgency: ``scripts/promote_cross_customer_memory.py``
(manual, Phase 1) and ``MemoryWriteService.write_memory`` (automatic, Phase 2
— see docs/cross_customer.md §5). Both need the exact same consent check,
anonymization pipeline call, dedup upsert, and embedding steps; this class
exists so that logic is written and tested once, not duplicated between a
script and a service.

Best-effort throughout: ``try_promote`` never raises. A failure at any step
(no consent, anonymization pipeline rejection, embedding failure) results in
``None``, logged, and the caller's own work (writing the private-tier
memory, grading the run) is completely unaffected — same posture as every
other enrichment in this app.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.models import ExecutionResult, Grade, MigrationRun, Prediction
from app.memory.cross_customer_anonymizer import anonymize_migration_for_sharing
from app.memory.embed_text import classify_migration_type, compose_embed_text
from app.memory.embedding_client import EmbeddingClient, vector_to_literal
from app.memory.constants import EMBEDDING_STATUS_READY
from app.prediction.bedrock_client import BedrockClient
from app.repositories.cross_customer_memory_repository import (
    CrossCustomerMemoryRepository,
)
from app.repositories.memory_sharing_preference_repository import (
    MemorySharingPreferenceRepository,
)

logger = get_logger(__name__)

_OUTCOME_SEVERITY = {
    "timeout": 3,
    "bad": 3,
    "warned_ok": 2,
    "clean_ok": 1,
}


def _is_more_extreme(
    *,
    new_outcome_class: str,
    new_score: float | None,
    existing_outcome_class: str,
    existing_score: float | None,
) -> bool:
    """docs/cross_customer.md §7 — a worse outcome than what's stored is
    more valuable to warn future users with; a routine success replacing an
    existing routine success teaches nothing new."""
    new_sev = _OUTCOME_SEVERITY.get(new_outcome_class, 0)
    existing_sev = _OUTCOME_SEVERITY.get(existing_outcome_class, 0)
    if new_sev != existing_sev:
        return new_sev > existing_sev
    if new_score is None or existing_score is None:
        return False
    return new_score < existing_score  # lower accuracy = more surprising


class CrossCustomerPromotionService:
    """Consent-gated, best-effort promotion of one graded run."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        cross_customer_repository: CrossCustomerMemoryRepository,
        sharing_preference_repository: MemorySharingPreferenceRepository,
        bedrock_client: BedrockClient,
        bedrock_model_id: str,
        embedding_client: EmbeddingClient | None,
        embedding_model_id: str | None = None,
    ) -> None:
        # BaseRepository only flushes ("Callers own commit/rollback." —
        # app/repositories/base.py); try_promote is the caller, so it must
        # commit its own writes explicitly. Found missing via live proof
        # (scripts/prove_automatic_cross_customer_promotion.py) — without
        # this, a successful upsert/embed was flushed but never durably
        # committed, and disappeared once the request's session closed.
        self._session = session
        self._cc_repo = cross_customer_repository
        self._prefs = sharing_preference_repository
        self._bedrock = bedrock_client
        self._bedrock_model_id = bedrock_model_id
        self._embed = embedding_client
        self._embed_model_id = (embedding_model_id or "").strip() or None

    async def try_promote(
        self,
        *,
        run: MigrationRun,
        prediction: Prediction | None,
        grade: Grade,
        force: bool = False,
    ) -> dict[str, Any] | None:
        """Returns a small result dict on success, ``None`` on any
        skip/failure (never raises). ``force`` bypasses the consent check —
        reserved for the synthetic-account proof
        (docs/cross_customer.md §9); never pass True against a real
        account's run.
        """
        try:
            if not force:
                enabled = await self._prefs.is_enabled(run.owner_identity)
                if not enabled:
                    return None

            migration_type = classify_migration_type(
                run.parsed_statement_types, run.migration_sql
            )
            risk_narrative = prediction.reasoning if prediction else ""

            record = anonymize_migration_for_sharing(
                bedrock_client=self._bedrock,
                bedrock_model_id=self._bedrock_model_id,
                migration_sql=run.migration_sql,
                migration_summary=run.migration_sql[:200],
                risk_narrative=risk_narrative,
                lessons_learned=grade.lessons_learned,
                surprise_notes=grade.surprise_notes,
                risk_flags=run.risk_flags,
                scale_tier=grade.scale_tier,
                outcome_class=grade.outcome_class,
                schema_snapshot=run.schema_snapshot,
            )
            if record is None:
                # Already logged inside anonymize_migration_for_sharing with
                # the specific reason (parse failure, Bedrock failure, or a
                # caught identifier leak).
                return None

            existing = await self._cc_repo.get_by_shape_hash(record.shape_hash)
            is_more_extreme = (
                True
                if existing is None
                else _is_more_extreme(
                    new_outcome_class=grade.outcome_class,
                    new_score=grade.scalar_accuracy_score,
                    existing_outcome_class=existing.outcome_class,
                    existing_score=existing.scalar_accuracy_score,
                )
            )

            entity, created = await self._cc_repo.upsert_by_shape_hash(
                shape_hash=record.shape_hash,
                migration_type=migration_type,
                scale_tier=grade.scale_tier,
                parsed_statement_types=list(run.parsed_statement_types or []),
                generalized_summary=record.generalized_summary,
                generalized_risk_narrative=record.generalized_risk_narrative,
                generalized_lessons_learned=record.generalized_lessons_learned,
                generalized_surprise_notes=record.generalized_surprise_notes,
                sql_shape_template=record.sql_shape_template,
                risk_flags=record.risk_flags,
                outcome_class=grade.outcome_class,
                scalar_accuracy_score=grade.scalar_accuracy_score,
                is_more_extreme_outcome=is_more_extreme,
            )

            needs_embedding = created or entity.embedding_status == "pending"
            if needs_embedding and self._embed is not None:
                embed_text = compose_embed_text(
                    migration_summary=entity.generalized_summary,
                    risk_narrative=entity.generalized_risk_narrative,
                    lessons_learned=entity.generalized_lessons_learned,
                    surprise_notes=entity.generalized_surprise_notes,
                    migration_sql=entity.sql_shape_template,
                )
                try:
                    vector = self._embed.embed(embed_text, model_id=self._embed_model_id)
                    entity.embedding = vector_to_literal(vector)
                    entity.embedding_status = EMBEDDING_STATUS_READY
                    entity.embedding_model_id = self._embed_model_id
                except Exception as exc:  # noqa: BLE001 - embedding is enrichment here too
                    entity.embedding_status = "pending"
                    entity.embedding_error = f"{type(exc).__name__}: {exc}"[:2000]
                    logger.warning(
                        "Cross-customer embedding failed; row left pending",
                        extra={"run_id": str(run.id), "error": entity.embedding_error},
                    )
                entity = await self._cc_repo.update(entity)

            await self._session.commit()

            logger.info(
                "Cross-customer memory promoted",
                extra={
                    "run_id": str(run.id),
                    "cross_customer_memory_id": str(entity.id),
                    "shape_hash": entity.shape_hash,
                    # NOT "created" — that collides with the reserved
                    # LogRecord.created attribute (record creation
                    # timestamp) and makes the logging call itself raise
                    # KeyError, which the outer except then reports as "the
                    # whole promotion failed" even though the DB write
                    # already succeeded. Found via live proof
                    # (scripts/prove_automatic_cross_customer_promotion.py).
                    "row_created": created,
                    "contributor_count": entity.contributor_count,
                },
            )
            return {
                "cross_customer_memory_id": str(entity.id),
                "shape_hash": entity.shape_hash,
                "created": created,
                "contributor_count": entity.contributor_count,
            }
        except Exception as exc:  # noqa: BLE001 - never let promotion crash the caller
            logger.warning(
                "Cross-customer promotion failed unexpectedly; skipping",
                extra={"run_id": str(run.id), "error": f"{type(exc).__name__}: {exc}"},
            )
            return None

    def preview(
        self,
        *,
        run: MigrationRun,
        prediction: Prediction | None,
        grade: Grade,
    ) -> dict[str, Any] | None:
        """Run the §3 anonymization pipeline WITHOUT writing anything —
        docs/cross_customer.md §6: the settings toggle must show a real
        example of what would be shared before the user confirms opting in,
        not an abstract privacy policy. Same pipeline ``try_promote`` uses,
        deliberately stopping short of the dedup upsert / embedding steps
        (there is nothing to store yet — this account hasn't consented).
        Never raises; ``None`` means the pipeline couldn't produce a clean
        example for this run (logged with the specific reason).
        """
        try:
            risk_narrative = prediction.reasoning if prediction else ""
            record = anonymize_migration_for_sharing(
                bedrock_client=self._bedrock,
                bedrock_model_id=self._bedrock_model_id,
                migration_sql=run.migration_sql,
                migration_summary=run.migration_sql[:200],
                risk_narrative=risk_narrative,
                lessons_learned=grade.lessons_learned,
                surprise_notes=grade.surprise_notes,
                risk_flags=run.risk_flags,
                scale_tier=grade.scale_tier,
                outcome_class=grade.outcome_class,
                schema_snapshot=run.schema_snapshot,
            )
            if record is None:
                return None
            return {
                "run_id": str(run.id),
                "sql_shape_template": record.sql_shape_template,
                "generalized_summary": record.generalized_summary,
                "generalized_risk_narrative": record.generalized_risk_narrative,
                "generalized_lessons_learned": record.generalized_lessons_learned,
                "generalized_surprise_notes": record.generalized_surprise_notes,
                "risk_flags": record.risk_flags,
            }
        except Exception as exc:  # noqa: BLE001 - preview is best-effort too
            logger.warning(
                "Cross-customer preview failed unexpectedly",
                extra={"run_id": str(run.id), "error": f"{type(exc).__name__}: {exc}"},
            )
            return None
