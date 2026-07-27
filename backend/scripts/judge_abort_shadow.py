#!/usr/bin/env python3
"""Start a real SFN shadow then abort — proves teardown path for demo day."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

API = os.environ.get("JUDGE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
OWNER = os.environ.get("JUDGE_OWNER", "judge-demo")
RO = (ROOT / ".judge_ro_database_url").read_text(encoding="utf-8").strip()
SQL = "CREATE INDEX IF NOT EXISTS idx_customers_region_abort ON public.customers (region);"


def api(method: str, path: str, body: dict | None = None, timeout: int = 300):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def main() -> None:
    health = api("GET", "/health")
    integ = health.get("integrations") or {}
    if not integ.get("sfn_ready"):
        raise SystemExit("sfn not ready")

    run = api(
        "POST",
        "/runs",
        {"migration_sql": SQL, "owner_identity": OWNER},
    )
    run_id = run["id"]
    print(f"run={run_id}", flush=True)
    api("POST", f"/runs/{run_id}/discover", {"database_url": RO}, timeout=180)
    print("discovered", flush=True)
    api("POST", f"/runs/{run_id}/predict", timeout=420)
    print("predicted", flush=True)
    api(
        "POST",
        f"/runs/{run_id}/approve",
        {
            "decision": "proceed",
            "approver_identity": OWNER,
            "start_workflow": False,
        },
    )
    started = api("POST", f"/runs/{run_id}/start-workflow", {})
    print(f"started arn={started.get('sfn_execution_arn') or started.get('workflow_execution_arn')}", flush=True)

    # Wait until SFN is actually running, then abort
    for _ in range(40):
        cur = api("GET", f"/runs/{run_id}")
        if cur.get("workflow_status") == "running" or cur.get("sfn_execution_arn"):
            break
        time.sleep(2)

    aborted = api("POST", f"/runs/{run_id}/abort-workflow", {})
    print(
        f"aborted status={aborted.get('status')} workflow={aborted.get('workflow_status')}",
        flush=True,
    )
    # Allow teardown to land
    time.sleep(15)
    try:
        shadow = api("GET", f"/runs/{run_id}/shadow-cluster")
        print(f"shadow_status={shadow.get('status')} destroyed_at={shadow.get('destroyed_at')}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"shadow_lookup={exc}", flush=True)
    print("ABORT_OK", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ABORT_FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
