"""Pure-function pieces of the GitHub webhook pipeline —
docs/FUTURE_GITHUB_INTEGRATION_PLAN.md.

Covers: HMAC signature verification (the security boundary — a webhook
route must never trust an unverified payload), the migration-file glob
heuristic, and best-effort SQL extraction from `.sql` files and Alembic
`.py` files.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.core.exceptions import GithubWebhookError, ValidationError
from app.services.github_webhook_service import (
    extract_migration_sql,
    find_migration_file,
    verify_webhook_signature,
)

# --------------------------------------------------------------- signature


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_webhook_signature_accepts_valid_signature() -> None:
    body = b'{"action": "opened"}'
    secret = "test-secret"
    verify_webhook_signature(body, _sign(secret, body), secret)


def test_verify_webhook_signature_rejects_wrong_secret() -> None:
    body = b'{"action": "opened"}'
    with pytest.raises(GithubWebhookError):
        verify_webhook_signature(body, _sign("wrong-secret", body), "test-secret")


def test_verify_webhook_signature_rejects_tampered_body() -> None:
    secret = "test-secret"
    signature = _sign(secret, b'{"action": "opened"}')
    with pytest.raises(GithubWebhookError):
        verify_webhook_signature(b'{"action": "closed"}', signature, secret)


def test_verify_webhook_signature_rejects_missing_header() -> None:
    with pytest.raises(GithubWebhookError):
        verify_webhook_signature(b"{}", None, "test-secret")


def test_verify_webhook_signature_rejects_malformed_header() -> None:
    with pytest.raises(GithubWebhookError):
        verify_webhook_signature(b"{}", "not-a-sha256-header", "test-secret")


def test_verify_webhook_signature_rejects_unconfigured_secret() -> None:
    body = b"{}"
    with pytest.raises(GithubWebhookError):
        verify_webhook_signature(body, _sign("anything", body), "")


# ------------------------------------------------------------- glob match


def test_find_migration_file_matches_alembic_convention() -> None:
    paths = [
        "backend/alembic/versions/abc123_add_column.py",
        "backend/app/main.py",
        "README.md",
    ]
    matched = find_migration_file(paths, "backend/alembic/versions/*.py")
    assert matched == ["backend/alembic/versions/abc123_add_column.py"]


def test_find_migration_file_no_match_returns_empty() -> None:
    paths = ["backend/app/main.py", "README.md"]
    matched = find_migration_file(paths, "backend/alembic/versions/*.py")
    assert matched == []


def test_find_migration_file_matches_raw_sql_glob() -> None:
    paths = ["migrations/0007_add_index.sql", "app/models.py"]
    matched = find_migration_file(paths, "migrations/*.sql")
    assert matched == ["migrations/0007_add_index.sql"]


# --------------------------------------------------------- SQL extraction


def test_extract_migration_sql_from_sql_file_uses_raw_content() -> None:
    content = "ALTER TABLE users ADD COLUMN flag BOOL NOT NULL DEFAULT false;"
    assert extract_migration_sql(content, "migrations/0007.sql") == content


def test_extract_migration_sql_rejects_empty_sql_file() -> None:
    with pytest.raises(ValidationError):
        extract_migration_sql("   \n  ", "migrations/0007.sql")


def test_extract_migration_sql_from_alembic_triple_quoted_op_execute() -> None:
    content = '''
def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workspaces ADD COLUMN github_repo_full_name STRING;
        """
    )
'''
    extracted = extract_migration_sql(content, "backend/alembic/versions/xyz.py")
    assert "ALTER TABLE workspaces" in extracted


def test_extract_migration_sql_from_alembic_single_quoted_op_execute() -> None:
    content = (
        "def upgrade() -> None:\n"
        "    op.execute('ALTER TABLE t ADD COLUMN c INT;')\n"
    )
    extracted = extract_migration_sql(content, "backend/alembic/versions/xyz.py")
    assert extracted == "ALTER TABLE t ADD COLUMN c INT;"


def test_extract_migration_sql_picks_first_of_multiple_op_execute() -> None:
    content = (
        "def upgrade() -> None:\n"
        "    op.execute('ALTER TABLE t ADD COLUMN a INT;')\n"
        "    op.execute('ALTER TABLE t ADD COLUMN b INT;')\n"
    )
    extracted = extract_migration_sql(content, "backend/alembic/versions/xyz.py")
    assert extracted == "ALTER TABLE t ADD COLUMN a INT;"


def test_extract_migration_sql_raises_when_no_op_execute_found() -> None:
    content = (
        "def upgrade() -> None:\n"
        "    op.add_column('t', sa.Column('c', sa.Integer()))\n"
    )
    with pytest.raises(ValidationError):
        extract_migration_sql(content, "backend/alembic/versions/xyz.py")
