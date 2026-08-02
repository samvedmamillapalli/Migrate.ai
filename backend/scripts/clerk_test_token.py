#!/usr/bin/env python3
"""Mint a short-lived Clerk session JWT for the agent test account.

Lets an agent (or any non-interactive caller) exercise the authenticated API
without driving a browser sign-in. Uses the Clerk Backend API with
CLERK_SECRET_KEY from the repo-root .env — the same test user documented in
docs/TEST_ACCOUNT.md.

Clerk session tokens are deliberately short-lived (~60s), so mint and use in
one shot rather than caching the value.

Usage (from backend/):
  python scripts/clerk_test_token.py                 # print a JWT
  python scripts/clerk_test_token.py --check         # mint + call the API with it
  python scripts/clerk_test_token.py --api http://127.0.0.1:8003 --check
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

CLERK_API = "https://api.clerk.com/v1"
TEST_USER_EMAIL = "claude-agent+clerk_test@migration-oracle.dev"

# Clerk's edge/WAF returns 403 for urllib's default "Python-urllib/x.y"
# User-Agent. Any explicit UA is accepted — verified 2026-08-02 (same request
# succeeds with curl, which sends its own). Not optional.
_USER_AGENT = "migration-oracle-test-token/1.0"


def _load_secret_key() -> str:
    key = os.environ.get("CLERK_SECRET_KEY", "").strip()
    if key:
        return key
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("CLERK_SECRET_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("CLERK_SECRET_KEY not found in env or repo-root .env")


def _clerk(path: str, secret: str, payload: dict | None = None) -> object:
    req = urllib.request.Request(
        f"{CLERK_API}{path}",
        method="POST" if payload is not None else "GET",
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        },
        data=json.dumps(payload).encode() if payload is not None else None,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _find_test_user(secret: str) -> str:
    users = _clerk("/users?limit=100", secret)
    for user in users:  # type: ignore[union-attr]
        for email in user.get("email_addresses") or []:
            if email.get("email_address") == TEST_USER_EMAIL:
                return user["id"]
    raise SystemExit(
        f"Test user {TEST_USER_EMAIL} not found in this Clerk instance. "
        "See docs/TEST_ACCOUNT.md."
    )


def mint_token(secret: str) -> tuple[str, str]:
    """Return (jwt, user_id)."""
    user_id = _find_test_user(secret)
    session = _clerk("/sessions", secret, {"user_id": user_id})
    token = _clerk(f"/sessions/{session['id']}/tokens", secret, {})  # type: ignore[index]
    return token["jwt"], user_id  # type: ignore[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8003")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Also call the API with the token and report status codes.",
    )
    args = parser.parse_args()

    secret = _load_secret_key()
    jwt, user_id = mint_token(secret)

    if not args.check:
        print(jwt)
        return 0

    print(f"user_id: {user_id}")
    print(f"jwt    : {len(jwt)} chars (expires ~60s)")
    failures = 0
    for method, path, body in (
        ("GET", "/health", None),
        ("GET", "/memories/health", None),
        ("POST", "/memories/search",
         {"query": "add a column to a large table", "scope": "all", "limit": 2}),
        ("GET", "/runs?limit=1", None),
    ):
        req = urllib.request.Request(
            f"{args.api}{path}",
            method=method,
            headers={
                "Authorization": f"Bearer {jwt}",
                "Content-Type": "application/json",
            },
            data=json.dumps(body).encode() if body else None,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                print(f"  {resp.status}  {method} {path}")
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            failures += 1
            print(f"  {exc.code}  {method} {path}  <- {exc.read()[:160]!r}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  ERR  {method} {path}  <- {type(exc).__name__}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
