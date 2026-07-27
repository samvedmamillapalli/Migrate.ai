"""HMAC-signed session tokens (no external JWT dependency)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + pad)


def hash_password(password: str, *, secret: str) -> str:
    """Slow-ish keyed hash suitable for demo auth (stdlib only)."""
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        secret.encode("utf-8"),
        120_000,
    )
    return _b64encode(digest)


def verify_password(password: str, password_hash: str, *, secret: str) -> bool:
    expected = hash_password(password, secret=secret)
    return hmac.compare_digest(expected, password_hash)


def issue_token(
    *,
    owner_identity: str,
    secret: str,
    ttl_seconds: int = 60 * 60 * 24 * 7,
) -> str:
    payload = {
        "sub": owner_identity,
        "exp": int(time.time()) + int(ttl_seconds),
        "iat": int(time.time()),
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def verify_token(token: str, *, secret: str) -> dict[str, Any]:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Malformed token") from exc
    expected = _b64encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, sig):
        raise ValueError("Invalid token signature")
    payload = json.loads(_b64decode(body).decode("utf-8"))
    if int(payload.get("exp") or 0) < int(time.time()):
        raise ValueError("Token expired")
    sub = str(payload.get("sub") or "").strip()
    if not sub:
        raise ValueError("Token missing subject")
    return {"owner_identity": sub, "exp": int(payload["exp"])}
