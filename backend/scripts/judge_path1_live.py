"""PATH1 happy-path judge driver: real discover → predict → SFN shadow → grade → closed loop.

Uses the HTTP API against a live backend (ccloud_api + Step Functions). Optionally
takes Next.js screenshots via Playwright when JUDGE_UI_SHOTS=1.

Wall-clock timings and Cockroach Cloud cluster evidence are written to
docs/judge_walkthrough_artifacts/path1_report.json.
"""

from __future__ import annotations

# Windows: Playwright needs Proactor; psycopg needs Selector. This script is
# urllib + optional Playwright only — force Proactor before anything else.
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import json
import os
import time
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
WEB = os.environ.get("JUDGE_WEB_BASE", "http://localhost:3000").rstrip("/")
OWNER = os.environ.get("JUDGE_OWNER", "judge-demo")
OUT = ROOT / "docs" / "judge_walkthrough_artifacts"
OUT.mkdir(parents=True, exist_ok=True)

REPORT: dict[str, Any] = {
    "started_at": datetime.now(UTC).isoformat(),
    "api": API,
    "timings_seconds": {},
    "clusters_seen": [],
    "bugs": [],
    "notes": [],
    "closed_loop": {},
}


def note(msg: str, **extra: Any) -> None:
    entry = {"msg": msg, "at": datetime.now(UTC).isoformat(), **extra}
    REPORT["notes"].append(entry)
    print(f"[path1] {msg}", extra or "", flush=True)


def bug(severity: str, title: str, detail: str, fixed: bool = False) -> None:
    REPORT["bugs"].append(
        {"severity": severity, "title": title, "detail": detail, "fixed": fixed}
    )
    print(f"[{severity}] {title}: {detail}", flush=True)


def api_json(
    method: str, path: str, body: dict | None = None, timeout: int = 600
) -> Any:
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


def list_ccloud_clusters() -> list[dict[str, Any]]:
    secret = os.environ.get("CCLOUD_API_SECRET")
    if not secret:
        return []
    req = urllib.request.Request(
        "https://cockroachlabs.cloud/api/v1/clusters",
        headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    clusters = payload.get("clusters") or payload.get("items") or []
    return clusters if isinstance(clusters, list) else []


def cluster_summary(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("id") or c.get("cluster_id"),
        "name": c.get("name"),
        "state": c.get("state") or c.get("status"),
        "created": c.get("created_at") or c.get("created"),
        "labels": c.get("labels") or {},
        "cloud_provider": c.get("cloud_provider") or c.get("provider"),
        "regions": c.get("regions"),
    }


def ui_shot(name: str, run_id: str | None = None) -> None:
    if os.environ.get("JUDGE_UI_SHOTS", "1") != "1":
        return
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        note(f"ui shot skipped (playwright import): {exc}")
        return
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{WEB}/dashboard/settings")
            page.wait_for_load_state("domcontentloaded")
            if page.locator("#owner-identity-settings").count():
                page.locator("#owner-identity-settings").fill(OWNER)
            if run_id:
                page.evaluate(
                    "(id) => localStorage.setItem('oracle:current_run_id', id)",
                    run_id,
                )
                page.goto(f"{WEB}/dashboard/migrations/current")
            else:
                page.goto(f"{WEB}/dashboard/migrations/current")
            page.wait_for_load_state("networkidle")
            path = OUT / f"{name}.png"
            page.screenshot(path=str(path), full_page=True)
            browser.close()
            note(f"screenshot {path.name}")
    except Exception as exc:  # noqa: BLE001
        note(f"ui shot failed {name}: {exc}")


def wait_run_terminal(run_id: str, t0: float, max_s: int = 2400) -> dict[str, Any]:
    before = { (c.get("id") or c.get("cluster_id")) for c in list_ccloud_clusters() }
    appeared: dict[str, Any] | None = None
    appeared_at: float | None = None
    gone_at: float | None = None
    last_status = None
    while time.perf_counter() - t0 < max_s:
        run = api_json("GET", f"/runs/{run_id}")
        status = run.get("status")
        wf = run.get("workflow_status")
        if (status, wf) != last_status:
            note(f"run status={status} workflow={wf}")
            last_status = (status, wf)
            try:
                prog = api_json("GET", f"/runs/{run_id}/pipeline-progress")
                note("pipeline", progress=prog)
            except Exception:  # noqa: BLE001
                pass
            try:
                shadow = api_json("GET", f"/runs/{run_id}/shadow-cluster")
                note(
                    "shadow-cluster",
                    status=shadow.get("status"),
                    provider_id=shadow.get("provider_cluster_id")
                    or shadow.get("cluster_id"),
                    scale_tier=shadow.get("scale_tier"),
                    created_at=shadow.get("created_at"),
                    destroyed_at=shadow.get("destroyed_at"),
                )
                REPORT.setdefault("shadow_snapshots", []).append(shadow)
            except Exception as exc:  # noqa: BLE001
                note(f"shadow-cluster not ready: {exc}")

        clusters = list_ccloud_clusters()
        for c in clusters:
            cid = c.get("id") or c.get("cluster_id")
            labels = c.get("labels") or {}
            if cid and cid not in before:
                appeared = cluster_summary(c)
                appeared_at = time.perf_counter()
                before.add(cid)
                REPORT["clusters_seen"].append(
                    {**appeared, "seen_at": datetime.now(UTC).isoformat()}
                )
                note(
                    "NEW cloud cluster",
                    name=appeared.get("name"),
                    id=cid,
                    labels=labels,
                    state=appeared.get("state"),
                    created=appeared.get("created"),
                )
                # Persist evidence JSON (console substitute)
                (OUT / "path1_cluster_created.json").write_text(
                    json.dumps(appeared, indent=2), encoding="utf-8"
                )

        if appeared:
            cid = appeared["id"]
            still = [
                c
                for c in clusters
                if (c.get("id") or c.get("cluster_id")) == cid
            ]
            if not still and gone_at is None:
                gone_at = time.perf_counter()
                note("cloud cluster gone (torn down)")
                (OUT / "path1_cluster_destroyed.json").write_text(
                    json.dumps(
                        {
                            "id": cid,
                            "name": appeared.get("name"),
                            "destroyed_observed_at": datetime.now(UTC).isoformat(),
                            "lifetime_seconds_approx": round(gone_at - (appeared_at or t0), 1),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )

        if status in ("completed", "failed"):
            REPORT["timings_seconds"]["shadow_total"] = round(
                time.perf_counter() - t0, 2
            )
            if appeared_at is not None:
                REPORT["timings_seconds"]["until_cluster_visible"] = round(
                    appeared_at - t0, 2
                )
            if gone_at is not None and appeared_at is not None:
                REPORT["timings_seconds"]["cluster_lifetime_visible"] = round(
                    gone_at - appeared_at, 2
                )
            return run
        time.sleep(10)
    raise TimeoutError(f"run {run_id} not terminal after {max_s}s")


def main() -> None:
    ro_path = _judge_ro_url_path() or ROOT / ".judge_ro_database_url"
    if not ro_path.exists():
        raise SystemExit("missing .judge_ro_database_url")
    ro_url = ro_path.read_text(encoding="utf-8").strip()
    migration_sql = (
        "ALTER TABLE customers ADD COLUMN status STRING NOT NULL DEFAULT 'active';"
    )

    health = api_json("GET", "/health")
    integ = health.get("integrations") or {}
    note(
        "health",
        sfn_ready=integ.get("sfn_ready"),
        shadow=integ.get("shadow_provider"),
        bedrock=integ.get("bedrock_configured"),
    )
    if not integ.get("sfn_ready") or integ.get("shadow_provider") != "ccloud_api":
        raise SystemExit("SFN/ccloud_api not ready — refusing fake path")

    ui_shot("path1_before")

    t0 = time.perf_counter()
    run = api_json(
        "POST",
        "/runs",
        {
            "migration_sql": migration_sql,
            "owner_identity": OWNER,
        },
    )
    run_id = run["id"]
    REPORT["run_id"] = run_id
    REPORT["timings_seconds"]["create_run"] = round(time.perf_counter() - t0, 2)
    note("created", run_id=run_id, seconds=REPORT["timings_seconds"]["create_run"])
    ui_shot("path1_created", run_id)

    t1 = time.perf_counter()
    disc = api_json(
        "POST",
        f"/runs/{run_id}/discover",
        {"database_url": ro_url},
        timeout=180,
    )
    REPORT["timings_seconds"]["discover"] = round(time.perf_counter() - t1, 2)
    tables = []
    snap = disc.get("schema_snapshot") or disc.get("discovered_schema") or {}
    for sch in snap.get("schemas") or []:
        for tbl in sch.get("tables") or []:
            tables.append(tbl.get("name") or tbl.get("table_name"))
    if "customers" not in tables and not any("customer" in (t or "").lower() for t in tables):
        # flat fallback
        flat = snap.get("tables") or disc.get("tables") or []
        tables = [t.get("name") if isinstance(t, dict) else t for t in flat]
    note("discover", seconds=REPORT["timings_seconds"]["discover"], tables=tables[:20])
    if "customers" not in [t for t in tables if t]:
        bug("critical", "discover_missing_customers", f"tables={tables}")
    ui_shot("path1_discovered", run_id)

    t2 = time.perf_counter()
    pred = api_json("POST", f"/runs/{run_id}/predict", timeout=420)
    REPORT["timings_seconds"]["predict"] = round(time.perf_counter() - t2, 2)
    note(
        "predict",
        seconds=REPORT["timings_seconds"]["predict"],
        status=pred.get("status"),
        policy=pred.get("policy_decision"),
        confidence=(pred.get("explainability") or {}).get("confidence"),
    )
    REPORT["prediction"] = {
        "policy_decision": pred.get("policy_decision"),
        "risk_flags": pred.get("risk_flags"),
        "recommendation": pred.get("recommendation"),
        "explainability": pred.get("explainability"),
    }
    ui_shot("path1_predicted", run_id)

    expl = pred.get("explainability") or {}
    if not expl.get("prediction"):
        bug("high", "prediction_incomplete", "missing explainability.prediction")
    conf = expl.get("confidence") or {}
    if conf.get("was_reduced") or conf.get("wasReduced"):
        note("confidence reduced", adjustments=conf.get("adjustments"))

    override = None
    if pred.get("policy_decision") == "block":
        override = "Judge PATH1: measured shadow verify required for demo."

    t3 = time.perf_counter()
    approved = api_json(
        "POST",
        f"/runs/{run_id}/approve",
        {
            "decision": "proceed",
            "approver_identity": OWNER,
            "override_rationale": override,
            "start_workflow": False,
        },
    )
    REPORT["timings_seconds"]["approve"] = round(time.perf_counter() - t3, 2)
    note(
        "approved",
        seconds=REPORT["timings_seconds"]["approve"],
        status=approved.get("status"),
    )
    ui_shot("path1_approved", run_id)

    before_clusters = list_ccloud_clusters()
    note("ccloud before", count=len(before_clusters), names=[c.get("name") for c in before_clusters])

    t4 = time.perf_counter()
    started = api_json("POST", f"/runs/{run_id}/start-workflow", {})
    note("workflow started", execution=started.get("workflow_execution_arn") or started)
    ui_shot("path1_shadow_starting", run_id)

    terminal = wait_run_terminal(run_id, t4)
    REPORT["terminal"] = {
        "status": terminal.get("status"),
        "workflow_status": terminal.get("workflow_status"),
        "error_message": terminal.get("error_message"),
    }
    ui_shot("path1_shadow_done", run_id)

    for label, path in [
        ("grade", f"/runs/{run_id}/grade"),
        ("memory", f"/runs/{run_id}/memory"),
        ("execution", f"/runs/{run_id}/execution-result"),
        ("shadow", f"/runs/{run_id}/shadow-cluster"),
    ]:
        try:
            data = api_json("GET", path)
            REPORT[label] = {
                k: data.get(k) for k in list(data)[:20]
            }
            note(f"{label} ok", keys=list(data)[:12])
        except Exception as exc:  # noqa: BLE001
            bug("high", f"missing_{label}", str(exc))

    # Closed loop: second similar migration must retrieve first memory
    mem1 = REPORT.get("memory") or {}
    mem1_id = mem1.get("id")
    mem1_run = run_id
    migration2 = (
        "ALTER TABLE customers ADD COLUMN loyalty_tier STRING NOT NULL DEFAULT 'standard';"
    )
    t5 = time.perf_counter()
    run2 = api_json(
        "POST",
        "/runs",
        {
            "migration_sql": migration2,
            "owner_identity": OWNER,
        },
    )
    run2_id = run2["id"]
    api_json(
        "POST",
        f"/runs/{run2_id}/discover",
        {"database_url": ro_url},
        timeout=180,
    )
    t6 = time.perf_counter()
    pred2 = api_json("POST", f"/runs/{run2_id}/predict", timeout=420)
    REPORT["timings_seconds"]["predict_second"] = round(time.perf_counter() - t6, 2)
    REPORT["timings_seconds"]["closed_loop_setup"] = round(time.perf_counter() - t5, 2)
    mem_block = (pred2.get("explainability") or {}).get("memory") or {}
    retrieved = mem_block.get("memories") or mem_block.get("retrieved_memories") or []
    run_ids_hit = [
        str(m.get("migration_run_id") or "")
        for m in retrieved
        if isinstance(m, dict)
    ]
    summaries = [
        (m.get("migration_summary") or "")[:120]
        for m in retrieved
        if isinstance(m, dict)
    ]
    hit = str(mem1_run) in run_ids_hit
    # Also accept strong similarity hit on same owner graded outcome if id mapping differs
    graded_hits = [
        m
        for m in retrieved
        if isinstance(m, dict) and not m.get("not_a_graded_run")
    ]
    REPORT["closed_loop"] = {
        "second_run_id": run2_id,
        "first_run_id": mem1_run,
        "first_memory_id": mem1_id,
        "retrieved_run_ids": run_ids_hit,
        "retrieved_summaries": summaries,
        "graded_hit_count": len(graded_hits),
        "retrieval_attempted": mem_block.get("retrieval_attempted"),
        "empty_vs_never_attempted": mem_block.get("empty_vs_never_attempted"),
        "hit_first_run_memory": hit,
        "memory_block_keys": list(mem_block.keys()),
    }
    if hit:
        note("CLOSED LOOP HIT — first run memory retrieved on second predict")
    elif graded_hits:
        note(
            "closed-loop partial — graded memories retrieved but not exact first run",
            graded=len(graded_hits),
            summaries=summaries[:3],
        )
        bug(
            "critical",
            "closed_loop_retrieval_miss",
            f"expected run {mem1_run} in {run_ids_hit}; graded_hits={len(graded_hits)}",
        )
    else:
        bug(
            "critical",
            "closed_loop_retrieval_miss",
            f"first_run={mem1_run} retrieved={run_ids_hit} block={mem_block}",
        )
    ui_shot("path1_second_predict", run2_id)
    REPORT["second_prediction_memory"] = mem_block

    # Cost estimate if we can infer from shadow row
    shadow = REPORT.get("shadow") or {}
    REPORT["cost_notes"] = {
        "scale_tier": shadow.get("scale_tier"),
        "provider": shadow.get("provider"),
        "lifetime_seconds": REPORT["timings_seconds"].get("cluster_lifetime_visible")
        or REPORT["timings_seconds"].get("shadow_total"),
        "note": "Cockroach Serverless/dev billing is account-specific; see Cloud invoice if available.",
    }

    REPORT["finished_at"] = datetime.now(UTC).isoformat()
    out = OUT / "path1_report.json"
    out.write_text(json.dumps(REPORT, indent=2, default=str), encoding="utf-8")
    print("Wrote", out, flush=True)
    print("TIMINGS", json.dumps(REPORT["timings_seconds"], indent=2), flush=True)
    if terminal.get("status") != "completed":
        raise SystemExit(f"PATH1 terminal status={terminal.get('status')}")


if __name__ == "__main__":
    main()
