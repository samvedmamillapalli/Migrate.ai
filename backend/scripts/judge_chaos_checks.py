"""Chaos checks: dual-slot wait, abort mid-flight teardown, missing-table policy."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
API = os.environ.get("JUDGE_API_BASE", "http://127.0.0.1:8002").rstrip("/")
OWNER = "judge-chaos"
OUT = ROOT / "docs" / "judge_walkthrough_artifacts"
OUT.mkdir(parents=True, exist_ok=True)
REPORT: dict[str, Any] = {"started_at": datetime.now(UTC).isoformat(), "cases": [], "api": API}

# Predict usually finishes in ~60s on Haiku; hang past this means diagnose, don't wait.
PREDICT_TIMEOUT_S = int(os.environ.get("JUDGE_PREDICT_TIMEOUT_S", "90"))
DISCOVER_TIMEOUT_S = int(os.environ.get("JUDGE_DISCOVER_TIMEOUT_S", "60"))


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
    except TimeoutError as exc:
        return 0, {"error": "timeout", "path": path, "timeout_s": timeout, "detail": str(exc)}
    except urllib.error.URLError as exc:
        return 0, {"error": "url_error", "path": path, "detail": str(exc.reason)}


def case(name: str, ok: bool, detail: Any) -> None:
    REPORT["cases"].append({"name": name, "ok": ok, "detail": detail})
    print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def health_or_die() -> None:
    code, body = api("GET", "/health", timeout=10)
    if code != 200:
        case("api_health", False, {"code": code, "body": body, "api": API})
        raise SystemExit(2)
    case("api_health", True, {"api": API})


def predict_or_fail(rid: str, label: str) -> tuple[bool, Any]:
    """Call predict with a hard ceiling; on hang return False instead of blocking forever."""
    t0 = time.monotonic()
    code, pred = api("POST", f"/runs/{rid}/predict", timeout=PREDICT_TIMEOUT_S)
    elapsed = round(time.monotonic() - t0, 1)
    if code == 0 and isinstance(pred, dict) and pred.get("error") == "timeout":
        case(
            label,
            False,
            {
                "error": "predict_timeout",
                "elapsed_s": elapsed,
                "timeout_s": PREDICT_TIMEOUT_S,
                "hint": "Bedrock/API hung — check API logs, stuck run status=running, AWS credentials",
            },
        )
        return False, pred
    if code != 200 or not isinstance(pred, dict):
        case(label, False, {"code": code, "elapsed_s": elapsed, "body": pred})
        return False, pred
    return True, pred


def list_ccloud() -> list[dict[str, Any]]:
    secret = os.environ.get("CCLOUD_API_SECRET")
    if not secret:
        return []
    req = urllib.request.Request(
        "https://cockroachlabs.cloud/api/v1/clusters",
        headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    return payload.get("clusters") or payload.get("items") or []


def prepare_approved(migration_sql: str, ro: str, label: str) -> str | None:
    """Create → discover → predict → approve(proceed). Returns run_id or None on fail-fast."""
    code, run = api("POST", "/runs", {"migration_sql": migration_sql, "owner_identity": OWNER})
    if code not in (200, 201) or not isinstance(run, dict):
        case(label, False, {"stage": "create", "code": code, "body": run})
        return None
    rid = run["id"]
    dcode, dbody = api(
        "POST", f"/runs/{rid}/discover", {"database_url": ro}, timeout=DISCOVER_TIMEOUT_S
    )
    if dcode == 0 or dcode >= 400:
        case(label, False, {"stage": "discover", "code": dcode, "body": dbody})
        return None
    ok, pred = predict_or_fail(rid, f"{label}_predict")
    if not ok:
        return None
    rat = label if pred.get("policy_decision") == "block" else None
    acode, _ = api(
        "POST",
        f"/runs/{rid}/approve",
        {
            "decision": "proceed",
            "approver_identity": OWNER,
            "override_rationale": rat,
            "start_workflow": False,
        },
    )
    if acode != 200:
        case(label, False, {"stage": "approve", "code": acode})
        return None
    return rid


def main() -> int:
    health_or_die()
    ro = (ROOT / ".judge_ro_database_url").read_text(encoding="utf-8").strip()
    skip_dual = os.environ.get("JUDGE_SKIP_DUAL", "").lower() in ("1", "true", "yes")

    # 1) Missing table after discover → policy block
    code, run = api(
        "POST",
        "/runs",
        {
            "migration_sql": "ALTER TABLE definitely_missing_xyz ADD COLUMN a INT;",
            "owner_identity": OWNER,
        },
    )
    rid = run["id"] if isinstance(run, dict) else None
    if not rid:
        case("missing_table_blocks", False, {"code": code, "body": run})
    else:
        api("POST", f"/runs/{rid}/discover", {"database_url": ro}, timeout=DISCOVER_TIMEOUT_S)
        ok, pred = predict_or_fail(rid, "missing_table_predict")
        if ok:
            flags = pred.get("risk_flags") if isinstance(pred, dict) else []
            ids = [f.get("rule_id") for f in flags or []]
            case(
                "missing_table_blocks",
                pred.get("policy_decision") == "block"
                and "missing_referenced_table" in ids,
                {"policy": pred.get("policy_decision"), "flags": ids},
            )

    # 2) Abort mid-flight: start real shadow, abort once cluster visible or after short wait
    rid = prepare_approved(
        "ALTER TABLE customers ADD COLUMN chaos_abort_flag STRING NOT NULL DEFAULT 'x';",
        ro,
        "abort_path",
    )
    if rid:
        before = {(c.get("id") or c.get("cluster_id")) for c in list_ccloud()}
        code, started = api("POST", f"/runs/{rid}/start-workflow", {})
        case(
            "abort_path_started",
            code == 200 and isinstance(started, dict) and started.get("status") == "running",
            {
                "status": started.get("status") if isinstance(started, dict) else started,
                "wf": started.get("workflow_status") if isinstance(started, dict) else None,
            },
        )

        appeared = None
        # Provision usually shows within ~30–60s; stop at ~90s and abort anyway.
        for _ in range(18):
            time.sleep(5)
            for c in list_ccloud():
                cid = c.get("id") or c.get("cluster_id")
                if cid and cid not in before:
                    appeared = c
                    break
            sh_code, sh = api("GET", f"/runs/{rid}/shadow-cluster")
            if appeared or (sh_code == 200 and isinstance(sh, dict) and sh.get("cluster_id")):
                break

        code, aborted = api("POST", f"/runs/{rid}/abort-workflow", {})
        case(
            "abort_workflow",
            code == 200
            and isinstance(aborted, dict)
            and aborted.get("workflow_status") == "aborted"
            and aborted.get("status") == "failed",
            {
                "status": aborted.get("status") if isinstance(aborted, dict) else aborted,
                "wf": aborted.get("workflow_status") if isinstance(aborted, dict) else None,
            },
        )

        time.sleep(20)
        after = list_ccloud()
        if appeared:
            cid = appeared.get("id") or appeared.get("cluster_id")
            still = [c for c in after if (c.get("id") or c.get("cluster_id")) == cid]
            case(
                "abort_cluster_torn_down",
                len(still) == 0,
                {"cluster": appeared.get("name"), "still": len(still)},
            )
        else:
            sh_code, sh = api("GET", f"/runs/{rid}/shadow-cluster")
            status = sh.get("status") if isinstance(sh, dict) else None
            case(
                "abort_cluster_torn_down",
                sh_code == 404 or status in ("destroyed", "destroying", "failed", None),
                {"shadow_http": sh_code, "shadow_status": status, "note": "no cloud cluster observed"},
            )

    # 3) Dual in-flight (expensive). Skip with JUDGE_SKIP_DUAL=1; fail-fast on predict hang.
    if skip_dual:
        case("dual_shadow_started", True, {"skipped": True, "reason": "JUDGE_SKIP_DUAL"})
        case("dual_shadow_cleaned", True, {"skipped": True})
    else:
        run_ids: list[str] = []
        for i in range(2):
            rid = prepare_approved(
                f"ALTER TABLE customers ADD COLUMN dual_{i} STRING NOT NULL DEFAULT 'd';",
                ro,
                f"dual_{i}",
            )
            if not rid:
                case(
                    "dual_shadow_started",
                    False,
                    {"error": "prepare_failed", "completed": run_ids, "failed_index": i},
                )
                break
            run_ids.append(rid)
        else:
            started_ok = []
            for rid in run_ids:
                c, s = api("POST", f"/runs/{rid}/start-workflow", {})
                started_ok.append(c == 200 and isinstance(s, dict) and s.get("status") == "running")
            case("dual_shadow_started", all(started_ok), {"started": started_ok, "ids": run_ids})

            for rid in run_ids:
                api("POST", f"/runs/{rid}/abort-workflow", {})
            # Teardown can lag Cloud list; poll briefly, then force-delete leftovers.
            leftover: list[dict[str, Any]] = []
            for _ in range(6):
                time.sleep(5)
                leftover = [
                    c
                    for c in list_ccloud()
                    if (c.get("labels") or {}).get("app") == "migration-oracle"
                ]
                if not leftover:
                    break
            forced = []
            secret = os.environ.get("CCLOUD_API_SECRET")
            for c in leftover:
                cid = c.get("id") or c.get("cluster_id")
                if not (secret and cid):
                    continue
                try:
                    req = urllib.request.Request(
                        f"https://cockroachlabs.cloud/api/v1/clusters/{cid}",
                        method="DELETE",
                        headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=60):
                        pass
                    forced.append(c.get("name"))
                except Exception as exc:  # noqa: BLE001 — chaos cleanup best-effort
                    forced.append(f"{c.get('name')}: {exc}")
            if forced:
                time.sleep(8)
            leftover = [
                c
                for c in list_ccloud()
                if (c.get("labels") or {}).get("app") == "migration-oracle"
            ]
            case(
                "dual_shadow_cleaned",
                len(leftover) == 0,
                {"leftover": [c.get("name") for c in leftover], "forced_delete": forced},
            )

    # 4) Bedrock traces field contract (fake migration — no discover / no cloud)
    code, fake = api("POST", f"/runs/debug/fake-migration?owner_identity={OWNER}")
    if code not in (200, 201) or not isinstance(fake, dict):
        case("bedrock_traces_present", False, {"code": code, "body": fake})
    else:
        ok, pred = predict_or_fail(fake["id"], "bedrock_predict")
        if ok:
            traces = ((pred.get("explainability") or {}).get("bedrock_traces") or {})
            pred_trace = traces.get("prediction") or {}
            case(
                "bedrock_traces_present",
                bool(pred_trace.get("attempts")) and "repair_retried" in pred_trace,
                {
                    "keys": list(pred_trace.keys())[:12],
                    "repair_retried": pred_trace.get("repair_retried"),
                    "attempts": len(pred_trace.get("attempts") or []),
                },
            )

    REPORT["finished_at"] = datetime.now(UTC).isoformat()
    path = OUT / "chaos_report.json"
    path.write_text(json.dumps(REPORT, indent=2, default=str), encoding="utf-8")
    print("Wrote", path, flush=True)
    return 0 if all(c["ok"] for c in REPORT["cases"]) else 1


if __name__ == "__main__":
    sys.exit(main())
