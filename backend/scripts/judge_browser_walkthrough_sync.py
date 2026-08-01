"""Sync Playwright judge walkthrough (Windows-compatible).

See judge_browser_walkthrough.py for intent. This sync driver avoids the
Windows SelectorEventLoop + Playwright subprocess conflict.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

API = os.environ.get("JUDGE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
WEB = os.environ.get("JUDGE_WEB_BASE", "http://localhost:3000").rstrip("/")
OUT = ROOT / "docs" / "judge_walkthrough_artifacts"
OUT.mkdir(parents=True, exist_ok=True)

REPORT: dict[str, Any] = {
    "started_at": datetime.now(UTC).isoformat(),
    "paths": {},
    "bugs": [],
    "timings_seconds": {},
    "clusters_seen": [],
    "could_not_test": [],
}


def bug(severity: str, title: str, detail: str, fixed: bool = False) -> None:
    REPORT["bugs"].append(
        {"severity": severity, "title": title, "detail": detail, "fixed": fixed}
    )
    print(f"[{severity}] {title}: {detail} (fixed={fixed})")


def note(path: str, msg: str, **extra: Any) -> None:
    REPORT["paths"].setdefault(path, []).append({"msg": msg, **extra})
    print(f"[{path}] {msg}", extra or "")


def api_json(method: str, path: str, body: dict | None = None, timeout: int = 600) -> Any:
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
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        note("path2", f"ccloud list failed: {exc}")
        return []
    clusters = payload.get("clusters") or payload.get("items") or []
    return clusters if isinstance(clusters, list) else []


def shot(page, name: str) -> Path:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


def set_owner(page, identity: str = "judge-demo") -> None:
    page.goto(f"{WEB}/dashboard/settings")
    page.wait_for_load_state("networkidle")
    page.locator("#owner-identity-settings").fill(identity)
    # Keep sidebar in sync if present
    if page.locator("#owner-identity-sidebar").count():
        page.locator("#owner-identity-sidebar").fill(identity)
    shot(page, "settings_owner")


def path4_empty_and_honesty(page) -> None:
    for route, name in [
        ("/dashboard", "overview"),
        ("/dashboard/migrations/history", "history"),
        ("/dashboard/memory", "memory"),
        ("/dashboard/settings", "settings"),
        ("/dashboard/migrations/current", "current_empty"),
        ("/", "landing"),
    ]:
        t0 = time.perf_counter()
        page.goto(f"{WEB}{route}")
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except PlaywrightTimeout:
            bug("medium", f"slow_or_stuck_{name}", f"{route} did not reach networkidle")
        shot(page, f"path4_{name}")
        body = page.inner_text("body")
        if "operator@migrationoracle.dev" in body:
            bug("high", "fake_sidebar_user", "Fake operator email still visible")
        if "Coming soon" in body or "coming soon" in body:
            bug("high", "coming_soon_visible", f"{route} still shows coming soon")
        if route == "/":
            if page.locator('a[href="/docs"]').count():
                bug("high", "broken_docs_link", "Landing still links to /docs")
            if page.locator('a[href="/sign-in"]').count():
                bug("medium", "sign_in_cta", "Landing still has Sign In CTA")
        note("path4", f"rendered {route}", seconds=round(time.perf_counter() - t0, 2))

    page.goto(f"{WEB}/dashboard/memory")
    page.wait_for_load_state("networkidle")
    text = page.inner_text("body")
    mem = api_json("GET", "/memories?limit=20")
    corpus = [i for i in (mem.get("items") or []) if i.get("not_a_graded_run")]
    if corpus and "Open-source corpus" not in text and "not a graded run" not in text.lower():
        bug(
            "high",
            "corpus_not_badged",
            f"API has {len(corpus)} corpus memories but UI does not badge them",
        )
    else:
        note("path4", f"memory page ok (corpus_api={len(corpus)})")

    metrics = api_json("GET", "/runs/metrics/accuracy")
    page.goto(f"{WEB}/dashboard")
    page.wait_for_load_state("networkidle")
    overview = page.inner_text("body")
    trend = metrics.get("scalar_accuracy_trend") or []
    if len(trend) == 0 and (
        "no graded" in overview.lower()
        or "0 graded" in overview.lower()
        or "empty" in overview.lower()
        or "honest" in overview.lower()
        or "not enough" in overview.lower()
    ):
        note("path4", "overview honest about zero/empty graded sample")
    elif len(trend) == 0:
        # soft check — screenshot for human
        note("path4", "zero graded runs; inspect overview screenshot for honesty")
        shot(page, "path4_overview_metrics")


def path1_happy(page) -> None:
    ro_path = ROOT / ".judge_ro_database_url"
    if not ro_path.exists():
        REPORT["could_not_test"].append("PATH1: missing .judge_ro_database_url")
        return
    ro_url = ro_path.read_text(encoding="utf-8").strip()
    migration_sql = (
        "ALTER TABLE customers ADD COLUMN status STRING NOT NULL DEFAULT 'active';"
    )

    set_owner(page, "judge-demo")
    page.goto(f"{WEB}/dashboard/migrations/current")
    page.evaluate("() => localStorage.removeItem('oracle:current_run_id')")
    page.reload()
    page.wait_for_load_state("networkidle")
    page.locator("#owner-identity-sidebar").fill("judge-demo")
    shot(page, "path1_empty")

    page.locator("textarea").first.fill(migration_sql)
    t_create = time.perf_counter()
    page.get_by_role("button", name="Create run").click()
    page.wait_for_selector("text=Schema discovery", timeout=60_000)
    REPORT["timings_seconds"]["create_run"] = round(time.perf_counter() - t_create, 2)
    shot(page, "path1_created")
    note("path1", "created run", seconds=REPORT["timings_seconds"]["create_run"])

    page.locator("#database-url").fill(ro_url)
    t_disc = time.perf_counter()
    page.get_by_role("button", name="Discover schema").click()
    try:
        page.wait_for_selector("text=customers", timeout=180_000)
        REPORT["timings_seconds"]["discover"] = round(time.perf_counter() - t_disc, 2)
        note("path1", "discover ok", seconds=REPORT["timings_seconds"]["discover"])
    except PlaywrightTimeout:
        shot(page, "path1_discover_fail")
        bug("critical", "discover_failed", page.inner_text("body")[:500])
        return
    shot(page, "path1_discovered")

    t_pred = time.perf_counter()
    page.get_by_role("button", name="Run prediction").click()
    try:
        page.wait_for_selector("text=Assessment", timeout=420_000)
        REPORT["timings_seconds"]["predict"] = round(time.perf_counter() - t_pred, 2)
        note("path1", "predict ok", seconds=REPORT["timings_seconds"]["predict"])
    except PlaywrightTimeout:
        shot(page, "path1_predict_fail")
        bug("critical", "predict_timeout", page.inner_text("body")[:800])
        return
    shot(page, "path1_predicted")
    body = page.inner_text("body")
    for needle in ["Retrieval transparency", "Distributed Vector Indexing", "Proceed"]:
        if needle not in body:
            bug("high", "missing_ui", f"Missing after predict: {needle}")

    # Policy block may require rationale
    if "block" in body.lower() and "override" in body.lower():
        page.locator("#override-rationale").fill(
            "Judge walkthrough: measured shadow verify required for demo."
        )

    t_appr = time.perf_counter()
    page.get_by_role("button", name="Proceed", exact=True).click()
    try:
        page.wait_for_selector("text=Shadow test", timeout=90_000)
        REPORT["timings_seconds"]["approve"] = round(time.perf_counter() - t_appr, 2)
    except PlaywrightTimeout:
        shot(page, "path1_approve_fail")
        bug("critical", "approve_failed", page.inner_text("body")[:800])
        return
    shot(page, "path1_approved")

    before = list_ccloud_clusters()
    before_ids = {(c.get("id") or c.get("cluster_id")) for c in before}
    note("path1", f"ccloud clusters before={len(before)}")

    t_sh = time.perf_counter()
    page.get_by_role("button", name="Start shadow test").click()
    shot(page, "path1_shadow_starting")

    terminal = False
    appeared = None
    for i in range(150):  # ~25 min
        time.sleep(10)
        clusters = list_ccloud_clusters()
        for c in clusters:
            cid = c.get("id") or c.get("cluster_id")
            if cid and cid not in before_ids:
                appeared = c
                REPORT["clusters_seen"].append(
                    {
                        "id": cid,
                        "name": c.get("name"),
                        "state": c.get("state") or c.get("status"),
                        "at": datetime.now(UTC).isoformat(),
                        "labels": c.get("labels") or c.get("label") or {},
                    }
                )
                note(
                    "path1",
                    f"NEW cluster name={c.get('name')} id={cid} state={c.get('state')}",
                )
                shot(page, f"path1_shadow_live_{i}")
                before_ids.add(cid)
                break

        run_id = page.evaluate("() => localStorage.getItem('oracle:current_run_id')")
        if run_id:
            run = api_json("GET", f"/runs/{run_id}")
            if run["status"] in ("completed", "failed"):
                terminal = True
                REPORT["timings_seconds"]["shadow_total"] = round(
                    time.perf_counter() - t_sh, 2
                )
                note(
                    "path1",
                    f"terminal status={run['status']} workflow={run.get('workflow_status')}",
                    seconds=REPORT["timings_seconds"]["shadow_total"],
                )
                break

    shot(page, "path1_shadow_done")
    if not terminal:
        bug("critical", "shadow_did_not_finish", "No terminal status in ~25m")

    time.sleep(20)
    after = list_ccloud_clusters()
    if appeared:
        cid = appeared.get("id") or appeared.get("cluster_id")
        still = [c for c in after if (c.get("id") or c.get("cluster_id")) == cid]
        if still:
            state = still[0].get("state") or still[0].get("status")
            note("path1", f"cluster still listed state={state}")
            if str(state).lower() not in {"deleted", "destroying", "destroyed"}:
                bug("critical", "cluster_leak", f"Cluster {cid} still active ({state})")
        else:
            note("path1", "cluster gone from Cloud API (torn down)")

    run_id = page.evaluate("() => localStorage.getItem('oracle:current_run_id')")
    if not run_id:
        return
    for path, label in [
        (f"/runs/{run_id}/grade", "grade"),
        (f"/runs/{run_id}/memory", "memory"),
        (f"/runs/{run_id}/execution-result", "execution"),
        (f"/runs/{run_id}/shadow-cluster", "shadow"),
    ]:
        try:
            data = api_json("GET", path)
            note("path1", f"{label} ok", id=str(data.get("id")))
            REPORT.setdefault("path1_artifacts", {})[label] = {
                k: data.get(k)
                for k in list(data.keys())[:12]
            }
        except Exception as exc:  # noqa: BLE001
            bug("high", f"missing_{label}", str(exc))

    page.goto(f"{WEB}/dashboard/memory")
    page.wait_for_load_state("networkidle")
    shot(page, "path1_memory_browser")

    # Closed loop second prediction
    page.goto(f"{WEB}/dashboard/migrations/current")
    page.evaluate("() => localStorage.removeItem('oracle:current_run_id')")
    page.reload()
    page.wait_for_load_state("networkidle")
    page.locator("#owner-identity-sidebar").fill("judge-demo")
    page.locator("textarea").first.fill(
        "ALTER TABLE customers ADD COLUMN loyalty_tier STRING NOT NULL DEFAULT 'standard';"
    )
    page.get_by_role("button", name="Create run").click()
    page.wait_for_selector("text=Schema discovery", timeout=60_000)
    page.locator("#database-url").fill(ro_url)
    page.get_by_role("button", name="Discover schema").click()
    page.wait_for_selector("text=customers", timeout=180_000)
    t2 = time.perf_counter()
    page.get_by_role("button", name="Run prediction").click()
    page.wait_for_selector("text=Assessment", timeout=420_000)
    REPORT["timings_seconds"]["predict_second"] = round(time.perf_counter() - t2, 2)
    shot(page, "path1_second_predict")
    body2 = page.inner_text("body")
    if "Retrieved" in body2 or "similarity" in body2.lower():
        note("path1", "closed-loop retrieval visible on second predict")
    elif "empty" in body2.lower() or "never attempted" in body2.lower():
        bug(
            "critical",
            "closed_loop_retrieval_miss",
            "Second prediction did not retrieve first memory",
        )
    else:
        note("path1", "inspect second predict screenshot for retrieval ranking")


def path3_failures(page) -> None:
    set_owner(page, "judge-demo")
    page.goto(f"{WEB}/dashboard/migrations/current")
    page.evaluate("() => localStorage.removeItem('oracle:current_run_id')")
    page.reload()
    page.locator("#owner-identity-sidebar").fill("judge-demo")
    page.locator("textarea").first.fill("NOT VALID SQL ;;;@@@")
    page.get_by_role("button", name="Create run").click()
    try:
        page.wait_for_selector("text=Schema discovery", timeout=30_000)
        page.get_by_role("button", name="Run prediction").click()
        time.sleep(8)
        shot(page, "path3_invalid_sql_predict")
        note("path3", "invalid SQL predict attempted")
    except PlaywrightTimeout:
        shot(page, "path3_invalid_sql_create")
        note("path3", "invalid SQL may have failed at create")

    page.evaluate("() => localStorage.removeItem('oracle:current_run_id')")
    page.reload()
    page.locator("#owner-identity-sidebar").fill("judge-demo")
    page.locator("textarea").first.fill(
        "ALTER TABLE customers ADD COLUMN x INT;"
    )
    page.get_by_role("button", name="Create run").click()
    page.wait_for_selector("text=Schema discovery", timeout=60_000)
    page.locator("#connection-secret-arn").fill(
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:does-not-exist"
    )
    page.get_by_role("button", name="Discover schema").click()
    time.sleep(10)
    shot(page, "path3_bad_arn")
    text = page.inner_text("body")
    if any(x in text.lower() for x in ["secret", "unable", "bad connection", "422", "load"]):
        note("path3", "bad ARN error surfaced")
    else:
        bug("high", "bad_arn_unclear", "Bad ARN without clear error")

    try:
        fake = api_json(
            "POST", "/runs/debug/fake-migration?owner_identity=judge-demo"
        )
        pred = api_json("POST", f"/runs/{fake['id']}/predict")
        if pred.get("status") == "awaiting_approval":
            rationale = None
            if pred.get("policy_decision") == "block":
                rationale = "accept recommended path test"
            done = api_json(
                "POST",
                f"/runs/{fake['id']}/approve",
                {
                    "decision": "accept_recommended",
                    "approver_identity": "judge-demo",
                    "override_rationale": rationale,
                    "start_workflow": False,
                },
            )
            if done["status"] == "completed":
                note("path3", "accept_recommended -> completed, no shadow required")
            else:
                bug(
                    "high",
                    "accept_recommended_state",
                    f"status={done['status']} wf={done.get('workflow_status')}",
                )
    except Exception as exc:  # noqa: BLE001
        bug("medium", "accept_recommended_fail", str(exc))


def main() -> None:
    print("API", API, "WEB", WEB)
    only = (os.environ.get("JUDGE_ONLY") or "").strip().lower()
    health = api_json("GET", "/health")
    note(
        "setup",
        "health",
        sfn_ready=health.get("integrations", {}).get("sfn_ready"),
        bedrock=health.get("integrations", {}).get("bedrock_configured"),
        shadow=health.get("integrations", {}).get("shadow_provider"),
        database=health.get("database"),
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(60_000)
        if only in ("", "all", "path4"):
            path4_empty_and_honesty(page)
        if only in ("", "all", "path3"):
            path3_failures(page)
        if only in ("", "all", "path1"):
            path1_happy(page)
        browser.close()
    REPORT["finished_at"] = datetime.now(UTC).isoformat()
    (OUT / "report.json").write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
    print("Wrote", OUT / "report.json")


if __name__ == "__main__":
    main()
