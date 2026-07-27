from __future__ import annotations

import time

import pytest

from app.auth.tokens import (
    hash_password,
    issue_token,
    verify_password,
    verify_token,
)


def test_password_roundtrip() -> None:
    secret = "test-secret"
    digest = hash_password("hunter2!!", secret=secret)
    assert verify_password("hunter2!!", digest, secret=secret)
    assert not verify_password("wrong", digest, secret=secret)


def test_token_roundtrip() -> None:
    secret = "token-secret"
    token = issue_token(owner_identity="alice", secret=secret, ttl_seconds=60)
    payload = verify_token(token, secret=secret)
    assert payload["owner_identity"] == "alice"


def test_token_rejects_bad_signature() -> None:
    token = issue_token(owner_identity="alice", secret="a", ttl_seconds=60)
    with pytest.raises(ValueError):
        verify_token(token, secret="b")


def test_token_rejects_expired() -> None:
    secret = "s"
    token = issue_token(owner_identity="alice", secret=secret, ttl_seconds=60)
    # Tamper by re-signing an expired payload with the public helpers.
    import json

    from app.auth import tokens as tokens_mod

    payload = {"sub": "alice", "exp": int(time.time()) - 10, "iat": 1}
    body = tokens_mod._b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    import hashlib
    import hmac

    sig = tokens_mod._b64encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    with pytest.raises(ValueError, match="expired"):
        verify_token(f"{body}.{sig}", secret=secret)
