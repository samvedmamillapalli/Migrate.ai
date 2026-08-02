"""Thin wrapper around the ccloud CLI's audit log, for control-plane use only.

NEVER call this from a Lambda — there is no browser and no durable session
there. This is confined to the FastAPI backend process, the one persistent
process in this system where a human can complete ``ccloud auth login``
once. See docs/cockroach_hookup.md §4.

Best-effort like everything else that enriches a shadow run in this app:
raises typed errors the caller can catch and log, never silently swallows —
but the caller (the sync-workflow completion hook) is responsible for making
sure a fetch failure here can never fail the run itself.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_CCLOUD_CANDIDATES = [
    "ccloud",
    "ccloud.exe",
    str(Path(os.environ.get("APPDATA", "")) / "ccloud" / "ccloud.exe"),
]

_TIMEOUT_SECONDS = 30


class CCloudCliError(Exception):
    """Base for all ccloud CLI wrapper failures."""


class CCloudCliNotFoundError(CCloudCliError):
    """ccloud binary isn't installed / on PATH on this host."""


class CCloudCliNotLoggedInError(CCloudCliError):
    """ccloud is installed but ``ccloud auth login`` hasn't been completed here."""


class CCloudCliInvocationError(CCloudCliError):
    """ccloud ran but returned a non-zero exit or unparseable output."""


def find_ccloud_binary() -> str:
    for candidate in _CCLOUD_CANDIDATES:
        resolved = (
            shutil.which(candidate)
            if os.sep not in candidate
            else (candidate if Path(candidate).is_file() else None)
        )
        if resolved:
            return resolved
    raise CCloudCliNotFoundError(
        "ccloud CLI not found on PATH or at %APPDATA%\\ccloud\\ccloud.exe"
    )


def _normalize_events(raw: object) -> list[dict[str, Any]]:
    """ccloud's exact JSON shape for `audit list` isn't documented in
    --help; accept either a bare list or a {"events": [...]} / {"auditLogEvents":
    [...]} wrapper rather than assuming one."""
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    if isinstance(raw, dict):
        for key in ("events", "auditLogEvents", "audit_log_events", "items"):
            value = raw.get(key)
            if isinstance(value, list):
                return [e for e in value if isinstance(e, dict)]
    return []


def fetch_audit_events(
    *,
    starting_from: datetime,
    limit: int = 50,
    ccloud_binary: str | None = None,
) -> list[dict[str, Any]]:
    """Returns raw audit-log event dicts from ``ccloud audit list``.

    Raises CCloudCliNotFoundError / CCloudCliNotLoggedInError /
    CCloudCliInvocationError — never returns a partial/silent empty list on
    failure, so the caller can distinguish "checked, found nothing" from
    "couldn't check."
    """
    binary = ccloud_binary or find_ccloud_binary()
    ts = starting_from.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        proc = subprocess.run(
            [
                binary,
                "audit",
                "list",
                "--starting-from",
                ts,
                "--limit",
                str(limit),
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CCloudCliInvocationError(
            f"ccloud audit list failed to run: {type(exc).__name__}: {exc}"
        ) from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if "not logged in" in stderr.lower():
            raise CCloudCliNotLoggedInError(
                "ccloud CLI is not logged in on this host. Run `ccloud auth "
                "login` once, interactively, to enable audit-trail fetches."
            )
        raise CCloudCliInvocationError(
            f"ccloud audit list exited {proc.returncode}: {stderr or proc.stdout.strip()}"
        )

    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CCloudCliInvocationError(
            f"ccloud audit list returned non-JSON output: {proc.stdout[:500]!r}"
        ) from exc

    events = _normalize_events(parsed)
    logger.info("ccloud audit list served", extra={"count": len(events)})
    return events
