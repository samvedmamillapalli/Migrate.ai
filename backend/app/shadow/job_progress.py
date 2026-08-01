"""Live CockroachDB background-job progress for the shadow "execute" stage.

CockroachDB runs schema-change DDL as a background job, but the initiating
SQL statement blocks until that job finishes — so watching it live needs two
things happening concurrently on two separate connections:

1. A notice handler on the connection running the DDL, which captures the
   job id the instant CockroachDB announces it (before the statement itself
   returns).
2. A second connection that, once it has that id, polls the single job by id
   — never bare ``SHOW JOBS``, which has been reported to take 30s+ to return
   while a schema-change job is active on the same cluster.

Best-effort throughout: if the notice never arrives (driver/server behavior
we haven't spiked against a live cluster yet — see docs/ai_audit.md Phase
C-0), this degrades to zero observations and the caller falls back to the
existing post-hoc ``job_watch.snapshot_schema_jobs``. Never fabricates a
progress value that wasn't actually reported by the database.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg

from app.core.logging import get_logger

logger = get_logger(__name__)

_JOB_ID_PATTERN = re.compile(r"\bjob\s+(\d+)\b", re.IGNORECASE)
_TERMINAL_JOB_STATUSES = frozenset(
    {"succeeded", "failed", "canceled", "revert-failed"}
)
_POLL_INTERVAL_SECONDS = 1.0
_MAX_POLLS = 180  # 3 minutes of targeted polling, well past any shadow-tier DDL


@dataclass
class JobProgressResult:
    """Everything observed about the background job(s) behind one migration."""

    job_ids: list[str] = field(default_factory=list)
    # Ordered observations: {job_id, status, running_status, fraction_completed,
    # description, error, observed_at}. Empty if no notice was ever captured.
    observations: list[dict[str, Any]] = field(default_factory=list)
    # Statement execution outcome. Kept on the result (not raised) so the
    # caller gets whatever job observations were collected even on failure.
    succeeded: bool = True
    error: BaseException | None = None


def _to_psycopg_dsn(normalized_sqlalchemy_url: str) -> str:
    """`cockroachdb+psycopg://...` / `postgresql+psycopg://...` -> `postgresql://...`.

    psycopg connects natively over the Postgres wire protocol; only the
    SQLAlchemy dialect prefix needs stripping, netloc/path/query are unchanged.
    """
    _, _, rest = normalized_sqlalchemy_url.partition("://")
    return f"postgresql://{rest}"


async def _poll_job(
    dsn: str,
    job_id: str,
    observations: list[dict[str, Any]],
) -> None:
    try:
        async with await psycopg.AsyncConnection.connect(
            dsn, autocommit=True
        ) as poll_conn:
            for _ in range(_MAX_POLLS):
                try:
                    async with poll_conn.cursor() as cur:
                        await cur.execute(
                            f"SELECT job_id::string, status, running_status, "
                            f"COALESCE(fraction_completed, 0)::float8, "
                            f"description, error FROM [SHOW JOB {int(job_id)}]"
                        )
                        row = await cur.fetchone()
                except Exception as exc:  # noqa: BLE001 - best-effort watch
                    logger.warning(
                        "Targeted SHOW JOB poll failed",
                        extra={"job_id": job_id, "error": str(exc)},
                    )
                    return
                if row is None:
                    return
                status = str(row[1] or "")
                observations.append(
                    {
                        "job_id": row[0],
                        "status": status,
                        "running_status": row[2],
                        "fraction_completed": row[3],
                        "description": row[4],
                        "error": row[5],
                        "observed_at": time.time(),
                    }
                )
                if status.lower() in _TERMINAL_JOB_STATUSES:
                    return
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - best-effort watch
        logger.warning(
            "Targeted SHOW JOB poll connection failed",
            extra={"job_id": job_id, "error": str(exc)},
        )


async def run_with_job_progress(
    normalized_connection_url: str,
    statements: list[str],
    *,
    statement_timeout_ms: int = 600_000,
) -> JobProgressResult:
    """Run ``statements`` in one transaction, capturing live job progress.

    Never raises — statement failure is reported via ``result.succeeded`` /
    ``result.error`` instead, so the caller still gets whatever job
    observations were collected up to the point of failure rather than
    losing them to an exception.
    """
    dsn = _to_psycopg_dsn(normalized_connection_url)
    result = JobProgressResult()
    poll_task: asyncio.Task[None] | None = None

    def _on_notice(diag: psycopg.errors.Diagnostic) -> None:
        nonlocal poll_task
        message = " ".join(
            part
            for part in (
                getattr(diag, "message_primary", None),
                getattr(diag, "message_detail", None),
                getattr(diag, "message_hint", None),
            )
            if part
        )
        match = _JOB_ID_PATTERN.search(message)
        if not match:
            return
        job_id = match.group(1)
        if job_id not in result.job_ids:
            result.job_ids.append(job_id)
        if poll_task is None:
            poll_task = asyncio.ensure_future(
                _poll_job(dsn, job_id, result.observations)
            )

    conn = await psycopg.AsyncConnection.connect(dsn)
    try:
        conn.add_notice_handler(_on_notice)
        async with conn.cursor() as cur:
            await cur.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
            for statement in statements:
                await cur.execute(statement)
        await conn.commit()
    except Exception as exc:  # noqa: BLE001 - reported on the result, not raised
        await conn.rollback()
        result.succeeded = False
        result.error = exc
    finally:
        await conn.close()
        if poll_task is not None and not poll_task.done():
            try:
                await asyncio.wait_for(poll_task, timeout=5.0)
            except (TimeoutError, asyncio.TimeoutError):
                poll_task.cancel()

    return result
