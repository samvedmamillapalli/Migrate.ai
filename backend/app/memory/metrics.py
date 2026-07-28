"""SQL-backed accuracy / learning metrics + optional CloudWatch publish."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.aws.observability import CloudWatchObservability
from app.core.logging import get_logger
from app.memory.constants import CORPUS_OWNER_IDENTITY

logger = get_logger(__name__)

METRIC_SCALAR_ACCURACY = "PredictionScalarAccuracy"
METRIC_RECOMMENDATION_ACCEPTANCE = "RecommendationAcceptanceRate"
METRIC_RECOMMENDATION_SUCCESS = "RecommendationSuccessRate"
METRIC_RETRIEVAL_STRENGTH = "RetrievalUsefulCount"


async def fetch_accuracy_metrics(
    session: AsyncSession,
    *,
    owner_identity: str | None = None,
) -> dict[str, Any]:
    """Plain SQL aggregates over grades / memories for Phase 11 charts.

    Excludes open-source documented incidents and synthetic seed rows — those
    are not predicted-then-measured grades and must not inflate accuracy.
    When ``owner_identity`` is given, every run-scoped query below is filtered
    to that owner so this card and the Overview "Recent" list always describe
    the same population instead of silently comparing per-owner to global.
    """
    params: dict[str, Any] = {"owner_identity": owner_identity}
    # Shared predicate: only genuine graded outcomes count toward accuracy.
    _GRADE_OK = """
        COALESCE(g.prose_status, '') NOT IN ('open_source', 'seed')
        AND COALESCE(g.dimension_details->>'source', '') != 'open_source'
        AND COALESCE(g.dimension_details->>'seed', '') NOT IN ('true', 'True', '1')
        AND COALESCE(
              (SELECT mm.grade_summary->>'open_source_key'
               FROM migration_memories mm
               WHERE mm.migration_run_id = g.migration_run_id
               LIMIT 1),
              ''
            ) = ''
        AND COALESCE(
              (SELECT mm.grade_summary->'integrity'->>'kind'
               FROM migration_memories mm
               WHERE mm.migration_run_id = g.migration_run_id
               LIMIT 1),
              ''
            ) NOT IN (
              'open_source_documented_incident',
              'synthetic_seed'
            )
        AND (:owner_identity IS NULL OR mr.owner_identity = :owner_identity)
    """

    scalar_trend = (
        await session.execute(
            text(
                f"""
                SELECT
                    g.created_at,
                    g.scalar_accuracy_score,
                    g.scale_tier,
                    g.adjusted_confidence,
                    g.outcome_class,
                    mr.parsed_statement_types
                FROM grades g
                JOIN migration_runs mr ON mr.id = g.migration_run_id
                WHERE {_GRADE_OK}
                ORDER BY g.created_at ASC
                """
            ),
            params,
        )
    ).mappings().all()

    calibration = (
        await session.execute(
            text(
                f"""
                SELECT
                    CASE
                        WHEN adjusted_confidence < 0.4 THEN 'low'
                        WHEN adjusted_confidence < 0.7 THEN 'mid'
                        ELSE 'high'
                    END AS confidence_bucket,
                    AVG(
                        COALESCE(duration_abs_error_seconds, 0)
                        + storage_abs_error_mb
                    ) AS mean_abs_error,
                    AVG(scalar_accuracy_score) AS mean_scalar,
                    COUNT(*) AS n
                FROM grades g
                JOIN migration_runs mr ON mr.id = g.migration_run_id
                WHERE {_GRADE_OK}
                GROUP BY 1
                ORDER BY 1
                """
            ),
            params,
        )
    ).mappings().all()

    # Graded-population success rate: "percent of graded runs that passed",
    # same denominator as GRADED above (not a different, unrelated query).
    # A grade's outcome_class is one of clean_ok / warned_ok / bad / timeout
    # (app.grading.engine.classify_outcome) — "passed" means the migration
    # actually executed successfully, clean or with risk flags noted.
    migration_success = (
        await session.execute(
            text(
                f"""
                SELECT
                    COUNT(*) AS graded,
                    COUNT(*) FILTER (
                        WHERE g.outcome_class IN ('clean_ok', 'warned_ok')
                    ) AS passed
                FROM grades g
                JOIN migration_runs mr ON mr.id = g.migration_run_id
                WHERE {_GRADE_OK}
                """
            ),
            params,
        )
    ).mappings().one()

    # Honest approval-decision breakdown — real counts, called what they are,
    # not folded into an "accuracy" rate. Scoped to the same owner, excludes
    # the reserved corpus identity and deliberate chaos/debug test runs so a
    # judge's "Recent" list and this breakdown describe the same runs.
    approval_breakdown = (
        await session.execute(
            text(
                """
                SELECT
                    COALESCE(a.decision, 'awaiting_decision') AS decision,
                    COUNT(*) AS n
                FROM migration_runs mr
                LEFT JOIN approvals a ON a.migration_run_id = mr.id
                WHERE mr.owner_identity != :corpus_owner
                  AND mr.run_kind NOT IN ('chaos', 'debug')
                  AND (:owner_identity IS NULL OR mr.owner_identity = :owner_identity)
                GROUP BY 1
                """
            ),
            {**params, "corpus_owner": CORPUS_OWNER_IDENTITY},
        )
    ).mappings().all()

    by_tier = (
        await session.execute(
            text(
                f"""
                SELECT scale_tier,
                       AVG(scalar_accuracy_score) AS mean_scalar,
                       COUNT(*) AS n
                FROM grades g
                JOIN migration_runs mr ON mr.id = g.migration_run_id
                WHERE {_GRADE_OK}
                GROUP BY scale_tier
                ORDER BY scale_tier
                """
            ),
            params,
        )
    ).mappings().all()

    retrieval = (
        await session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS memories_ready,
                    COUNT(*) FILTER (WHERE embedding_status = 'pending') AS pending,
                    AVG(
                      CASE
                        WHEN COALESCE(grade_summary->>'open_source_key', '') = ''
                         AND COALESCE(grade_summary->'integrity'->>'kind', '')
                             NOT IN ('open_source_documented_incident', 'synthetic_seed')
                         AND COALESCE(grade_summary->>'seed', '') NOT IN ('true', 'True')
                        THEN (grade_summary->>'scalar_accuracy_score')::float
                        ELSE NULL
                      END
                    ) AS mean_scalar_in_memory
                FROM migration_memories
                """
            )
        )
    ).mappings().one()

    # outcome_class is one of clean_ok / warned_ok / bad / timeout
    # (app.grading.engine.classify_outcome) — 'failure'/'partial' were never
    # real values here, so this precision/recall table previously only ever
    # matched on 'timeout' and silently under-counted every non-timeout bad
    # outcome. Fixed to the actual "went badly" set: bad + timeout.
    high_risk = (
        await session.execute(
            text(
                f"""
                SELECT
                    COUNT(*) FILTER (
                        WHERE high_risk_flags_present
                          AND outcome_class IN ('bad', 'timeout')
                    ) AS true_positive,
                    COUNT(*) FILTER (
                        WHERE high_risk_flags_present
                          AND outcome_class NOT IN ('bad', 'timeout')
                    ) AS false_positive,
                    COUNT(*) FILTER (
                        WHERE NOT high_risk_flags_present
                          AND outcome_class IN ('bad', 'timeout')
                    ) AS false_negative,
                    COUNT(*) FILTER (
                        WHERE NOT high_risk_flags_present
                          AND outcome_class NOT IN ('bad', 'timeout')
                    ) AS true_negative
                FROM grades g
                JOIN migration_runs mr ON mr.id = g.migration_run_id
                WHERE {_GRADE_OK}
                """
            ),
            params,
        )
    ).mappings().one()

    retrieval_usefulness = (
        await session.execute(
            text(
                f"""
                SELECT
                    AVG(g.scalar_accuracy_score) AS mean_scalar,
                    AVG(
                        CASE
                          WHEN COALESCE(
                            (mr.explainability->'memory'->>'retrieved_count')::int, 0
                          ) > 0 THEN 1.0 ELSE 0.0
                        END
                    ) AS fraction_with_retrieval,
                    CORR(
                        g.scalar_accuracy_score,
                        COALESCE(
                          (mr.explainability->'memory'->>'retrieved_count')::float, 0
                        )
                    ) AS corr_retrieval_count_vs_accuracy
                FROM grades g
                JOIN migration_runs mr ON mr.id = g.migration_run_id
                WHERE {_GRADE_OK}
                """
            ),
            params,
        )
    ).mappings().one()

    graded_n = int(migration_success["graded"] or 0)
    passed_n = int(migration_success["passed"] or 0)

    approval_counts = {
        str(row["decision"]): int(row["n"] or 0) for row in approval_breakdown
    }
    approval_total = sum(approval_counts.values())

    tp = int(high_risk["true_positive"] or 0)
    fp = int(high_risk["false_positive"] or 0)
    fn = int(high_risk["false_negative"] or 0)
    tn = int(high_risk["true_negative"] or 0)
    precision = (tp / (tp + fp)) if (tp + fp) else None
    recall = (tp / (tp + fn)) if (tp + fn) else None

    return {
        "scalar_accuracy_trend": [dict(row) for row in scalar_trend],
        "confidence_calibration": [dict(row) for row in calibration],
        "migration_success_rate": {
            "numerator": passed_n,
            "denominator": graded_n,
            "rate": (passed_n / graded_n) if graded_n else None,
            "note": (
                "Percent of graded runs whose shadow execution actually "
                "succeeded (clean_ok or warned_ok), out of the same graded "
                "population as 'Graded' above."
            ),
        },
        "approval_breakdown": {
            "proceed": approval_counts.get("proceed", 0),
            "accept_recommended": approval_counts.get("accept_recommended", 0),
            "cancel": approval_counts.get("cancel", 0),
            "awaiting_decision": approval_counts.get("awaiting_decision", 0),
            "total": approval_total,
            "note": (
                "Real approval-decision counts, not an accuracy rate. "
                "Excludes the reserved corpus identity and chaos/debug runs."
            ),
        },
        "learning_by_scale_tier": [dict(row) for row in by_tier],
        "memory_corpus": dict(retrieval),
        "high_risk_flag_precision_recall": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
            "precision": precision,
            "recall": recall,
        },
        "retrieval_usefulness_vs_accuracy": dict(retrieval_usefulness),
        "integrity_note": (
            "Accuracy aggregates exclude open_source_documented_incident and "
            "synthetic_seed memories; those are not predicted-then-measured grades."
        ),
    }


async def publish_metrics_to_cloudwatch(
    metrics: dict[str, Any],
    observability: CloudWatchObservability | None,
) -> None:
    if observability is None:
        return
    try:
        trend = metrics.get("scalar_accuracy_trend") or []
        if trend:
            latest = trend[-1]
            await observability.put_metric(
                METRIC_SCALAR_ACCURACY,
                float(latest["scalar_accuracy_score"]),
                unit="None",
                dimensions={"ScaleTier": str(latest.get("scale_tier") or "unknown")},
            )
        success_rate = metrics.get("migration_success_rate") or {}
        if success_rate.get("rate") is not None:
            await observability.put_metric(
                METRIC_RECOMMENDATION_SUCCESS,
                float(success_rate["rate"]),
                unit="None",
            )
        approvals = metrics.get("approval_breakdown") or {}
        total = int(approvals.get("total") or 0)
        proceed = int(approvals.get("proceed") or 0)
        if total:
            await observability.put_metric(
                METRIC_RECOMMENDATION_ACCEPTANCE,
                proceed / total,
                unit="None",
            )
        corpus = metrics.get("memory_corpus") or {}
        ready = corpus.get("memories_ready")
        if ready is not None:
            await observability.put_metric(
                METRIC_RETRIEVAL_STRENGTH,
                float(ready),
                unit="Count",
            )
    except Exception as exc:  # noqa: BLE001 - metrics must not break grading
        logger.warning(
            "CloudWatch metrics publish failed",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
