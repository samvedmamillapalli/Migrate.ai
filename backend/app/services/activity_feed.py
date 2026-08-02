"""Cross-run activity feed.

The Overview page shows a merged, reverse-chronological stream of what the
system actually did: runs created, predictions produced, decisions recorded,
shadow executions started and finished, grades written, memories learned.

Every row here is derived from a real persisted timestamp — there is no
synthesized or interpolated event. When a stage never happened for a run, it
simply contributes no row.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.constants import CORPUS_OWNER_IDENTITY

# Tone names match the frontend's semantic palette:
#   emerald = succeeded, blue = shadow activity, violet = model activity,
#   amber = awaiting a human, red = failed/cancelled.
_FEED_SQL = """
WITH scoped AS (
    SELECT
        mr.id,
        mr.migration_sql,
        mr.created_at,
        mr.updated_at,
        mr.status,
        mr.compatibility_risk,
        mr.workflow_started_at,
        mr.workflow_finished_at,
        mr.workflow_status,
        mr.explainability
    FROM migration_runs mr
    WHERE mr.owner_identity != :corpus_owner
      AND mr.run_kind NOT IN ('chaos', 'debug')
      AND (CAST(:owner_identity AS STRING) IS NULL
           OR mr.owner_identity = CAST(:owner_identity AS STRING))
)
SELECT * FROM (
    -- Run created
    SELECT
        s.id            AS migration_run_id,
        s.created_at    AS at,
        'Queued'        AS kind,
        'amber'         AS tone,
        'Migration submitted for review.' AS text,
        s.migration_sql AS migration_sql
    FROM scoped s

    UNION ALL

    -- Prediction produced (a run only carries explainability once predicted)
    SELECT
        s.id,
        COALESCE(p.created_at, s.updated_at),
        'Predicted',
        'violet',
        'Risk model classified the migration as '
            || COALESCE(CAST(s.compatibility_risk AS STRING), 'unclassified')
            || '-impact.',
        s.migration_sql
    FROM scoped s
    LEFT JOIN predictions p ON p.migration_run_id = s.id
    WHERE s.explainability IS NOT NULL

    UNION ALL

    -- Memory retrieval contributed to the prediction
    SELECT
        s.id,
        COALESCE(p.created_at, s.updated_at),
        'Learned',
        'blue',
        'Agent Memory contributed '
            || (s.explainability->'memory'->>'retrieved_count')
            || ' matching verified runs to this prediction.',
        s.migration_sql
    FROM scoped s
    LEFT JOIN predictions p ON p.migration_run_id = s.id
    WHERE COALESCE((s.explainability->'memory'->>'retrieved_count')::INT, 0) > 0

    UNION ALL

    -- Human decision recorded
    SELECT
        s.id,
        a.created_at,
        CASE a.decision
            WHEN 'proceed' THEN 'Approved'
            WHEN 'accept_recommended' THEN 'Accepted Plan'
            ELSE 'Cancelled'
        END,
        CASE a.decision WHEN 'cancel' THEN 'red' ELSE 'emerald' END,
        CASE a.decision
            WHEN 'proceed' THEN 'Approved for shadow execution by '
                || a.approver_identity || '.'
            WHEN 'accept_recommended' THEN 'Plan accepted without a shadow run by '
                || a.approver_identity || '.'
            ELSE 'Run cancelled by ' || a.approver_identity || '.'
        END,
        s.migration_sql
    FROM scoped s
    JOIN approvals a ON a.migration_run_id = s.id

    UNION ALL

    -- Shadow execution started
    SELECT
        s.id,
        COALESCE(s.workflow_started_at, sc.created_at),
        'Shadow',
        'blue',
        'Shadow run started on ' || COALESCE(sc.provider, 'shadow cluster')
            || COALESCE(' (' || sc.region || ')', '') || '.',
        s.migration_sql
    FROM scoped s
    JOIN shadow_clusters sc ON sc.migration_run_id = s.id
    WHERE COALESCE(s.workflow_started_at, sc.created_at) IS NOT NULL

    UNION ALL

    -- Shadow execution measured
    SELECT
        s.id,
        COALESCE(s.workflow_finished_at, er.created_at),
        CASE WHEN er.success THEN 'Completed' ELSE 'Failed' END,
        CASE WHEN er.success THEN 'emerald' ELSE 'red' END,
        CASE WHEN er.success
            THEN 'Shadow execution finished in '
                 || CAST(ROUND(er.actual_duration_seconds::NUMERIC, 1) AS STRING)
                 || 's with no rollback required.'
            ELSE 'Shadow execution failed: '
                 || COALESCE(er.error_message, 'no error message recorded')
        END,
        s.migration_sql
    FROM scoped s
    JOIN execution_results er ON er.migration_run_id = s.id

    UNION ALL

    -- Prediction graded against the measurement
    SELECT
        s.id,
        g.created_at,
        'Graded',
        'violet',
        'Prediction graded '
            || CAST(ROUND(g.scalar_accuracy_score::NUMERIC, 3) AS STRING)
            || ' (' || g.outcome_class || ').',
        s.migration_sql
    FROM scoped s
    JOIN grades g ON g.migration_run_id = s.id

    UNION ALL

    -- Outcome written back into the corpus
    SELECT
        s.id,
        mm.created_at,
        'Remembered',
        'blue',
        'Outcome stored in Agent Memory for future predictions.',
        s.migration_sql
    FROM scoped s
    JOIN migration_memories mm ON mm.migration_run_id = s.id
) events
WHERE events.at IS NOT NULL
ORDER BY events.at DESC
LIMIT :limit
"""


_VOLUME_SQL = """
SELECT
    DATE(mr.created_at) AS day,
    COUNT(*) FILTER (
        WHERE mr.status = 'completed'
          AND COALESCE(er.success, TRUE)
    ) AS ok,
    COUNT(*) FILTER (
        WHERE mr.status = 'failed'
           OR er.success = FALSE
           OR er.timed_out = TRUE
    ) AS bad,
    COUNT(*) AS total
FROM migration_runs mr
LEFT JOIN execution_results er ON er.migration_run_id = mr.id
WHERE mr.owner_identity != :corpus_owner
  AND mr.run_kind NOT IN ('chaos', 'debug')
  AND mr.created_at >= (CURRENT_DATE - CAST(:days AS INT) + 1)
  AND (CAST(:owner_identity AS STRING) IS NULL
       OR mr.owner_identity = CAST(:owner_identity AS STRING))
GROUP BY 1
ORDER BY 1
"""


async def fetch_run_volume(
    session: AsyncSession,
    *,
    owner_identity: str | None = None,
    days: int = 7,
) -> dict[str, Any]:
    """Daily succeeded / failed run counts across the whole history."""
    from datetime import date, timedelta

    window = max(1, min(int(days), 90))
    rows = (
        await session.execute(
            text(_VOLUME_SQL),
            {
                "owner_identity": owner_identity,
                "corpus_owner": CORPUS_OWNER_IDENTITY,
                "days": window,
            },
        )
    ).mappings().all()

    by_day = {str(row["day"]): row for row in rows}
    today = date.today()
    series = []
    for i in range(window - 1, -1, -1):
        d = today - timedelta(days=i)
        key = d.isoformat()
        row = by_day.get(key)
        series.append(
            {
                "day": key,
                "ok": int(row["ok"]) if row else 0,
                "bad": int(row["bad"]) if row else 0,
                "total": int(row["total"]) if row else 0,
            }
        )
    return {"days": series, "window_days": window}


def _snippet(sql: str | None) -> str:
    one = " ".join((sql or "").split())
    return one if len(one) <= 96 else f"{one[:93]}..."


async def fetch_activity_feed(
    session: AsyncSession,
    *,
    owner_identity: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(_FEED_SQL),
            {
                "owner_identity": owner_identity,
                "corpus_owner": CORPUS_OWNER_IDENTITY,
                "limit": max(1, min(int(limit), 200)),
            },
        )
    ).mappings().all()

    return {
        "items": [
            {
                "migration_run_id": str(row["migration_run_id"]),
                "at": row["at"].isoformat() if row["at"] is not None else None,
                "kind": row["kind"],
                "tone": row["tone"],
                "text": row["text"],
                "sql_snippet": _snippet(row["migration_sql"]),
            }
            for row in rows
        ],
        "total": len(rows),
    }


__all__ = ["fetch_activity_feed", "fetch_run_volume"]
