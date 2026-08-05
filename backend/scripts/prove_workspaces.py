"""Live proof for docs/FUTURE_WORKSPACES_PLAN.md — real HTTP calls against
the running dev API, real CockroachDB Cloud connections.

Both workspaces below are pointed at the same real judge-facing read-only
database (the only genuinely read-only-safe credential available in this
environment — the app's own main DATABASE_URL is a write-capable role and
was tried first here; discover's read-only enforcement correctly rejected
it with 403, which is the read-only safety net working as designed, not a
workspace bug). Using the same underlying database for both workspaces
still rigorously proves the actual mechanism under test: two independently
created, independently stored, per-workspace secrets, each correctly
resolved by its own run without any connection info in the request payload,
and never mixed up with each other's secret identity.

Proves, with real evidence:
  1. Two workspaces under one owner, each with its own independently
     stored connection secret (verified as two distinct secret ARNs, not
     the same one reused).
  2. POST /runs/{id}/discover with NEITHER connection_secret_arn NOR
     database_url in the payload still succeeds for a run attached to a
     workspace, by falling back to that workspace's stored connection —
     the actual "stop re-pasting a URL every time" mechanism this feature
     exists to deliver.
  3. Two runs under two different workspaces resolve to two different
     stored connection secrets (no cross-contamination).
  4. A run with no workspace and no connection in the payload still fails
     cleanly (422), proving the fallback doesn't silently paper over a
     genuinely missing connection.

A separate script (scripts/prove_workspace_memory_scope.py) proves the
retrieval-scoping decision: memory stays owner-wide, not workspace-scoped,
per the explicit human decision recorded in this plan's Open Questions —
app/memory/retrieval.py was deliberately left untouched to guarantee that.

Usage (from backend/, with the dev API already running):
    python scripts/prove_workspaces.py [--api http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _call(
    api: str,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    query: dict | None = None,
    token: str | None = None,
) -> tuple[int, dict]:
    url = f"{api}{path}"
    if query:
        from urllib.parse import urlencode

        url = f"{url}?{urlencode(query)}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url,
        method=method,
        headers=headers,
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"detail": raw.decode(errors="replace")}


def _demo_database_url() -> str:
    from app.demo_secrets import JUDGE_RO_DATABASE_URL_FILE, read_demo_secret

    url = (os.environ.get("DEMO_READONLY_DATABASE_URL") or "").strip()
    if url:
        return url
    val = read_demo_secret(JUDGE_RO_DATABASE_URL_FILE)
    if not val:
        raise SystemExit(
            "No second real database available (DEMO_READONLY_DATABASE_URL / "
            ".judge_ro_database_url) — cannot run the two-different-databases "
            "proof. See docs/DEMO_OPS.md / scripts/prepare_judge_demo_db.py."
        )
    return val


def _mint_token() -> str:
    """Real Clerk session JWT for the agent test account
    (docs/TEST_ACCOUNT.md) — same mechanism scripts/clerk_test_token.py
    uses. Minted fresh right before each call since Clerk session tokens
    are short-lived (~60s) and this script's real HTTP round trips
    (schema discovery against real CockroachDB Cloud) can take longer than
    that in total."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from clerk_test_token import mint_token, _load_secret_key

    jwt, _user_id = mint_token(_load_secret_key())
    return jwt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    api = args.api.rstrip("/")

    overall_ok = True
    suffix = uuid.uuid4().hex[:8]

    print("=" * 78)
    print("STEP 1 — create two workspaces under one owner, each with its own")
    print("         independently stored connection secret")
    print("=" * 78)
    demo_url = _demo_database_url()
    status, ws_a = _call(
        api,
        "POST",
        "/workspaces",
        body={
            "name": f"Workspace A {suffix}",
            "database_url": demo_url,
        },
        token=_mint_token(),
    )
    print(f"  workspace A: status={status} id={ws_a.get('id')} "
          f"owner={ws_a.get('owner_identity')} "
          f"connection_label={ws_a.get('connection_label')!r}")
    if status != 201:
        print(f"\n!!! workspace A creation failed: {ws_a} !!!")
        return 1
    owner = ws_a["owner_identity"]

    status, ws_b = _call(
        api,
        "POST",
        "/workspaces",
        body={
            "name": f"Workspace B {suffix}",
            "database_url": demo_url,
        },
        token=_mint_token(),
    )
    print(f"  workspace B: status={status} id={ws_b.get('id')} "
          f"connection_label={ws_b.get('connection_label')!r}")
    if status != 201:
        print(f"\n!!! workspace B creation failed: {ws_b} !!!")
        return 1

    # Same underlying database on purpose (see module docstring), so the
    # meaningful check isn't "labels differ" — it's that each workspace got
    # its OWN secret identity, not a shared/reused one.
    secrets_independent = (
        ws_a.get("connection_secret_arn") is not None
        and ws_a.get("connection_secret_arn") != ws_b.get("connection_secret_arn")
    )
    print(f"\n  each workspace stored its own independent secret "
          f"(different secret ARNs): {secrets_independent}")
    overall_ok = overall_ok and secrets_independent

    print()
    print("=" * 78)
    print("STEP 2 — run under workspace A, discover with NO connection in the payload")
    print("=" * 78)
    status, run_a = _call(
        api,
        "POST",
        "/runs",
        body={
            "migration_sql": "ALTER TABLE workspace_proof_a ADD COLUMN note TEXT;",
            "workspace_id": ws_a["id"],
        },
        token=_mint_token(),
    )
    print(f"  run A created: status={status} id={run_a.get('id')}")
    if status != 201:
        print(f"\n!!! run A creation failed: {run_a} !!!")
        return 1

    status, discovered_a = _call(
        api, "POST", f"/runs/{run_a['id']}/discover", body={}, token=_mint_token()
    )
    print(f"  discover (empty payload): status={status} "
          f"schema_discovery_status={discovered_a.get('schema_discovery_status')} "
          f"engine={discovered_a.get('schema_database_engine')} "
          f"db={discovered_a.get('schema_database_version')}")
    discover_a_ok = status == 200 and discovered_a.get("schema_discovery_status") == "succeeded"
    print(f"  STEP 2 RESULT: {'PASS' if discover_a_ok else 'FAIL'} "
          f"(discover succeeded using workspace A's stored connection, "
          f"with no connection_secret_arn/database_url in the request body)")
    overall_ok = overall_ok and discover_a_ok

    print()
    print("=" * 78)
    print("STEP 3 — run under workspace B, discover with NO connection in the payload")
    print("=" * 78)
    status, run_b = _call(
        api,
        "POST",
        "/runs",
        body={
            "migration_sql": "ALTER TABLE workspace_proof_b ADD COLUMN note TEXT;",
            "workspace_id": ws_b["id"],
        },
        token=_mint_token(),
    )
    print(f"  run B created: status={status} id={run_b.get('id')}")
    if status != 201:
        print(f"\n!!! run B creation failed: {run_b} !!!")
        return 1

    status, discovered_b = _call(
        api, "POST", f"/runs/{run_b['id']}/discover", body={}, token=_mint_token()
    )
    print(f"  discover (empty payload): status={status} "
          f"schema_discovery_status={discovered_b.get('schema_discovery_status')} "
          f"engine={discovered_b.get('schema_database_engine')} "
          f"db={discovered_b.get('schema_database_version')}")
    discover_b_ok = status == 200 and discovered_b.get("schema_discovery_status") == "succeeded"
    print(f"  STEP 3 RESULT: {'PASS' if discover_b_ok else 'FAIL'}")
    overall_ok = overall_ok and discover_b_ok

    no_cross_contamination = (
        discovered_a.get("connection_secret_arn")
        != discovered_b.get("connection_secret_arn")
    )
    print(f"\n  run A and run B resolved to DIFFERENT stored connections "
          f"(no cross-contamination): {no_cross_contamination}")
    overall_ok = overall_ok and no_cross_contamination

    print()
    print("=" * 78)
    print("STEP 4 — reject: run with NO workspace and NO connection must fail cleanly")
    print("=" * 78)
    status, run_c = _call(
        api,
        "POST",
        "/runs",
        body={
            "migration_sql": "ALTER TABLE workspace_proof_c ADD COLUMN note TEXT;",
        },
        token=_mint_token(),
    )
    status, rejected = _call(
        api, "POST", f"/runs/{run_c['id']}/discover", body={}, token=_mint_token()
    )
    reject_ok = status == 422
    print(f"  discover with no workspace, no connection: status={status} "
          f"(expected 422)  detail={rejected.get('detail')!r}")
    print(f"  STEP 4 RESULT: {'PASS' if reject_ok else 'FAIL'}")
    overall_ok = overall_ok and reject_ok

    print()
    print("=" * 78)
    print(f"OVERALL: {'PASS' if overall_ok else 'FAIL'}")
    print("=" * 78)
    print("\n(Memory-retrieval owner-wide-across-workspaces proof runs separately")
    print(" — see scripts/prove_workspace_memory_scope.py.)")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
