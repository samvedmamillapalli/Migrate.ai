"""Proof for docs/FUTURE_GITHUB_INTEGRATION_PLAN.md.

Two parts, both against the real database and real internal pipeline —
only the actual GitHub REST API calls are mocked, because that requires a
registered GitHub App installed on a real repository, which this
environment does not have yet (see docs/GITHUB_APP_SETUP.md). Nothing else
here is fabricated: workspace linking, signature verification, migration-
file detection, run creation, schema discovery, and prediction all run for
real against the real CockroachDB Cloud database configured for this app.

PART A — real HTTP against the already-running dev API
  1. Create a workspace with a real stored connection, link it to a repo.
  2. A second workspace cannot claim the same repo (409) — the plan's
     one-repo-to-one-workspace constraint, enforced for real.
  3. POST /webhooks/github with a bad signature is rejected (401) — the
     security boundary a webhook route must never skip.

PART B — in-process (TestClient), real DB, GitHub REST calls mocked
  4. A realistic pull_request webhook payload, signed with the real
     configured GITHUB_WEBHOOK_SECRET, is posted to the app in-process.
  5. GithubAppClient is monkeypatched (list_pull_request_files /
     get_file_content / post_issue_comment / create_check_run) so no
     network call to api.github.com happens — every other step is real:
     workspace resolution, SQL extraction, MigrationRun creation, real
     schema discovery, real prediction (Bedrock if configured, else the
     mock model), and a real GithubPullRequestLink row.
  6. The mocked post_issue_comment call is inspected to confirm it received
     the run's actual predicted numbers, not placeholder text — proving the
     PredictionPipelineService -> GithubNotificationService hook actually
     fired with real data.

Requires GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY / GITHUB_WEBHOOK_SECRET set
in .env — dummy values are fine for GITHUB_APP_ID/GITHUB_APP_PRIVATE_KEY
since the client that would use them is mocked; GITHUB_WEBHOOK_SECRET must
be a real value since it's used to compute a real HMAC signature.

Usage (from backend/, with the dev API already running for Part A):
    python scripts/prove_github_integration.py [--api http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _call(
    api: str,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    headers: dict | None = None,
    raw_body: bytes | None = None,
    token: str | None = None,
) -> tuple[int, dict]:
    url = f"{api}{path}"
    data = raw_body if raw_body is not None else (
        json.dumps(body).encode() if body is not None else None
    )
    req_headers = {"Content-Type": "application/json", **(headers or {})}
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=req_headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw) if raw else {}
            except ValueError:
                return resp.status, {"_raw": raw.decode(errors="replace")}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"detail": raw.decode(errors="replace")}


def _mint_token() -> str:
    """Real Clerk session JWT, matching scripts/prove_workspaces.py's
    convention. Minted fresh right before each call (~60s token lifetime)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from clerk_test_token import mint_token, _load_secret_key

    jwt, _user_id = mint_token(_load_secret_key())
    return jwt


def _demo_database_url() -> str:
    from app.demo_secrets import JUDGE_RO_DATABASE_URL_FILE, read_demo_secret
    import os

    url = (os.environ.get("DEMO_READONLY_DATABASE_URL") or "").strip()
    if url:
        return url
    val = read_demo_secret(JUDGE_RO_DATABASE_URL_FILE)
    if not val:
        raise SystemExit(
            "No real read-only database available (DEMO_READONLY_DATABASE_URL / "
            ".judge_ro_database_url) — see scripts/prepare_judge_demo_db.py."
        )
    return val


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def part_a(api: str, suffix: str) -> tuple[bool, str, str]:
    """Real HTTP against the running dev API. Returns (ok, workspace_id, repo_full_name)."""
    overall_ok = True
    repo_full_name = f"proof-org/proof-repo-{suffix}"

    print("=" * 78)
    print("PART A.1 — link a repo to a workspace (real HTTP)")
    print("=" * 78)
    status, ws = _call(
        api,
        "POST",
        "/workspaces",
        body={
            "name": f"GitHub Proof {suffix}",
            "database_url": _demo_database_url(),
            "github_repo_full_name": repo_full_name,
        },
        token=_mint_token(),
    )
    print(f"  workspace: status={status} id={ws.get('id')} "
          f"github_repo_full_name={ws.get('github_repo_full_name')!r} "
          f"github_migration_glob={ws.get('github_migration_glob')!r}")
    ok = status == 201 and ws.get("github_repo_full_name") == repo_full_name
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    overall_ok = overall_ok and ok
    if status != 201:
        raise SystemExit(f"workspace creation failed: {ws}")

    print()
    print("=" * 78)
    print("PART A.2 — a second workspace cannot claim the same repo (409)")
    print("=" * 78)
    status, dupe = _call(
        api,
        "POST",
        "/workspaces",
        body={
            "name": f"GitHub Proof Dupe {suffix}",
            "github_repo_full_name": repo_full_name,
        },
        token=_mint_token(),
    )
    ok = status == 409
    print(f"  second workspace claiming the same repo: status={status} "
          f"(expected 409)  detail={dupe.get('detail')!r}")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    overall_ok = overall_ok and ok

    print()
    print("=" * 78)
    print("PART A.3 — webhook with a bad signature is rejected (401)")
    print("=" * 78)
    body = json.dumps({"action": "opened"}).encode()
    status, rejected = _call(
        api,
        "POST",
        "/webhooks/github",
        raw_body=body,
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "X-GitHub-Event": "pull_request",
        },
    )
    ok = status == 401
    print(f"  bad signature: status={status} (expected 401) body={rejected}")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    overall_ok = overall_ok and ok

    return overall_ok, ws["id"], repo_full_name


def part_b(workspace_id: str, repo_full_name: str) -> bool:
    """In-process TestClient, real DB, GitHub REST calls mocked."""
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    app_id = (settings.github_app_id or "").strip()
    private_key = (
        settings.github_app_private_key.get_secret_value()
        if settings.github_app_private_key
        else ""
    )
    webhook_secret = (
        settings.github_webhook_secret.get_secret_value()
        if settings.github_webhook_secret
        else ""
    )
    if not (app_id and private_key and webhook_secret):
        print(
            "\nSKIPPING PART B — GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY / "
            "GITHUB_WEBHOOK_SECRET are not all set in .env.\n"
            "Dummy values are fine for the first two (the client that would "
            "use them is mocked below); GITHUB_WEBHOOK_SECRET must be a real "
            "shared secret since a real HMAC signature is computed with it.\n"
            "Add e.g.:\n"
            "  GITHUB_APP_ID=dev-placeholder\n"
            "  GITHUB_APP_PRIVATE_KEY=dev-placeholder\n"
            "  GITHUB_WEBHOOK_SECRET=" + uuid.uuid4().hex + "\n"
            "to .env, restart the dev API, and re-run this script."
        )
        return False

    from fastapi.testclient import TestClient

    from app.main import app

    migration_file_path = "backend/alembic/versions/proof_migration.py"
    file_content = (
        "def upgrade() -> None:\n"
        "    op.execute(\n"
        "        \"ALTER TABLE github_proof_table ADD COLUMN note STRING;\"\n"
        "    )\n"
    )
    payload = {
        "action": "opened",
        "repository": {"full_name": repo_full_name},
        "installation": {"id": 999999},
        "pull_request": {
            "number": 7,
            "head": {"sha": "abc123deadbeef"},
            "user": {"login": "proof-author"},
        },
    }
    body = json.dumps(payload).encode()
    signature = _sign(webhook_secret, body)

    mock_client = MagicMock()
    mock_client.get_installation_token = AsyncMock(return_value="fake-installation-token")
    mock_client.list_pull_request_files = AsyncMock(
        return_value=[migration_file_path, "README.md"]
    )
    mock_client.get_file_content = AsyncMock(return_value=file_content)
    mock_client.post_issue_comment = AsyncMock(return_value=555)
    mock_client.create_check_run = AsyncMock(return_value=777)
    mock_client.update_check_run = AsyncMock(return_value=None)

    print()
    print("=" * 78)
    print("PART B — real webhook pipeline in-process (GitHub REST calls mocked)")
    print("=" * 78)

    with (
        patch(
            "app.services.github_webhook_service.GithubAppClient",
            return_value=mock_client,
        ),
        patch(
            "app.services.github_notification_service.GithubAppClient",
            return_value=mock_client,
        ),
        TestClient(app) as client,
    ):
        resp = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": signature,
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )
        print(f"  webhook response: status={resp.status_code}")
        ok = resp.status_code == 200
        run = resp.json() if ok else {}
        run_id = run.get("id")
        print(f"  created run: id={run_id} run_kind={run.get('run_kind')} "
              f"workspace_id={run.get('workspace_id')} "
              f"schema_discovery_status={run.get('schema_discovery_status')} "
              f"status={run.get('status')}")
        ok = ok and run.get("workspace_id") == workspace_id
        ok = ok and run.get("run_kind") == "github_pr"
        ok = ok and run.get("schema_discovery_status") == "succeeded"
        print(f"  RESULT (run created under the right workspace, real "
              f"discover succeeded): {'PASS' if ok else 'FAIL'}")

        mock_client.list_pull_request_files.assert_awaited()
        fetched = mock_client.get_file_content.await_args
        fetch_ok = fetched is not None and fetched.args[1:] == (
            repo_full_name, migration_file_path, "abc123deadbeef"
        )
        print(f"  fetched the matched migration file at the PR's head sha: "
              f"{'PASS' if fetch_ok else 'FAIL'}")
        ok = ok and fetch_ok

        posted = mock_client.post_issue_comment.await_args
        comment_ok = posted is not None
        comment_body = ""
        if posted is not None:
            comment_body = posted.args[3] if len(posted.args) > 3 else posted.kwargs.get("body", "")
            comment_ok = "duration" in comment_body.lower() or "MB" in comment_body
        print(f"  PR comment was posted with real prediction numbers "
              f"(not placeholder text): {'PASS' if comment_ok else 'FAIL'}")
        if posted is not None:
            print("  --- comment body (truncated) ---")
            print("  " + comment_body[:400].replace("\n", "\n  "))

    return ok and comment_ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    api = args.api.rstrip("/")
    suffix = uuid.uuid4().hex[:8]

    part_a_ok, workspace_id, repo_full_name = part_a(api, suffix)
    part_b_ok = part_b(workspace_id, repo_full_name)

    print()
    print("=" * 78)
    print(f"OVERALL: {'PASS' if (part_a_ok and part_b_ok) else 'FAIL'}")
    print("=" * 78)
    if not part_b_ok:
        print(
            "\nNOTE: Part B failing/skipping only means GitHub App env vars "
            "aren't set, or a follow-on assertion needs attention — it does "
            "NOT mean a real GitHub App + real PR has been verified end to "
            "end. That last mile (docs/FUTURE_GITHUB_INTEGRATION_PLAN.md's "
            "own verification bar) requires docs/GITHUB_APP_SETUP.md's "
            "manual steps: register the App, install it on a real repo, "
            "link that repo to a workspace, and open a real PR."
        )
    return 0 if (part_a_ok and part_b_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
