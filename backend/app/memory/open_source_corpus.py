"""Seed curated open-source migration memories into the shared corpus.

Each record is derived from a public repo (SQL file + documented incident/outcome).
These are NOT shadow-verified graded runs. Integrity metadata marks them as
documented incidents so accuracy metrics and UI copy can exclude them.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.aws.config import AwsSettings, get_aws_settings
from app.core.logging import get_logger
from app.database.models import (
    ExecutionResult,
    Grade,
    MigrationMemory,
    MigrationRun,
    MigrationRunStatus,
    Prediction,
    RollbackRisk,
)
from app.memory.constants import (
    CORPUS_OWNER_IDENTITY,
    EMBEDDING_STATUS_PENDING,
    EMBEDDING_STATUS_READY,
    LEGACY_DEMO_CORPUS_OWNER,
    MEMORY_ORIGIN_OPEN_SOURCE_INCIDENT,
    MEMORY_ORIGIN_SYNTHETIC_SEED,
)
from app.memory.embed_text import classify_migration_type, compose_embed_text
from app.memory.embedding_client import (
    AwsTitanEmbeddingClient,
    EmbeddingAccessError,
    EmbeddingClient,
    EmbeddingInvocationError,
    vector_to_literal,
)
from app.repositories.migration_memory_repository import MigrationMemoryRepository

logger = get_logger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "open_source_corpus"
_SOURCE_RUN_NS = uuid.UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


def integrity_block(
    *,
    source_key: str,
    source_url: str | None,
    project: str | None = None,
) -> dict[str, Any]:
    """Label open-source incidents so they never look like graded shadow runs."""
    return {
        "kind": MEMORY_ORIGIN_OPEN_SOURCE_INCIDENT,
        "not_a_graded_run": True,
        "exclude_from_accuracy_metrics": True,
        "open_source_key": source_key,
        "source_url": source_url,
        "project": project,
        "ui_label": "Documented open-source incident (not a Migration Oracle graded run)",
    }


@dataclass(frozen=True)
class OpenSourceRecord:
    source_key: str
    migration_sql: str
    migration_summary: str
    scale_tier: str
    migration_type: str
    parsed_statement_types: list[str]
    schema_summary: str
    index_count: int
    table_complexity: int
    risk_flags: list[dict[str, Any]]
    risk_narrative: str
    lessons_learned: str
    surprise_notes: str | None
    prediction_summary: dict[str, Any]
    grade_summary: dict[str, Any]
    documented_outcomes: dict[str, Any]
    metadata: dict[str, Any]
    source_url: str | None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> OpenSourceRecord:
        source_key = str(payload["source_key"])
        source_url = (
            payload.get("incident_issue")
            or payload.get("source_url")
            or payload.get("migration_file")
        )
        project = payload.get("project")
        grade = dict(payload.get("grade_summary") or {})
        grade["open_source_key"] = source_key
        grade["provenance"] = "open_source_corpus"
        grade["integrity"] = integrity_block(
            source_key=source_key,
            source_url=str(source_url) if source_url else None,
            project=str(project) if project else None,
        )
        meta = {
            k: payload[k]
            for k in (
                "project",
                "repo",
                "license",
                "migration_file",
                "incident_issue",
                "source_url",
                "full_migration_sql",
            )
            if k in payload
        }
        summary = str(
            payload.get("migration_summary")
            or payload.get("mechanism_summary")
            or ""
        ).strip()
        if not summary:
            raise ValueError(
                f"{source_key}: migration_summary (mechanism prose) is required"
            )
        return cls(
            source_key=source_key,
            migration_sql=str(payload["migration_sql"]),
            migration_summary=summary,
            scale_tier=str(payload.get("scale_tier") or "medium"),
            migration_type=str(payload.get("migration_type") or "unknown"),
            parsed_statement_types=list(payload.get("parsed_statement_types") or []),
            schema_summary=str(payload.get("schema_summary") or ""),
            index_count=int(payload.get("index_count") or 0),
            table_complexity=int(payload.get("table_complexity") or 0),
            risk_flags=list(payload.get("risk_flags") or []),
            risk_narrative=str(payload.get("risk_narrative") or ""),
            lessons_learned=str(payload.get("lessons_learned") or ""),
            surprise_notes=payload.get("surprise_notes"),
            prediction_summary=dict(payload.get("prediction_summary") or {}),
            grade_summary=grade,
            documented_outcomes=dict(payload.get("documented_outcomes") or {}),
            metadata=meta,
            source_url=str(source_url) if source_url else None,
        )


def load_open_source_records() -> list[OpenSourceRecord]:
    if not _DATA_DIR.is_dir():
        return []
    records: list[OpenSourceRecord] = []
    for path in sorted(_DATA_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records.append(OpenSourceRecord.from_json(payload))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping open-source corpus file %s: %s", path.name, exc)
    return records


def source_run_id(source_key: str) -> uuid.UUID:
    return uuid.uuid5(_SOURCE_RUN_NS, source_key)


def assert_corpus_owner(owner_identity: str) -> None:
    if owner_identity != CORPUS_OWNER_IDENTITY:
        raise ValueError(
            f"Corpus entries must use CORPUS_OWNER_IDENTITY; got {owner_identity!r}"
        )


async def rekey_legacy_demo_corpus_owners(session: AsyncSession) -> int:
    """Idempotently move legacy 'demo-corpus' rows onto the reserved identity."""
    result = await session.execute(
        select(MigrationMemory).where(
            MigrationMemory.owner_identity == LEGACY_DEMO_CORPUS_OWNER
        )
    )
    rows = list(result.scalars().all())
    if not rows:
        return 0
    for mem in rows:
        mem.owner_identity = CORPUS_OWNER_IDENTITY
        grade = dict(mem.grade_summary or {})
        integrity = dict(grade.get("integrity") or {})
        integrity.setdefault("kind", MEMORY_ORIGIN_SYNTHETIC_SEED)
        integrity["not_a_graded_run"] = True
        integrity["exclude_from_accuracy_metrics"] = True
        integrity["ui_label"] = (
            "Synthetic seed memory (not a Migration Oracle graded shadow run)"
        )
        integrity["rekeyed_from"] = LEGACY_DEMO_CORPUS_OWNER
        grade["integrity"] = integrity
        grade["seed"] = True
        mem.grade_summary = grade
        # Also fix the parent run owner when present.
        run = await session.get(MigrationRun, mem.migration_run_id)
        if run is not None and run.owner_identity == LEGACY_DEMO_CORPUS_OWNER:
            run.owner_identity = CORPUS_OWNER_IDENTITY
        grade_row = (
            await session.execute(
                select(Grade).where(Grade.migration_run_id == mem.migration_run_id)
            )
        ).scalar_one_or_none()
        if grade_row is not None:
            details = dict(grade_row.dimension_details or {})
            details["seed"] = True
            details["integrity"] = integrity
            grade_row.dimension_details = details
            if grade_row.prose_status not in {"open_source"}:
                grade_row.prose_status = "seed"
    await session.execute(
        update(MigrationRun)
        .where(MigrationRun.owner_identity == LEGACY_DEMO_CORPUS_OWNER)
        .values(owner_identity=CORPUS_OWNER_IDENTITY)
    )
    await session.commit()
    logger.info("Re-keyed %s legacy demo-corpus memories to reserved identity", len(rows))
    return len(rows)


async def _find_by_source_key(
    session: AsyncSession,
    source_key: str,
) -> MigrationMemory | None:
    result = await session.execute(
        select(MigrationMemory).where(
            MigrationMemory.grade_summary["open_source_key"].astext == source_key
        )
    )
    return result.scalar_one_or_none()


def _rollback_risk(raw: str | None) -> RollbackRisk:
    try:
        return RollbackRisk((raw or "low").lower())
    except ValueError:
        return RollbackRisk.LOW


def _embed_text_for(rec: OpenSourceRecord) -> str:
    return compose_embed_text(
        migration_summary=rec.migration_summary,
        risk_narrative=rec.risk_narrative,
        lessons_learned=rec.lessons_learned,
        surprise_notes=rec.surprise_notes,
        migration_sql=rec.migration_sql,
    )


async def ensure_open_source_corpus(
    session: AsyncSession,
    *,
    embedding_client: EmbeddingClient | None = None,
    embedding_model_id: str | None = None,
    aws_settings: AwsSettings | None = None,
) -> dict[str, Any]:
    """Idempotently insert curated open-source memories (with embeddings when possible)."""
    rekeyed = await rekey_legacy_demo_corpus_owners(session)

    records = load_open_source_records()
    if not records:
        return {
            "seeded": 0,
            "skipped": 0,
            "repaired_embeddings": 0,
            "rekeyed_demo_corpus": rekeyed,
            "records": [],
        }

    aws = aws_settings or get_aws_settings()
    embed = embedding_client
    model_id = (embedding_model_id or aws.bedrock_embedding_model_id or "").strip() or None
    if embed is None and aws.aws_enabled and model_id:
        try:
            embed = AwsTitanEmbeddingClient(settings=aws)
        except Exception as exc:
            logger.warning("Open-source corpus: embedding client unavailable: %s", exc)

    repo = MigrationMemoryRepository(session)
    seeded = 0
    skipped = 0
    repaired = 0
    details: list[dict[str, Any]] = []

    for rec in records:
        existing = await _find_by_source_key(session, rec.source_key)
        embed_text = _embed_text_for(rec)
        mig_type = rec.migration_type or classify_migration_type(
            rec.parsed_statement_types,
            rec.migration_sql,
        )

        needs_embed = True
        if (
            existing is not None
            and existing.embedding_status == EMBEDDING_STATUS_READY
            and existing.embed_text == embed_text
            and existing.owner_identity == CORPUS_OWNER_IDENTITY
        ):
            skipped += 1
            details.append({"source_key": rec.source_key, "status": "exists"})
            continue

        embedding_literal: str | None = None
        embedding_status = EMBEDDING_STATUS_PENDING
        embedding_error: str | None = None
        if embed is not None and needs_embed:
            try:
                vector = embed.embed(embed_text, model_id=model_id)
                embedding_literal = vector_to_literal(vector)
                embedding_status = EMBEDDING_STATUS_READY
            except (EmbeddingAccessError, EmbeddingInvocationError, Exception) as exc:
                embedding_error = f"{type(exc).__name__}: {exc}"[:2000]
                logger.warning(
                    "Open-source corpus embedding failed for %s: %s",
                    rec.source_key,
                    embedding_error,
                )

        if existing is not None:
            assert_corpus_owner(CORPUS_OWNER_IDENTITY)
            existing.owner_identity = CORPUS_OWNER_IDENTITY
            existing.migration_summary = rec.migration_summary
            existing.schema_summary = rec.schema_summary
            existing.risk_flags = rec.risk_flags
            existing.lessons_learned = rec.lessons_learned
            existing.surprise_notes = rec.surprise_notes
            existing.grade_summary = rec.grade_summary
            existing.prediction_summary = rec.prediction_summary
            existing.recommendation_summary = {
                "recommended_strategy": "See documented incident lessons",
                "source_url": rec.source_url,
                "integrity": rec.grade_summary.get("integrity"),
            }
            existing.embed_text = embed_text
            if embedding_literal is not None:
                existing.embedding = embedding_literal
                existing.embedding_status = embedding_status
                existing.embedding_error = embedding_error
                existing.embedding_model_id = model_id
            elif existing.embedding_status != EMBEDDING_STATUS_READY:
                existing.embedding_status = embedding_status
                existing.embedding_error = embedding_error
            existing.index_count = rec.index_count
            existing.table_complexity = rec.table_complexity
            existing.migration_type = mig_type
            existing.scale_tier = rec.scale_tier
            await repo.update(existing)
            if embedding_status == EMBEDDING_STATUS_READY:
                repaired += 1
            details.append(
                {
                    "source_key": rec.source_key,
                    "status": "updated",
                    "embedding_status": existing.embedding_status,
                }
            )
            continue

        assert_corpus_owner(CORPUS_OWNER_IDENTITY)
        pred_raw = rec.prediction_summary
        run_id = source_run_id(rec.source_key)
        run = MigrationRun(
            id=run_id,
            migration_sql=rec.migration_sql,
            status=MigrationRunStatus.COMPLETED,
            owner_identity=CORPUS_OWNER_IDENTITY,
            prediction_scale_tier=rec.scale_tier,
            parsed_statement_types=rec.parsed_statement_types,
            risk_flags=rec.risk_flags,
            explainability={
                "open_source": rec.metadata,
                "integrity": rec.grade_summary.get("integrity"),
            },
        )
        session.add(run)
        await session.flush()

        pred = Prediction(
            migration_run_id=run.id,
            estimated_duration_seconds=float(
                pred_raw.get("estimated_duration_seconds") or 60.0
            ),
            estimated_storage_mb=float(pred_raw.get("estimated_storage_mb") or 10.0),
            rollback_risk=_rollback_risk(str(pred_raw.get("rollback_risk"))),
            confidence_score=float(pred_raw.get("confidence_score") or 0.5),
            raw_confidence_score=float(pred_raw.get("confidence_score") or 0.5),
            confidence_adjustments=[],
            reasoning=str(pred_raw.get("risk_explanation") or rec.risk_narrative),
            key_assumptions=["open_source_documented_incident"],
            uncertainty_notes=[
                "Not a Migration Oracle graded run — documented public incident only."
            ],
            model_version=f"open-source:{rec.source_key}",
            prompt_template_version="n/a",
        )
        doc = rec.documented_outcomes
        exec_row = ExecutionResult(
            migration_run_id=run.id,
            success=bool(doc.get("success", False)),
            actual_duration_seconds=float(doc.get("actual_duration_seconds") or 0.0),
            actual_storage_mb=float(doc.get("actual_storage_mb") or 0.0),
            rollback_required=bool(doc.get("rollback_required", False)),
            timed_out=bool(doc.get("timed_out", False)),
            error_message=doc.get("error_message"),
        )
        grade = Grade(
            migration_run_id=run.id,
            scale_tier=rec.scale_tier,
            timed_out=bool(doc.get("timed_out", False)),
            duration_abs_error_seconds=0.0,
            duration_pct_error=0.0,
            duration_within_band=bool(rec.grade_summary.get("duration_within_band")),
            duration_unverifiable=doc.get("actual_duration_seconds") is None,
            storage_abs_error_mb=0.0,
            storage_pct_error=0.0,
            storage_within_band=bool(
                rec.grade_summary.get("storage_within_band", False)
            ),
            rollback_predicted=str(pred_raw.get("rollback_risk") or "low"),
            rollback_actual_class="required" if doc.get("rollback_required") else "none",
            rollback_consistent=False,
            rollback_within_band=bool(rec.grade_summary.get("rollback_within_band")),
            outcome_class=str(rec.grade_summary.get("outcome_class") or "documented"),
            high_risk_flags_present=bool(rec.risk_flags),
            adjusted_confidence=float(pred_raw.get("confidence_score") or 0.5),
            scalar_accuracy_score=float(
                rec.grade_summary.get("scalar_accuracy_score") or 0.0
            ),
            dimension_details={
                **(rec.grade_summary.get("dimension_details") or {}),
                "source": "open_source",
                "integrity": rec.grade_summary.get("integrity"),
            },
            surprise_notes=rec.surprise_notes,
            lessons_learned=rec.lessons_learned,
            prose_status="open_source",
        )
        memory = MigrationMemory(
            migration_run_id=run.id,
            owner_identity=CORPUS_OWNER_IDENTITY,
            scale_tier=rec.scale_tier,
            migration_type=mig_type,
            migration_summary=rec.migration_summary,
            schema_summary=rec.schema_summary,
            risk_flags=rec.risk_flags,
            prediction_summary=rec.prediction_summary,
            recommendation_summary={
                "recommended_strategy": "See documented incident lessons",
                "source_url": rec.source_url,
                "integrity": rec.grade_summary.get("integrity"),
            },
            approval_summary={"decision": "proceed", "open_source": True},
            execution_summary={
                "success": exec_row.success,
                "actual_duration_seconds": exec_row.actual_duration_seconds,
                "actual_storage_mb": exec_row.actual_storage_mb,
                "rollback_required": exec_row.rollback_required,
                "timed_out": exec_row.timed_out,
                "error_message": exec_row.error_message,
            },
            grade_summary=rec.grade_summary,
            lessons_learned=rec.lessons_learned,
            surprise_notes=rec.surprise_notes,
            embed_text=embed_text,
            embedding=embedding_literal,
            embedding_status=embedding_status,
            embedding_error=embedding_error,
            embedding_model_id=model_id,
            index_count=rec.index_count,
            table_complexity=rec.table_complexity,
        )
        session.add_all([pred, exec_row, grade, memory])
        seeded += 1
        details.append(
            {
                "source_key": rec.source_key,
                "status": "seeded",
                "embedding_status": embedding_status,
                "migration_run_id": str(run.id),
                "source_url": rec.source_url,
            }
        )

    if seeded or repaired:
        await session.commit()
    else:
        await session.rollback()

    return {
        "seeded": seeded,
        "skipped": skipped,
        "repaired_embeddings": repaired,
        "rekeyed_demo_corpus": rekeyed,
        "records": details,
    }
