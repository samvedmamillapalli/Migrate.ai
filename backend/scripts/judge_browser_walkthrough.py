"""Adversarial browser walkthrough of the Next.js Migration Oracle console.

Drives Chromium via Playwright against http://localhost:3000 with the live
FastAPI backend. Records wall-clock stage timings, screenshots, and CockroachDB
Cloud cluster presence via the Cloud REST API (console-equivalent evidence when
interactive Cloud console login is unavailable).

Usage (API + Next already running):
  python backend/scripts/judge_browser_walkthrough.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

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


async def api_json(method: str, path: str, body: dict | None = None) -> Any:
    import urllib.request

    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else None


async def list_ccloud_clusters() -> list[dict[str, Any]]:
    """List clusters via CockroachDB Cloud REST — evidence without console UI login."""
    secret = os.environ.get("CCLOUD_API_SECRET")
    if not secret:
        return []
    import urllib.request

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
    if isinstance(clusters, dict):
        clusters = list(clusters.values())
    return clusters if isinstance(clusters, list) else []


async def shot(page, name: str) -> Path:
    path = OUT / f"{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    return path


async def set_owner(page, identity: str = "judge-demo") -> None:
    await page.goto(f"{WEB}/dashboard/settings")
    await page.wait_for_load_state("networkidle")
    field = page.locator("#owner-identity")
    await field.fill(identity)
    await shot(page, "settings_owner")


async def path4_empty_and_honesty(page) -> None:
    """Cold-start pages + honesty audit (no fabricated assertions)."""
    for route, name in [
        ("/dashboard", "overview"),
        ("/dashboard/migrations/history", "history"),
        ("/dashboard/memory", "memory"),
        ("/dashboard/settings", "settings"),
        ("/dashboard/migrations/current", "current_empty"),
        ("/", "landing"),
    ]:
        t0 = time.perf_counter()
        await page.goto(f"{WEB}{route}")
        try:
            await page.wait_for_load_state("networkidle", timeout=30_000)
        except PlaywrightTimeout:
            bug("medium", f"slow_or_stuck_{name}", f"{route} did not reach networkidle")
        await shot(page, f"path4_{name}")
        body = await page.inner_text("body")
        if "operator@migrationoracle.dev" in body:
            bug("high", "fake_sidebar_user", "Fake operator email still visible", fixed=False)
        if "Coming soon" in body or "coming soon" in body:
            bug("high", "coming_soon_visible", f"{route} still shows coming soon")
        if route == "/" and ("/docs" in (await page.content()) or "Sign In" in body):
            # Check links
            docs = page.locator('a[href="/docs"]')
            if await docs.count():
                bug("high", "broken_docs_link", "Landing still links to /docs")
            if await page.locator('a[href="/sign-in"]').count():
                bug("medium", "sign_in_cta", "Landing still has Sign In CTA")
        note("path4", f"rendered {route}", seconds=round(time.perf_counter() - t0, 2))

    # Memory corpus distinction
    await page.goto(f"{WEB}/dashboard/memory")
    await page.wait_for_load_state("networkidle")
    text = await page.inner_text("body")
    if "Open-source corpus" in text or "not a graded run" in text.lower():
        note("path4", "corpus badge present")
    elif "No memories" in text or "0 memories" in text or "empty" in text.lower():
        note("path4", "memory empty/honest state")
    else:
        # May have memories without badge if none are corpus — check API
        mem = await api_json("GET", "/memories?limit=5")
        corpus = [
            i
            for i in (mem.get("items") or [])
            if i.get("not_a_graded_run")
        ]
        if corpus and "Open-source corpus" not in text:
            bug(
                "high",
                "corpus_not_badged",
                "API has not_a_graded_run memories but UI does not badge them",
            )


async def path1_happy(page) -> None:
    ro_url = (ROOT / ".judge_ro_database_url").read_text(encoding="utf-8").strip()
    if not ro_url:
        REPORT["could_not_test"].append("PATH1: missing .judge_ro_database_url")
        return

    migration_sql = (
        "ALTER TABLE customers ADD COLUMN status STRING NOT NULL DEFAULT 'active';"
    )

    await set_owner(page, "judge-demo")
    await page.goto(f"{WEB}/dashboard/migrations/current")
    await page.wait_for_load_state("networkidle")

    # Clear prior current run by creating fresh SQL
    # If a run is already loaded, we still create a new one via empty state —
    # navigate with cleared localStorage.
    await page.evaluate("() => localStorage.removeItem('oracle:current_run_id')")
    await page.reload()
    await page.wait_for_load_state("networkidle")
    await shot(page, "path1_empty")

    # Owner may need re-set after clear? owner is separate key.
    await page.locator("#owner-identity").fill("judge-demo")

    textarea = page.locator("textarea").first
    await textarea.fill(migration_sql)
    t_create = time.perf_counter()
    await page.get_by_role("button", name="Create run").click()
    await page.wait_for_selector("text=Schema discovery", timeout=60_000)
    REPORT["timings_seconds"]["create_run"] = round(time.perf_counter() - t_create, 2)
    await shot(page, "path1_created")
    note("path1", "created run", seconds=REPORT["timings_seconds"]["create_run"])

    # Discover
    await page.locator("#database-url").fill(ro_url)
    t_disc = time.perf_counter()
    await page.get_by_role("button", name="Discover schema").click()
    try:
        await page.wait_for_selector("text=customers", timeout=120_000)
        REPORT["timings_seconds"]["discover"] = round(time.perf_counter() - t_disc, 2)
        note("path1", "discover succeeded", seconds=REPORT["timings_seconds"]["discover"])
    except PlaywrightTimeout:
        await shot(page, "path1_discover_fail")
        err = await page.locator("text=Discovery").all_inner_texts()
        bug("critical", "discover_failed", f"No customers table after discover: {err}")
        return
    await shot(page, "path1_discovered")

    # Predict
    t_pred = time.perf_counter()
    await page.get_by_role("button", name="Run prediction").click()
    try:
        await page.wait_for_selector("text=Assessment", timeout=300_000)
        REPORT["timings_seconds"]["predict"] = round(time.perf_counter() - t_pred, 2)
        note("path1", "predict done", seconds=REPORT["timings_seconds"]["predict"])
    except PlaywrightTimeout:
        await shot(page, "path1_predict_fail")
        bug("critical", "predict_timeout", "Prediction did not produce Assessment")
        return
    await shot(page, "path1_predicted")

    body = await page.inner_text("body")
    for needle in ["Retrieval transparency", "Distributed Vector Indexing", "Proceed"]:
        if needle not in body:
            bug("high", f"missing_{needle.replace(' ', '_')}", f"After predict, missing: {needle}")

    # Approve proceed
    t_appr = time.perf_counter()
    await page.get_by_role("button", name="Proceed", exact=True).click()
    try:
        await page.wait_for_selector("text=Shadow test", timeout=60_000)
        REPORT["timings_seconds"]["approve"] = round(time.perf_counter() - t_appr, 2)
    except PlaywrightTimeout:
        await shot(page, "path1_approve_fail")
        bug("critical", "approve_failed", "Shadow test section not shown after Proceed")
        return
    await shot(page, "path1_approved")

    # Clusters before
    before = await list_ccloud_clusters()
    before_ids = {c.get("id") or c.get("cluster_id") for c in before}
    note("path1", f"ccloud clusters before start: {len(before)}")

    # Start shadow
    t_sh = time.perf_counter()
    await page.get_by_role("button", name="Start shadow test").click()
    await shot(page, "path1_shadow_starting")

    # Poll UI + ccloud until terminal
    terminal = False
    appeared = None
    for i in range(120):  # up to ~20 min at 10s
        await asyncio.sleep(10)
        clusters = await list_ccloud_clusters()
        tagged = [
            c
            for c in clusters
            if "migration-oracle" in json.dumps(c).lower()
            or (c.get("name") or "").startswith("migration-oracle")
            or (c.get("id") not in before_ids and c.get("state") not in (None,))
        ]
        # Prefer newly appeared
        for c in clusters:
            cid = c.get("id") or c.get("cluster_id")
            name = c.get("name") or ""
            if cid and cid not in before_ids:
                appeared = c
                REPORT["clusters_seen"].append(
                    {
                        "id": cid,
                        "name": name,
                        "state": c.get("state") or c.get("status"),
                        "at": datetime.now(UTC).isoformat(),
                        "raw_keys": list(c.keys())[:20],
                    }
                )
                note("path1", f"NEW cluster appeared: {name} id={cid} state={c.get('state')}")
                await shot(page, f"path1_shadow_live_{i}")
                break

        status_text = await page.inner_text("body")
        if "Completed" in status_text or "Outcome" in status_text:
            if "failed" in status_text.lower() and "Completed" not in status_text:
                pass
            # Check run status via API from localStorage
            run_id = await page.evaluate(
                "() => localStorage.getItem('oracle:current_run_id')"
            )
            if run_id:
                run = await api_json("GET", f"/runs/{run_id}")
                if run["status"] in ("completed", "failed"):
                    terminal = True
                    REPORT["timings_seconds"]["shadow_total"] = round(
                        time.perf_counter() - t_sh, 2
                    )
                    note(
                        "path1",
                        f"run terminal status={run['status']} workflow={run.get('workflow_status')}",
                        seconds=REPORT["timings_seconds"]["shadow_total"],
                    )
                    break

    await shot(page, "path1_shadow_done")
    if not terminal:
        bug("critical", "shadow_did_not_finish", "Shadow did not reach terminal in ~20m")

    # Confirm destroyed
    await asyncio.sleep(15)
    after = await list_ccloud_clusters()
    if appeared:
        cid = appeared.get("id") or appeared.get("cluster_id")
        still = [c for c in after if (c.get("id") or c.get("cluster_id")) == cid]
        if still:
            state = still[0].get("state") or still[0].get("status")
            note("path1", f"cluster still listed after finish state={state}")
            if str(state).lower() not in {"deleted", "destroying", "destroyed"}:
                bug(
                    "critical",
                    "cluster_leak",
                    f"Cluster {cid} still present in Cloud API after run finished (state={state})",
                )
        else:
            note("path1", "cluster no longer listed in Cloud API (torn down)")

    # Outcome / memory
    run_id = await page.evaluate("() => localStorage.getItem('oracle:current_run_id')")
    if run_id:
        for path, label in [
            (f"/runs/{run_id}/grade", "grade"),
            (f"/runs/{run_id}/memory", "memory"),
            (f"/runs/{run_id}/execution-result", "execution"),
            (f"/runs/{run_id}/shadow-cluster", "shadow"),
        ]:
            try:
                data = await api_json("GET", path)
                note("path1", f"{label} present", id=str(data.get("id")))
            except Exception as exc:  # noqa: BLE001
                bug("high", f"missing_{label}", str(exc))

        await page.goto(f"{WEB}/dashboard/memory")
        await page.wait_for_load_state("networkidle")
        await shot(page, "path1_memory_browser")

        # Closed loop: second similar migration
        await page.goto(f"{WEB}/dashboard/migrations/current")
        await page.evaluate("() => localStorage.removeItem('oracle:current_run_id')")
        await page.reload()
        await page.wait_for_load_state("networkidle")
        await page.locator("#owner-identity").fill("judge-demo")
        sql2 = (
            "ALTER TABLE customers ADD COLUMN loyalty_tier STRING NOT NULL DEFAULT 'standard';"
        )
        await page.locator("textarea").first.fill(sql2)
        await page.get_by_role("button", name="Create run").click()
        await page.wait_for_selector("text=Schema discovery", timeout=60_000)
        await page.locator("#database-url").fill(ro_url)
        await page.get_by_role("button", name="Discover schema").click()
        await page.wait_for_selector("text=customers", timeout=120_000)
        t_pred2 = time.perf_counter()
        await page.get_by_role("button", name="Run prediction").click()
        await page.wait_for_selector("text=Assessment", timeout=300_000)
        REPORT["timings_seconds"]["predict_second"] = round(
            time.perf_counter() - t_pred2, 2
        )
        await shot(page, "path1_second_predict")
        body2 = await page.inner_text("body")
        if "Retrieved" in body2 or "similarity" in body2.lower() or "hits" in body2.lower():
            note("path1", "second prediction shows retrieval hits")
        else:
            if "never attempted" in body2.lower() or "empty" in body2.lower():
                bug(
                    "critical",
                    "closed_loop_retrieval_miss",
                    "Second prediction did not retrieve the first run's memory",
                )
            else:
                note("path1", "retrieval section present; inspect screenshot for ranked memories")


async def path3_failures(page) -> None:
    """Sample failure modes via UI + API."""
    await set_owner(page, "judge-demo")

    # Invalid SQL via create
    await page.goto(f"{WEB}/dashboard/migrations/current")
    await page.evaluate("() => localStorage.removeItem('oracle:current_run_id')")
    await page.reload()
    await page.locator("#owner-identity").fill("judge-demo")
    await page.locator("textarea").first.fill("NOT VALID SQL ;;;@@@")
    await page.get_by_role("button", name="Create run").click()
    # Create may succeed (SQL stored raw); predict should fail or policy fail
    try:
        await page.wait_for_selector("text=Schema discovery", timeout=30_000)
        await page.get_by_role("button", name="Run prediction").click()
        await asyncio.sleep(5)
        await shot(page, "path3_invalid_sql_predict")
        note("path3", "invalid SQL predict attempted")
    except PlaywrightTimeout:
        note("path3", "invalid SQL create may have failed visibly")
        await shot(page, "path3_invalid_sql_create")

    # Bad ARN discover
    await page.evaluate("() => localStorage.removeItem('oracle:current_run_id')")
    await page.reload()
    await page.locator("#owner-identity").fill("judge-demo")
    await page.locator("textarea").first.fill(
        "ALTER TABLE customers ADD COLUMN x INT;"
    )
    await page.get_by_role("button", name="Create run").click()
    await page.wait_for_selector("text=Schema discovery", timeout=60_000)
    await page.locator("#connection-secret-arn").fill(
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:does-not-exist"
    )
    await page.get_by_role("button", name="Discover schema").click()
    await asyncio.sleep(8)
    await shot(page, "path3_bad_arn")
    text = await page.inner_text("body")
    if "Bad connection" in text or "Unable to load" in text or "422" in text or "secret" in text.lower():
        note("path3", "bad ARN surfaced an error")
    else:
        bug("high", "bad_arn_unclear", "Bad ARN did not show a clear discover error")

    # accept_recommended via API for speed (locked decision check)
    try:
        run = await api_json(
            "POST",
            "/runs",
            {
                "migration_sql": "ALTER TABLE customers ADD COLUMN note STRING;",
                "owner_identity": "judge-demo",
            },
        )
        # skip full predict if expensive — use fake for accept_recommended path
        fake = await api_json(
            "POST", f"/runs/debug/fake-migration?owner_identity=judge-demo", None
        )
        pred = await api_json("POST", f"/runs/{fake['id']}/predict", None)
        if pred.get("status") == "awaiting_approval":
            done = await api_json(
                "POST",
                f"/runs/{fake['id']}/approve",
                {
                    "decision": "accept_recommended",
                    "approver_identity": "judge-demo",
                    "start_workflow": False,
                },
            )
            if done["status"] == "completed" and done.get("workflow_status") in (
                "not_started",
                None,
            ):
                note("path3", "accept_recommended completed without shadow")
            else:
                bug(
                    "high",
                    "accept_recommended_wrong_state",
                    f"status={done['status']} workflow={done.get('workflow_status')}",
                )
    except Exception as exc:  # noqa: BLE001
        bug("medium", "accept_recommended_api_fail", str(exc))


async def main() -> None:
    print("API", API, "WEB", WEB)
    health = await api_json("GET", "/health")
    note(
        "setup",
        "health",
        sfn_ready=health.get("integrations", {}).get("sfn_ready"),
        bedrock=health.get("integrations", {}).get("bedrock_configured"),
        shadow=health.get("integrations", {}).get("shadow_provider"),
    )
    if not health.get("integrations", {}).get("sfn_ready"):
        bug("critical", "sfn_not_ready", "MIGRATION_WORKFLOW_ARN / bucket not ready")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        page.set_default_timeout(60_000)

        await path4_empty_and_honesty(page)
        await path3_failures(page)
        await path1_happy(page)

        await browser.close()

    REPORT["finished_at"] = datetime.now(UTC).isoformat()
    out = OUT / "report.json"
    out.write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
    print("Wrote", out)


if __name__ == "__main__":
    asyncio.run(main())
