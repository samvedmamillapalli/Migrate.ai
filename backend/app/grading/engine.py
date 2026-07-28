"""Deterministic grading engine — model never decides the grade."""

from __future__ import annotations

from typing import Any

from app.database.models import ExecutionResult, Prediction, RollbackRisk
from app.grading.config import get_grading_file
from app.grading.models import GradingFile, NumericGradeResult


def classify_rollback_actual(
    *,
    success: bool,
    rollback_required: bool,
    timed_out: bool,
) -> str:
    """Map execution outcome to low / medium / high rollback actual class.

    - low: clean success, reversible, no rollback required
    - high: failed, irreversible, or timeout (budget blow — treat as high risk)
    - medium: success but rollback_required, or ambiguous mixed signals
    """
    if timed_out or not success:
        return "high"
    if rollback_required:
        return "medium"
    return "low"


def classify_outcome(
    *,
    success: bool,
    rollback_required: bool,
    timed_out: bool,
    high_risk_flags: bool,
) -> str:
    if timed_out:
        return "timeout"
    if not success or rollback_required:
        return "bad"
    if high_risk_flags:
        return "warned_ok"
    return "clean_ok"


def _pct_error(
    predicted: float,
    actual: float,
    *,
    min_actual: float,
) -> float | None:
    if abs(actual) < min_actual:
        return None
    return abs(predicted - actual) / abs(actual) * 100.0


def _within_band(
    *,
    abs_error: float,
    pct_error: float | None,
    max_abs: float,
    max_pct: float,
) -> bool:
    if abs_error <= max_abs:
        return True
    if pct_error is not None and pct_error <= max_pct:
        return True
    return False


def compute_numeric_grade(
    *,
    prediction: Prediction,
    execution: ExecutionResult,
    scale_tier: str,
    high_risk_flags_present: bool,
    config: GradingFile | None = None,
) -> NumericGradeResult:
    """Compare prediction vs actuals. Pure function; no model involvement."""
    cfg = config or get_grading_file()
    tier = scale_tier if scale_tier in cfg.error_bands else "medium"
    bands = cfg.error_bands[tier]
    timed_out = bool(execution.timed_out)

    predicted_duration = float(prediction.estimated_duration_seconds)
    actual_duration = float(execution.actual_duration_seconds)
    predicted_storage = float(prediction.estimated_storage_mb)
    actual_storage = float(execution.actual_storage_mb)

    duration_unverifiable = timed_out
    if duration_unverifiable:
        duration_abs = None
        duration_pct = None
        duration_within: bool | None = None
    else:
        duration_abs = abs(predicted_duration - actual_duration)
        duration_pct = _pct_error(
            predicted_duration,
            actual_duration,
            min_actual=cfg.pct_error_min_actual.duration_seconds,
        )
        duration_within = _within_band(
            abs_error=duration_abs,
            pct_error=duration_pct,
            max_abs=float(bands.duration.max_abs_seconds or 0.0),
            max_pct=bands.duration.max_pct,
        )

    storage_abs = abs(predicted_storage - actual_storage)
    storage_pct = _pct_error(
        predicted_storage,
        actual_storage,
        min_actual=cfg.pct_error_min_actual.storage_mb,
    )
    # Below the floor, approximate disk-stat storage can't reliably resolve a
    # real delta from measurement noise — grading it "within band" anyway
    # (trivially true for a near-zero abs_error) would be generous, not
    # honest. Treated like a timed-out duration: unverifiable, not a pass.
    storage_unverifiable = (
        predicted_storage < cfg.storage_unverifiable_floor_mb
        and actual_storage < cfg.storage_unverifiable_floor_mb
    )
    storage_within: bool | None
    if storage_unverifiable:
        storage_within = None
    else:
        storage_within = _within_band(
            abs_error=storage_abs,
            pct_error=storage_pct,
            max_abs=float(bands.storage.max_abs_mb or 0.0),
            max_pct=bands.storage.max_pct,
        )

    rollback_predicted = (
        prediction.rollback_risk.value
        if isinstance(prediction.rollback_risk, RollbackRisk)
        else str(prediction.rollback_risk)
    )
    rollback_actual = classify_rollback_actual(
        success=execution.success,
        rollback_required=execution.rollback_required,
        timed_out=timed_out,
    )
    consistent_pairs = {
        (a.lower(), b.lower()) for a, b in cfg.rollback.consistent_pairs
    }
    rollback_consistent = (rollback_predicted.lower(), rollback_actual) in consistent_pairs
    # Rollback "within band" == consistent with documented mapping.
    rollback_within = rollback_consistent

    outcome = classify_outcome(
        success=execution.success,
        rollback_required=execution.rollback_required,
        timed_out=timed_out,
        high_risk_flags=high_risk_flags_present,
    )

    # Scalar accuracy: mean of within-band dimensions that are verifiable.
    # Timeout makes duration contribute 0; the storage floor makes storage
    # contribute 0 the same way. Formula is frozen once corpus runs begin.
    scores: list[float] = []
    if duration_unverifiable:
        scores.append(0.0)
    elif duration_within is not None:
        scores.append(1.0 if duration_within else 0.0)
    if storage_unverifiable:
        scores.append(0.0)
    else:
        scores.append(1.0 if storage_within else 0.0)
    scores.append(1.0 if rollback_within else 0.0)
    scalar = round(sum(scores) / len(scores), 6)

    any_miss = False
    if duration_unverifiable:
        any_miss = True
    elif duration_within is False:
        any_miss = True
    if storage_unverifiable or not storage_within or not rollback_within:
        any_miss = True

    details: dict[str, Any] = {
        "duration": {
            "predicted": predicted_duration,
            "actual": actual_duration,
            "abs_error": duration_abs,
            "pct_error": duration_pct,
            "within_band": duration_within,
            "unverifiable": duration_unverifiable,
        },
        "storage": {
            "predicted": predicted_storage,
            "actual": actual_storage,
            "abs_error": storage_abs,
            "pct_error": storage_pct,
            "within_band": storage_within,
            "unverifiable": storage_unverifiable,
        },
        "rollback": {
            "predicted": rollback_predicted,
            "actual_class": rollback_actual,
            "consistent": rollback_consistent,
            "within_band": rollback_within,
        },
        "scalar_formula": (
            "mean of within-band scores for duration, storage, and rollback; "
            "timeout sets duration score to 0, and storage below the "
            "measurement floor sets storage score to 0 the same way"
        ),
    }

    return NumericGradeResult(
        scale_tier=tier,
        timed_out=timed_out,
        duration_abs_error_seconds=duration_abs,
        duration_pct_error=duration_pct,
        duration_within_band=duration_within,
        duration_unverifiable=duration_unverifiable,
        storage_abs_error_mb=storage_abs,
        storage_pct_error=storage_pct,
        storage_unverifiable=storage_unverifiable,
        storage_within_band=storage_within,
        rollback_predicted=rollback_predicted,
        rollback_actual_class=rollback_actual,
        rollback_consistent=rollback_consistent,
        rollback_within_band=rollback_within,
        outcome_class=outcome,
        high_risk_flags_present=high_risk_flags_present,
        adjusted_confidence=float(prediction.confidence_score),
        scalar_accuracy_score=scalar,
        dimension_details=details,
        any_miss=any_miss,
    )
