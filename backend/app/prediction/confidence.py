"""Hybrid confidence: model proposes, deterministic code only reduces."""

from __future__ import annotations

from app.policy.models import FindingSeverity, PolicyAnalysisResult
from app.prediction.memory import MemoryRetrievalResult
from app.prediction.models import ConfidenceAdjustment
from app.shadow.models import ScaleTier, TIER_ROW_CAPS


# Reduction amounts (absolute). Adjustments only lower confidence.
WEAK_RETRIEVAL_REDUCTION = 0.20
SCHEMA_SIZE_MISMATCH_REDUCTION = 0.10
UNCOMMON_MIGRATION_REDUCTION = 0.08
UNUSUAL_RISK_REDUCTION = 0.15

# Statement types from sqlglot alone are too coarse (Create/Alter/Drop cover
# almost everything). Prefer compact taxonomy from memory.embed_text.
_COMMON_MIGRATION_TYPES = frozenset(
    {
        "create_index",
        "add_column",
        "create_table",
        "alter_column",
    }
)


def adjust_confidence(
    raw_confidence: float,
    *,
    policy: PolicyAnalysisResult,
    memories: MemoryRetrievalResult,
    scale_tier: ScaleTier | str | None,
    snapshot_total_rows: int | None,
    migration_sql: str | None = None,
) -> tuple[float, list[ConfidenceAdjustment]]:
    """Return (adjusted_confidence, adjustments). Never raises the raw value."""
    score = max(0.0, min(1.0, raw_confidence))
    adjustments: list[ConfidenceAdjustment] = []

    def apply(reason_code: str, reason: str, amount: float) -> None:
        nonlocal score
        reduction = min(amount, score)
        if reduction <= 0:
            return
        score = round(score - reduction, 6)
        adjustments.append(
            ConfidenceAdjustment(
                reason_code=reason_code,
                reason=reason,
                amount=reduction,
            )
        )

    # 1. Weak retrieval support (conditional on real retrieval strength)
    explain = memories.to_explainability()
    if memories.is_empty or explain.get("weak_retrieval"):
        count = explain.get("retrieved_count", len(memories.memories))
        if memories.is_empty:
            reason = (
                "No similar past migrations were retrieved "
                f"(retrieved_count={count})."
            )
        else:
            reason = (
                "Retrieved memories have weak similarity support "
                f"(retrieved_count={count}; all below weak_similarity_threshold)."
            )
        apply("weak_retrieval", reason, WEAK_RETRIEVAL_REDUCTION)

    # 2. Schema size mismatch vs shadow scale tier
    tier = scale_tier.value if isinstance(scale_tier, ScaleTier) else scale_tier
    if tier and snapshot_total_rows is not None:
        try:
            tier_enum = ScaleTier(tier)
            cap = TIER_ROW_CAPS[tier_enum]
            if snapshot_total_rows > cap * 10:
                apply(
                    "schema_size_mismatch",
                    (
                        f"Shadow scale tier '{tier}' caps synthetic rows at {cap:,}, "
                        f"but the schema snapshot totals ~{snapshot_total_rows:,} rows."
                    ),
                    SCHEMA_SIZE_MISMATCH_REDUCTION,
                )
        except ValueError:
            pass

    # 3. Uncommon migration type (taxonomy, not raw sqlglot class names)
    from app.memory.embed_text import classify_migration_type

    migration_type = classify_migration_type(
        list(policy.parsed_statement_types),
        migration_sql or "",
    )
    if policy.parse_failed or migration_type not in _COMMON_MIGRATION_TYPES:
        apply(
            "uncommon_migration_type",
            (
                f"Migration type '{migration_type}' is uncommon or was not fully "
                "parsed relative to typical additive DDL the system expects."
            ),
            UNCOMMON_MIGRATION_REDUCTION,
        )

    # 4. Unusual risk from deterministic layer
    high_findings = [
        f for f in policy.risk_flags if f.severity == FindingSeverity.HIGH
    ]
    if policy.parse_failed or high_findings:
        detail = (
            "parse failure"
            if policy.parse_failed
            else ", ".join(sorted({f.rule_id for f in high_findings}))
        )
        apply(
            "unusual_risk",
            f"Deterministic layer flagged unusual risk ({detail}).",
            UNUSUAL_RISK_REDUCTION,
        )

    return score, adjustments
