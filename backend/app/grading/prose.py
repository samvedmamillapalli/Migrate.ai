"""Surprise notes + lessons learned via Bedrock — never blocks numeric grade."""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.grading.models import NumericGradeResult, SurpriseLessonsOutput
from app.grading.prompts import SURPRISE_LESSONS_PROMPT_VERSION, load_prompt
from app.prediction.bedrock_client import (
    BedrockClient,
    BedrockInvocationError,
    extract_json_object,
)

logger = get_logger(__name__)

_SYSTEM = load_prompt("surprise_lessons_v1.txt")


class SurpriseLessonsResult:
    __slots__ = ("surprise_notes", "lessons_learned", "prose_status", "prose_error")

    def __init__(
        self,
        *,
        surprise_notes: str | None,
        lessons_learned: str,
        prose_status: str,
        prose_error: str | None = None,
    ) -> None:
        self.surprise_notes = surprise_notes
        self.lessons_learned = lessons_learned
        self.prose_status = prose_status
        self.prose_error = prose_error


def _fallback_lessons(numeric: NumericGradeResult) -> str:
    if numeric.timed_out:
        return (
            f"At scale tier {numeric.scale_tier}, this migration shape blew the "
            "execution time budget; duration was unverifiable and should be "
            "treated as high blast-radius for backfill duration."
        )
    if not numeric.any_miss:
        return (
            f"Prediction was within configured error bands at tier "
            f"{numeric.scale_tier} (scalar={numeric.scalar_accuracy_score})."
        )
    misses = []
    if numeric.duration_within_band is False:
        misses.append("duration")
    if not numeric.storage_within_band:
        misses.append("storage")
    if not numeric.rollback_within_band:
        misses.append("rollback")
    return (
        f"Missed band(s) on {', '.join(misses) or 'unknown'} at tier "
        f"{numeric.scale_tier}; review prediction assumptions for similar shapes."
    )


def generate_surprise_and_lessons(
    client: BedrockClient | None,
    *,
    model_id: str,
    numeric: NumericGradeResult,
    migration_sql: str,
    risk_explanation: str,
) -> SurpriseLessonsResult:
    """Generate prose with one repair retry. On failure, use deterministic fallback."""
    if not numeric.any_miss and not numeric.timed_out:
        # Still call model for lessons when client provided; otherwise skip.
        pass

    if client is None:
        lessons = _fallback_lessons(numeric)
        notes = None
        if numeric.any_miss or numeric.timed_out:
            notes = lessons
        return SurpriseLessonsResult(
            surprise_notes=notes,
            lessons_learned=lessons,
            prose_status="skipped",
        )

    user_payload: dict[str, Any] = {
        "any_miss": numeric.any_miss,
        "timed_out": numeric.timed_out,
        "scale_tier": numeric.scale_tier,
        "scalar_accuracy_score": numeric.scalar_accuracy_score,
        "dimension_details": numeric.dimension_details,
        "outcome_class": numeric.outcome_class,
        "migration_sql_excerpt": migration_sql[:1500],
        "risk_explanation": risk_explanation[:1500],
    }
    user_prompt = json.dumps(user_payload, indent=2)

    last_error: str | None = None
    for attempt in range(2):
        try:
            raw = client.generate_json(
                system_prompt=_SYSTEM,
                user_prompt=user_prompt
                if attempt == 0
                else (
                    user_prompt
                    + "\n\nPrevious output failed validation. Return ONLY valid JSON "
                    "matching the schema."
                ),
                model_id=model_id,
            )
            parsed = extract_json_object(raw)
            validated = SurpriseLessonsOutput.model_validate(parsed)
            notes = validated.surprise_notes
            if (numeric.any_miss or numeric.timed_out) and not (notes or "").strip():
                raise ValueError("surprise_notes required when any dimension missed")
            if not numeric.any_miss and not numeric.timed_out:
                notes = None
            return SurpriseLessonsResult(
                surprise_notes=notes,
                lessons_learned=validated.lessons_learned.strip(),
                prose_status="ok",
            )
        except Exception as exc:  # noqa: BLE001 - prose must never block grade
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "Surprise/lessons prose generation failed",
                extra={"attempt": attempt + 1, "error": last_error},
            )

    lessons = _fallback_lessons(numeric)
    notes = lessons if (numeric.any_miss or numeric.timed_out) else None
    return SurpriseLessonsResult(
        surprise_notes=notes,
        lessons_learned=lessons,
        prose_status="failed",
        prose_error=(last_error or "unknown")[:2000],
    )


# Silence unused import lint when BedrockInvocationError is referenced in docs.
_ = BedrockInvocationError
