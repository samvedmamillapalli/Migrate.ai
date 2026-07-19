"""SQL-backed accuracy / learning metrics + optional CloudWatch publish."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.aws.observability import CloudWatchObservability
from app.core.logging import get_logger

logger = get_logger(__name__)

METRIC_SCALAR_ACCURACY = "PredictionScalarAccuracy"
METRIC_RECOMMENDATION_ACCEPTANCE = "RecommendationAcceptanceRate"
METRIC_RECOMMENDATION_SUCCESS = "RecommendationSuccessRate"
METRIC_RETRIEVAL_STRENGTH = "RetrievalUsefulCount"


async def fetch_accuracy_metrics(session: AsyncSession) -> dict[str, Any]:
    """Plain SQL aggregates over grades / memories for Phase 11 charts."""
    scalar_trend = (
        await session.execute(
            text(
                """
                SELECT
                    g.created_at,
                    g.scalar_accuracy_score,
                    g.scale_tier,
                    g.adjusted_confidence,
                    g.outcome_class,
                    mr.parsed_statement_types
                FROM grades g
                JOIN migration_runs mr ON mr.id = g.migration_run_id
                ORDER BY g.created_at ASC
                """
            )
        )
    ).mappings().all()

    calibration = (
        await session.execute(
            text(
                """
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
                FROM grades
                GROUP BY 1
                ORDER BY 1
                """
            )
        )
    ).mappings().all()

    recommendation = (
        await session.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE recommendation ->> 'recommended_strategy' IS NOT NULL
                    ) AS recommendations_issued,
                    COUNT(*) FILTER (
                        WHERE approval_decision = 'accept_recommended'
                    ) AS accepted,
                    COUNT(*) FILTER (
                        WHERE recommendation_outcome -> 'linked_evidence'
                            ->> 'status' = 'success'
                    ) AS linked_successes,
                    COUNT(*) FILTER (
                        WHERE recommendation_outcome -> 'linked_evidence' IS NOT NULL
                    ) AS linked_pairs
                FROM (
                    SELECT
                        mr.recommendation,
                        mr.recommendation_outcome,
                        a.decision AS approval_decision
                    FROM migration_runs mr
                    LEFT JOIN approvals a ON a.migration_run_id = mr.id
                ) t
                """
            )
        )
    ).mappings().one()

    by_tier = (
        await session.execute(
            text(
                """
                SELECT scale_tier,
                       AVG(scalar_accuracy_score) AS mean_scalar,
                       COUNT(*) AS n
                FROM grades
                GROUP BY scale_tier
                ORDER BY scale_tier
                """
            )
        )
    ).mappings().all()

    retrieval = (
        await session.execute(
            text(
                """
                SELECT
                    COUNT(*) AS memories_ready,
                    COUNT(*) FILTER (WHERE embedding_status = 'pending') AS pending,
                    AVG((grade_summary->>'scalar_accuracy_score')::float)
                        AS mean_scalar_in_memory
                FROM migration_memories
                """
            )
        )
    ).mappings().one()

    high_risk = (
        await session.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE high_risk_flags_present
                          AND outcome_class IN ('failure', 'partial', 'timeout')
                    ) AS true_positive,
                    COUNT(*) FILTER (
                        WHERE high_risk_flags_present
                          AND outcome_class NOT IN ('failure', 'partial', 'timeout')
                    ) AS false_positive,
                    COUNT(*) FILTER (
                        WHERE NOT high_risk_flags_present
                          AND outcome_class IN ('failure', 'partial', 'timeout')
                    ) AS false_negative,
                    COUNT(*) FILTER (
                        WHERE NOT high_risk_flags_present
                          AND outcome_class NOT IN ('failure', 'partial', 'timeout')
                    ) AS true_negative
                FROM grades
                """
            )
        )
    ).mappings().one()

    retrieval_usefulness = (
        await session.execute(
            text(
                """
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
                """
            )
        )
    ).mappings().one()

    issued = int(recommendation["recommendations_issued"] or 0)
    accepted = int(recommendation["accepted"] or 0)
    linked = int(recommendation["linked_pairs"] or 0)
    linked_ok = int(recommendation["linked_successes"] or 0)

    tp = int(high_risk["true_positive"] or 0)
    fp = int(high_risk["false_positive"] or 0)
    fn = int(high_risk["false_negative"] or 0)
    tn = int(high_risk["true_negative"] or 0)
    precision = (tp / (tp + fp)) if (tp + fp) else None
    recall = (tp / (tp + fn)) if (tp + fn) else None

    return {
        "scalar_accuracy_trend": [dict(row) for row in scalar_trend],
        "confidence_calibration": [dict(row) for row in calibration],
        "recommendation_rates": {
            "acceptance": {
                "numerator": accepted,
                "denominator": issued,
                "rate": (accepted / issued) if issued else None,
            },
            "success": {
                "numerator": linked_ok,
                "denominator": linked,
                "rate": (linked_ok / linked) if linked else None,
                "note": "Success only counted from linked revised-run evidence",
            },
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
        rates = metrics.get("recommendation_rates") or {}
        acc = rates.get("acceptance") or {}
        if acc.get("rate") is not None:
            await observability.put_metric(
                METRIC_RECOMMENDATION_ACCEPTANCE,
                float(acc["rate"]),
                unit="None",
            )
        suc = rates.get("success") or {}
        if suc.get("rate") is not None:
            await observability.put_metric(
                METRIC_RECOMMENDATION_SUCCESS,
                float(suc["rate"]),
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
