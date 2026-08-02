"""PATH3 failure-mode probes against live API (clear errors, recoverable)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
import pathlib
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def _judge_ro_url_path():
    """Path to the RO demo URL file (.local_secrets/, legacy root fallback)."""
    import sys as _sys
    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from app.demo_secrets import JUDGE_RO_DATABASE_URL_FILE, demo_secret_path
    return demo_secret_path(JUDGE_RO_DATABASE_URL_FILE)

load_dotenv(ROOT / ".env")
API = os.environ.get("JUDGE_API_BASE", "http://127.0.0.1:8001").rstrip("/")
OWNER = "judge-path3"
OUT = ROOT / "docs" / "judge_walkthrough_artifacts"
OUT.mkdir(parents=True, exist_ok=True)
REPORT: dict[str, Any] = {"started_at": datetime.now(UTC).isoformat(), "cases": []}


def api(method: str, path: str, body: dict | None = None, timeout: int = 120) -> tuple[int, Any]:
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
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            parsed = detail
        return exc.code, parsed


def case(name: str, ok: bool, detail: Any) -> None:
    REPORT["cases"].append({"name": name, "ok": ok, "detail": detail})
    print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def main() -> int:
    # 1. Invalid SQL at create or predict
    code, run = api(
        "POST",
        "/runs",
        {"migration_sql": "NOT VALID SQL ;;;@@@", "owner_identity": OWNER},
    )
    if code >= 400:
        case("invalid_sql_create", True, {"status": code, "body": run})
    else:
        rid = run["id"]
        c2, pred = api("POST", f"/runs/{rid}/predict", timeout=180)
        msg = json.dumps(pred)[:500]
        case(
            "invalid_sql_predict",
            c2 >= 400 or (isinstance(pred, dict) and pred.get("status") == "failed"),
            {"status": c2, "body": msg},
        )

    # 2. Missing table (parseable SQL)
    code, run = api(
        "POST",
        "/runs",
        {
            "migration_sql": "ALTER TABLE definitely_missing_xyz ADD COLUMN a INT;",
            "owner_identity": OWNER,
        },
    )
    rid = run["id"]
    # discover real DB so predict can run with schema that lacks the table
    ro = (_judge_ro_url_path() or ROOT / ".judge_ro_database_url").read_text(encoding="utf-8").strip()
    api("POST", f"/runs/{rid}/discover", {"database_url": ro}, timeout=180)
    c2, pred = api("POST", f"/runs/{rid}/predict", timeout=300)
    # Policy/prediction may still succeed with risk flags — check for coherent response
    ok = c2 == 200 and isinstance(pred, dict) and pred.get("status") in (
        "awaiting_approval",
        "failed",
    )
    flags = pred.get("risk_flags") if isinstance(pred, dict) else None
    case(
        "missing_table_predict",
        ok,
        {"status": c2, "run_status": pred.get("status") if isinstance(pred, dict) else pred, "risk_flags": flags},
    )

    # 3. Bad connection secret ARN on discover
    code, run = api(
        "POST",
        "/runs",
        {
            "migration_sql": "ALTER TABLE customers ADD COLUMN x INT;",
            "owner_identity": OWNER,
        },
    )
    rid = run["id"]
    c2, body = api(
        "POST",
        f"/runs/{rid}/discover",
        {
            "connection_secret_arn": "arn:aws:secretsmanager:us-east-1:123456789012:secret:does-not-exist-abcdef"
        },
        timeout=60,
    )
    text = json.dumps(body).lower()
    case(
        "bad_secret_arn",
        c2 >= 400 and any(x in text for x in ("secret", "not found", "unable", "load", "422", "404", "403")),
        {"status": c2, "body": body},
    )

    # 4. Unreachable database URL
    code, run = api(
        "POST",
        "/runs",
        {
            "migration_sql": "ALTER TABLE customers ADD COLUMN y INT;",
            "owner_identity": OWNER,
        },
    )
    rid = run["id"]
    c2, body = api(
        "POST",
        f"/runs/{rid}/discover",
        {
            "database_url": "postgresql://nobody:wrong@127.0.0.1:1/nope?sslmode=disable"
        },
        timeout=60,
    )
    text = json.dumps(body).lower()
    case(
        "unreachable_db",
        c2 >= 400 and any(x in text for x in ("connect", "refused", "timeout", "unreachable", "failed", "error")),
        {"status": c2, "body": body},
    )

    # 5. accept_recommended → completed, no shadow
    code, fake = api("POST", f"/runs/debug/fake-migration?owner_identity={OWNER}")
    rid = fake["id"]
    c2, pred = api("POST", f"/runs/{rid}/predict", timeout=300)
    rationale = None
    if isinstance(pred, dict) and pred.get("policy_decision") == "block":
        rationale = "path3 accept_recommended"
    c3, done = api(
        "POST",
        f"/runs/{rid}/approve",
        {
            "decision": "accept_recommended",
            "approver_identity": OWNER,
            "override_rationale": rationale,
            "start_workflow": False,
        },
    )
    case(
        "accept_recommended",
        c3 == 200 and done.get("status") == "completed",
        {"status": done.get("status"), "workflow": done.get("workflow_status")},
    )
    # confirm no shadow row required
    c4, shadow = api("GET", f"/runs/{rid}/shadow-cluster")
    case(
        "accept_recommended_no_shadow",
        c4 == 404 or (isinstance(shadow, dict) and "not found" in json.dumps(shadow).lower()),
        {"status": c4, "body": shadow},
    )

    # 6. Policy block override rationale recorded
    # Use a high-risk-ish SQL if policy blocks; else note skip
    code, run = api(
        "POST",
        "/runs",
        {
            "migration_sql": "DROP TABLE customers;",
            "owner_identity": OWNER,
        },
    )
    rid = run["id"]
    api("POST", f"/runs/{rid}/discover", {"database_url": ro}, timeout=180)
    c2, pred = api("POST", f"/runs/{rid}/predict", timeout=300)
    policy = pred.get("policy_decision") if isinstance(pred, dict) else None
    if policy == "block":
        c3, done = api(
            "POST",
            f"/runs/{rid}/approve",
            {
                "decision": "proceed",
                "approver_identity": OWNER,
                "override_rationale": "Judge PATH3: recording override rationale visibility",
                "start_workflow": False,
            },
        )
        # fetch approval via run explainability or nested - check run has approval
        full = api("GET", f"/runs/{rid}")[1]
        # Approval may not be embedded; use OpenAPI - check grade path N/A
        case(
            "policy_block_override",
            c3 == 200 and done.get("status") == "running",
            {"policy": policy, "status": done.get("status"), "run": full.get("status")},
        )
    else:
        case(
            "policy_block_override",
            True,
            {"skipped": True, "policy": policy, "note": "DROP did not block; override path not exercised"},
        )

    # 7. Cancel at awaiting_approval
    code, fake = api("POST", f"/runs/debug/fake-migration?owner_identity={OWNER}")
    rid = fake["id"]
    api("POST", f"/runs/{rid}/predict", timeout=300)
    c3, done = api(
        "POST",
        f"/runs/{rid}/approve",
        {
            "decision": "cancel",
            "approver_identity": OWNER,
            "start_workflow": False,
        },
    )
    case(
        "cancel_awaiting_approval",
        c3 == 200 and done.get("status") == "failed",
        {"status": done.get("status")},
    )

    REPORT["finished_at"] = datetime.now(UTC).isoformat()
    path = OUT / "path3_report.json"
    path.write_text(json.dumps(REPORT, indent=2, default=str), encoding="utf-8")
    print("Wrote", path, flush=True)
    failed = [c for c in REPORT["cases"] if not c["ok"]]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
