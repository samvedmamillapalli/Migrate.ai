"""CockroachDB Changefeed-backed live event stream for the shadow "execute"
stage — augments, does not replace, the SHOW JOBS polling in
app.shadow.job_progress.

Why augment rather than replace: CHANGEFEEDs cannot be created on system
tables — verified live against this project's own cluster:
``CREATE CHANGEFEED FOR TABLE system.jobs INTO 'null://'`` is rejected with
"CHANGEFEEDs are not supported on system tables". So this watches the actual
table(s) the migration targets instead of the job record. A backfill-heavy
migration (``ADD COLUMN ... DEFAULT``, ``ALTER COLUMN ... TYPE``) rewrites
every existing row, so the changefeed reports real row-level progress as it
happens. ``CREATE INDEX`` writes to a separate index span and may produce
zero events on the base table — SHOW JOBS stays the one signal that works for
every migration type, which is why this is additive, not a replacement.

Sink is CockroachDB Cloud's own Enterprise changefeed S3 support (confirmed
licensed and working on this Basic-plan cluster — not the deprecated
core/experimental changefeed), writing into this app's existing artifacts
bucket under a per-run prefix. The CockroachDB cluster is not inside this AWS
account and can't assume the Lambda's execution role, so it authenticates
with a narrowly-scoped IAM credential (s3:PutObject only, one prefix — see
ChangefeedS3WriterUser in infra/sam/template.yaml) passed as a query
parameter on the sink URI, always as a bound SQL parameter, never
string-formatted into the statement text.

Best-effort throughout, like everything else that enriches a shadow run in
this app: never raises, never blocks or fails the migration it's watching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.logging import get_logger

if TYPE_CHECKING:
    from botocore.client import BaseClient
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = get_logger(__name__)

# Checkpoint frequently so CANCEL JOB (fired shortly after the migration
# completes, since the shadow cluster is about to be torn down) doesn't lose
# events that were still buffered.
_RESOLVED_INTERVAL = "1s"


def build_sink_uri(
    *,
    bucket: str,
    run_id: str,
    access_key_id: str,
    secret_access_key: str,
) -> str:
    """S3 sink URI with credentials as query params — CockroachDB Cloud isn't
    in this AWS account, so it can't use an assumed role."""
    return (
        f"s3://{bucket}/changefeed/{run_id}/"
        f"?AWS_ACCESS_KEY_ID={quote(access_key_id, safe='')}"
        f"&AWS_SECRET_ACCESS_KEY={quote(secret_access_key, safe='')}"
    )


async def create_changefeed(
    conn: AsyncConnection,
    *,
    tables: list[str],
    sink_uri: str,
) -> str | None:
    """Best-effort: returns the changefeed's job id, or None on any failure
    (unsupported table shape, no primary key, licensing, network). Never
    raises — a missing changefeed is a missing enrichment, not a failed
    migration.

    ``sink_uri`` is always passed as a bound parameter (never interpolated
    into the SQL text) — confirmed live that CockroachDB accepts a bound
    param for the INTO target, which keeps the embedded S3 secret out of any
    query-text logging.
    """
    if not tables:
        return None
    table_list = ", ".join(tables)
    try:
        result = await conn.execute(
            text(
                f"CREATE CHANGEFEED FOR TABLE {table_list} "
                f"INTO :sink_uri WITH resolved = '{_RESOLVED_INTERVAL}', updated"
            ),
            {"sink_uri": sink_uri},
        )
        row = result.first()
        job_id = str(row[0]) if row else None
        logger.info(
            "Changefeed created",
            extra={"job_id": job_id, "tables": tables},
        )
        return job_id
    except Exception as exc:  # noqa: BLE001 - best-effort enrichment
        logger.warning(
            "Changefeed creation failed",
            extra={"tables": tables, "error": f"{type(exc).__name__}: {exc}"},
        )
        return None


async def start_changefeed_safely(
    engine: "AsyncEngine",
    *,
    tables: list[str],
    sink_uri: str,
) -> str | None:
    """Engine-level wrapper that owns its own transaction and can never raise.

    This exists because ``create_changefeed`` alone is NOT enough to honor this
    module's "never fails the migration" contract: when the caller wraps it in
    ``async with engine.begin()``, the COMMIT happens on context-manager *exit*,
    outside ``create_changefeed``'s own try/except. A statement that fails and
    is swallowed still leaves the transaction aborted, so that COMMIT raises
    and escapes to the caller — which is exactly how a best-effort enrichment
    turned into a failed shadow run (run c1635bcc-d801-4288-9afe-5af932014d5e,
    2026-08-02). Owning the transaction here keeps the whole lifecycle —
    statement *and* commit — inside one guard.
    """
    try:
        async with engine.begin() as conn:
            return await create_changefeed(conn, tables=tables, sink_uri=sink_uri)
    except Exception as exc:  # noqa: BLE001 - best-effort enrichment
        logger.warning(
            "Changefeed start failed (non-fatal; migration continues)",
            extra={"tables": tables, "error": f"{type(exc).__name__}: {exc}"},
        )
        return None


async def stop_changefeed_safely(engine: "AsyncEngine", job_id: str) -> None:
    """Engine-level counterpart to ``start_changefeed_safely``; never raises."""
    try:
        async with engine.begin() as conn:
            await cancel_changefeed(conn, job_id)
    except Exception as exc:  # noqa: BLE001 - best-effort enrichment
        logger.warning(
            "Changefeed stop failed (non-fatal; migration already measured)",
            extra={"job_id": job_id, "error": f"{type(exc).__name__}: {exc}"},
        )


async def cancel_changefeed(conn: AsyncConnection, job_id: str) -> None:
    """Best-effort: never raises. Not a graceful drain — CANCEL JOB stops the
    feed abruptly, which is why the caller should leave a short gap after the
    migration completes for the resolved-interval checkpoint to flush first.
    """
    try:
        await conn.execute(text(f"CANCEL JOB {int(job_id)}"))
        logger.info("Changefeed cancelled", extra={"job_id": job_id})
    except Exception as exc:  # noqa: BLE001 - best-effort enrichment
        logger.warning(
            "Changefeed cancel failed",
            extra={"job_id": job_id, "error": f"{type(exc).__name__}: {exc}"},
        )


def parse_changefeed_events(ndjson_blobs: list[bytes]) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON changefeed event files into a flat,
    time-ordered list. Malformed lines are skipped, not fatal — an event
    stream with a few dropped lines is still useful; refusing to show any of
    it over one bad line is not the right tradeoff for enrichment data.
    """
    import json

    events: list[dict[str, Any]] = []
    for blob in ndjson_blobs:
        for line in blob.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    events.sort(key=lambda e: str(e.get("updated") or e.get("resolved") or ""))
    return events


# The UI ("Live Change Events") only ever renders the first 20 events
# (frontend/oracle/apps/web/app/dashboard/migrations/[id]/page.tsx). A
# backfill-heavy migration on a wide, multi-thousand-row table (real example:
# a computed STORED column on a 4,500-row / ~40-column table) makes the
# changefeed emit one full-row event per row — persisting all of them into
# `shadow_clusters.stage_timings`/`event_log` produced a >20 MiB JSONB
# payload on a single UPDATE, which CockroachDB rejects outright (default
# `sql.conn.max_read_buffer_message_size` is 16 MiB), failing the *entire*
# shadow run at the persist step even though the migration itself had
# already succeeded (run 20ee1287-bffd-4fdf-9e83-3d0bb3c44281, 2026-08-11).
# Capping here — not just at render time — is the actual fix: it keeps this
# enrichment's own failure mode from ever reaching the size limit, honoring
# this module's stated "never fails the migration it's watching" contract.
#
# 100, not 200: ShadowClusterService._append_event (shadow_cluster_service.py)
# embeds a full copy of stage_timings — including this list — into
# shadow_clusters.event_log on EVERY status transition (ready/seeding/
# migrating/holding/destroying, ~5-8 per run), so the effective multiplier
# is per-transition, not one-shot. Halving the cap roughly halves that
# compounded worst case, for a real, empty-handed cost (the UI still only
# ever shows 20).
_MAX_PERSISTED_EVENTS = 100


def read_changefeed_events(
    s3_client: "BaseClient",
    *,
    bucket: str,
    run_id: str,
    max_events: int = _MAX_PERSISTED_EVENTS,
) -> list[dict[str, Any]]:
    """Reads and parses NDJSON files the changefeed wrote for this run, capped
    to ``max_events`` (chronologically first — matching what the UI actually
    displays) so a large backfill can never balloon this into an oversized
    JSONB write. See ``_MAX_PERSISTED_EVENTS`` above for why the cap exists.

    Best-effort: returns whatever it can read; a missing prefix (changefeed
    was never created, or wrote nothing before cancellation) is an empty
    list, not an error — this is enrichment on top of an already-measured
    migration, same posture as the rest of this module.
    """
    prefix = f"changefeed/{run_id}/"
    blobs: list[bytes] = []
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents") or []:
                key = obj["Key"]
                # Nothing else writes under this run's own dedicated prefix,
                # so download everything found there rather than guessing at
                # CockroachDB's exact file-naming convention — parse_changefeed_
                # events() already skips lines that aren't valid JSON.
                body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
                blobs.append(body)
    except Exception as exc:  # noqa: BLE001 - best-effort enrichment
        logger.warning(
            "Reading changefeed events from S3 failed",
            extra={"run_id": run_id, "bucket": bucket, "error": f"{type(exc).__name__}: {exc}"},
        )
        return []

    events = parse_changefeed_events(blobs)
    total_event_count = len(events)
    if total_event_count > max_events:
        events = events[:max_events]

    logger.info(
        "Changefeed events read from S3",
        extra={
            "run_id": run_id,
            "file_count": len(blobs),
            "event_count": len(events),
            "total_event_count": total_event_count,
            "truncated": total_event_count > max_events,
        },
    )
    return events
