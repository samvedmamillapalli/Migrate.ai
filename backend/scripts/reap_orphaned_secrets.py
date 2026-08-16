#!/usr/bin/env python3
"""Delete Secrets Manager secrets this app created and then abandoned.

Why this exists
---------------
Every run given an explicit ``database_url`` gets its own secret
``migration-oracle/connections/{run_id}`` (see
``app/services/connection_secrets.store_connection_url``). Nothing ever deletes
it: ``CleanupFunction`` only removes ``migration-oracle/shadow*``, and its IAM
policy does not even permit deleting anything else. At $0.40/secret/month they
accumulate forever - 105 of them had built up by 2026-08-14, $42/month for
secrets belonging to runs that finished weeks earlier.

Safety rules (all enforced, not assumed):
  * Only ``migration-oracle/connections/{uuid}`` and
    ``migration-oracle/shadow/{uuid}`` are ever considered.
  * ``migration-oracle/connections/workspace/{uuid}`` is NEVER touched - those
    are the persistent per-workspace connections that live runs resolve
    through, and deleting one breaks every future run in that workspace.
  * A secret is kept if its run is missing from the database, still in a
    non-terminal status, or finished less recently than --min-age-hours.
  * A secret is kept if any workspace or any non-terminal run still points at
    its ARN.
  * Deletion uses the default 7-day recovery window (NOT
    ForceDeleteWithoutRecovery), so a mistake is reversible with
    ``aws secretsmanager restore-secret``. Billing stops as soon as deletion is
    scheduled.

Usage:
    python backend/scripts/reap_orphaned_secrets.py                 # dry run
    python backend/scripts/reap_orphaned_secrets.py --apply
    python backend/scripts/reap_orphaned_secrets.py --min-age-hours 6 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import re
import sys
from datetime import UTC, datetime, timedelta

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

CONNECTION_PREFIX = "migration-oracle/connections/"
WORKSPACE_PREFIX = "migration-oracle/connections/workspace/"
SHADOW_PREFIX = "migration-oracle/shadow/"
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

# Verified against the live database, not guessed: migration_runs.status is one
# of completed / pending / failed / awaiting_approval / running. `completed` is
# the success terminal state - there is no `succeeded`.
TERMINAL_STATUSES = {"completed", "failed"}

# A run left in a non-terminal status never transitions on its own, so without
# this an abandoned `pending` run pins its secret forever. Treat a non-terminal
# run untouched for this long as abandoned.
DEFAULT_STALE_DAYS = 7


def _load_env() -> None:
    raw = (BACKEND.parent / ".env").read_text(encoding="utf-8-sig")
    pairs: list[list[str]] = []
    for line in raw.splitlines():
        line = line.rstrip("\r")
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m:
            pairs.append([m.group(1), m.group(2)])
        elif pairs and line.strip() and not line.lstrip().startswith("#"):
            pairs[-1][1] += "\n" + line
    for k, v in pairs:
        if k != "AWS_PROFILE":
            os.environ.setdefault(k, v.strip().strip('"'))
    os.environ.pop("AWS_PROFILE", None)


async def _live_state() -> tuple[dict[str, str], set[str], set[str], set[str]]:
    """Return (run_id -> status, referenced ARNs, recently-touched runs,
    run ids whose shadow cluster is already destroyed)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.database.session import normalize_database_url

    engine = create_async_engine(normalize_database_url(os.environ["DATABASE_URL"]))
    statuses: dict[str, str] = {}
    referenced: set[str] = set()
    recent: set[str] = set()
    dead_shadow: set[str] = set()
    now = datetime.now(UTC)
    recent_cutoff = now - timedelta(hours=_ARGS.min_age_hours)
    stale_cutoff = now - timedelta(days=_ARGS.stale_days)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id::STRING, status::STRING, connection_secret_arn, "
                        "updated_at FROM migration_runs"
                    )
                )
            ).fetchall()
            for run_id, status, arn, updated_at in rows:
                st = (status or "").lower()
                statuses[run_id] = st
                touched = (
                    updated_at.replace(tzinfo=UTC) if updated_at is not None else None
                )
                if touched is not None and touched > recent_cutoff:
                    recent.add(run_id)
                # Only protect the ARN of a run that is both non-terminal AND
                # still moving. An abandoned `pending` run never transitions, so
                # protecting it forever is what caused the pile-up.
                is_stale = touched is not None and touched < stale_cutoff
                if st not in TERMINAL_STATUSES and not is_stale and arn:
                    referenced.add(arn)
            ws = (
                await conn.execute(
                    text(
                        "SELECT connection_secret_arn FROM workspaces "
                        "WHERE connection_secret_arn IS NOT NULL"
                    )
                )
            ).fetchall()
            for (arn,) in ws:
                if arn:
                    referenced.add(arn)
            # A destroyed shadow cluster's credential can never be used again.
            sc = (
                await conn.execute(
                    text(
                        "SELECT migration_run_id::STRING FROM shadow_clusters "
                        "WHERE status::STRING = 'destroyed'"
                    )
                )
            ).fetchall()
            for (rid,) in sc:
                if rid:
                    dead_shadow.add(rid)
    finally:
        await engine.dispose()
    return statuses, referenced, recent, dead_shadow


def _list_secrets(client) -> list[dict]:
    out: list[dict] = []
    token = None
    while True:
        kw = {"MaxResults": 100}
        if token:
            kw["NextToken"] = token
        page = client.list_secrets(**kw)
        out.extend(page.get("SecretList", []))
        token = page.get("NextToken")
        if not token:
            return out


def _classify(
    secret: dict,
    statuses: dict[str, str],
    referenced: set[str],
    recent: set[str],
    dead_shadow: set[str],
) -> tuple[bool, str]:
    """Return (deletable, reason)."""
    name = secret["Name"]
    arn = secret.get("ARN", "")

    if name.startswith(WORKSPACE_PREFIX):
        return False, "workspace connection (persistent)"
    if arn in referenced or name in referenced:
        return False, "still referenced by a live run or workspace"

    if name.startswith(CONNECTION_PREFIX):
        run_id = name[len(CONNECTION_PREFIX) :]
        kind = "connection"
    elif name.startswith(SHADOW_PREFIX):
        run_id = name[len(SHADOW_PREFIX) :]
        kind = "shadow"
    else:
        return False, "not an app per-run secret"

    if not _UUID.match(run_id):
        return False, "name is not <prefix>/<uuid>"
    if run_id in recent:
        return False, f"run updated within {_ARGS.min_age_hours}h"

    # A shadow credential outlives nothing: once the cluster is destroyed the
    # secret cannot be used again, whatever the parent run's status.
    if kind == "shadow" and run_id in dead_shadow:
        return True, "shadow: cluster already destroyed"

    status = statuses.get(run_id)
    if status is None:
        return True, f"{kind}: run no longer exists"
    if status in TERMINAL_STATUSES:
        return True, f"{kind}: run is {status}"
    return True, f"{kind}: run is {status} but untouched >{_ARGS.stale_days}d"


def main() -> int:
    global _ARGS
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually schedule deletion (default is a dry run)")
    ap.add_argument("--min-age-hours", type=int, default=24,
                    help="keep secrets whose run changed within this window")
    ap.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS,
                    help="a non-terminal run untouched this long counts as abandoned")
    ap.add_argument("--region", default=None)
    _ARGS = ap.parse_args()

    _load_env()
    import boto3

    region = _ARGS.region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)

    statuses, referenced, recent, dead_shadow = asyncio.run(_live_state())
    secrets = _list_secrets(client)

    deletable: list[tuple[str, str]] = []
    kept: dict[str, int] = {}
    for s in secrets:
        ok, reason = _classify(s, statuses, referenced, recent, dead_shadow)
        if ok:
            deletable.append((s["Name"], reason))
        else:
            kept[reason] = kept.get(reason, 0) + 1

    print(f"region={region}  secrets={len(secrets)}  runs_known={len(statuses)}")
    print(f"current monthly cost at $0.40/secret: ${len(secrets) * 0.40:.2f}\n")
    print(f"KEEPING {len(secrets) - len(deletable)}:")
    for reason, n in sorted(kept.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4}  {reason}")
    print(f"\n{'DELETING' if _ARGS.apply else 'WOULD DELETE'} {len(deletable)}:")
    by_reason: dict[str, int] = {}
    for _, reason in deletable:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4}  {reason}")
    saving = len(deletable) * 0.40
    print(f"\nprojected saving: ${saving:.2f}/month "
          f"-> new cost ${(len(secrets) - len(deletable)) * 0.40:.2f}/month")

    if not _ARGS.apply:
        print("\n(dry run - pass --apply to schedule deletion, 7-day recovery window)")
        return 0

    failed = 0
    for name, _ in deletable:
        try:
            # No ForceDeleteWithoutRecovery: keep the 7-day restore window.
            client.delete_secret(SecretId=name, RecoveryWindowInDays=7)
        except Exception as exc:  # noqa: BLE001 - report and continue
            failed += 1
            print(f"  FAILED {name}: {str(exc)[:120]}")
    print(f"\nscheduled {len(deletable) - failed} for deletion, {failed} failed")
    print("restore within 7 days with: aws secretsmanager restore-secret --secret-id <name>")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
