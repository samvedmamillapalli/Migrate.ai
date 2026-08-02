"""Prepare a read-only discoverable customer DB with real row counts.

Creates (idempotent):
  - role ``judge_ro`` (SELECT-only)
  - table ``public.customers`` with ~5000 rows
  - grants SELECT to judge_ro

Prints a RO database URL (password redacted in logs; full URL only to stdout
as JUDGE_RO_DATABASE_URL=...) for discovery tests. Does not print admin URL.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urlunparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.demo_secrets import (  # noqa: E402
    JUDGE_RO_DATABASE_URL_FILE,
    JUDGE_RO_PASSWORD_FILE,
    demo_secret_path,
    demo_secret_write_path,
)

# Written under .local_secrets/ (gitignored) rather than the repo root.
PASSWORD_FILE = demo_secret_path(JUDGE_RO_PASSWORD_FILE) or demo_secret_write_path(
    JUDGE_RO_PASSWORD_FILE
)
TABLE = "customers"
ROLE = "judge_ro"
ROW_TARGET = 5000


def _admin_url() -> str:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise SystemExit("DATABASE_URL missing")
    return raw


def _to_psycopg(url: str) -> str:
    """Normalize to the SQLAlchemy Cockroach dialect used by the app."""
    if url.startswith("cockroachdb+psycopg://"):
        return url
    if url.startswith("postgresql+psycopg://"):
        return "cockroachdb+psycopg://" + url.split("://", 1)[1]
    if url.startswith("postgresql://"):
        return "cockroachdb+psycopg://" + url.split("://", 1)[1]
    if url.startswith("postgres://"):
        return "cockroachdb+psycopg://" + url.split("://", 1)[1]
    return url


def _build_ro_url(admin: str, password: str) -> str:
    parsed = urlparse(admin)
    # Replace user/password; keep host/path/query
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    userinfo = f"{ROLE}:{quote_plus(password)}"
    netloc = f"{userinfo}@{host}{port}"
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def main() -> None:
    admin = _admin_url()
    engine = create_engine(_to_psycopg(admin), pool_pre_ping=True)

    if PASSWORD_FILE.exists():
        password = PASSWORD_FILE.read_text(encoding="utf-8").strip()
    else:
        password = secrets.token_urlsafe(18)
        PASSWORD_FILE.write_text(password + "\n", encoding="utf-8")

    with engine.begin() as conn:
        # Role / user (Cockroach SHOW ROLES uses ``username``)
        exists = conn.execute(
            text("SELECT 1 FROM [SHOW ROLES] WHERE username = :r"),
            {"r": ROLE},
        ).scalar()
        if not exists:
            conn.execute(text(f"CREATE USER {ROLE} WITH PASSWORD :pw"), {"pw": password})
        else:
            conn.execute(text(f"ALTER USER {ROLE} WITH PASSWORD :pw"), {"pw": password})

        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                  email STRING NOT NULL,
                  region STRING NOT NULL DEFAULT 'us-east',
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )

        count = conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar() or 0
        if count < ROW_TARGET:
            need = ROW_TARGET - int(count)
            # Batched inserts
            while need > 0:
                batch = min(need, 500)
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {TABLE} (email, region)
                        SELECT
                          'user_' || gen_random_uuid()::STRING || '@example.com',
                          (ARRAY['us-east','us-west','eu-west'])[1 + (random()*2)::INT]
                        FROM generate_series(1, :n)
                        """
                    ),
                    {"n": batch},
                )
                need -= batch

        # Grants — revoke write paths for judge_ro if any
        conn.execute(text(f"GRANT SELECT ON TABLE {TABLE} TO {ROLE}"))
        # Ensure no INSERT/UPDATE/DELETE/CREATE where possible
        try:
            conn.execute(text(f"REVOKE INSERT, UPDATE, DELETE ON TABLE {TABLE} FROM {ROLE}"))
        except Exception:
            pass
        try:
            conn.execute(text(f"REVOKE CREATE ON DATABASE {engine.url.database} FROM {ROLE}"))
        except Exception:
            pass
        # Database-level CREATE isn't the only write path: CockroachDB grants
        # CREATE on the `public` schema to the implicit `public` role by
        # default, so a freshly created database lets any user CREATE TABLE
        # there unless this is revoked too. Without it, app.schema_analysis's
        # own read-only probe (a real CREATE TABLE attempt) correctly rejects
        # this "read-only" role as writable.
        try:
            conn.execute(text("REVOKE CREATE ON SCHEMA public FROM public"))
        except Exception:
            pass
        try:
            conn.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {ROLE}"))
        except Exception:
            pass

        final_count = conn.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar()

    ro_url = _build_ro_url(admin, password)
    url_file = demo_secret_write_path(JUDGE_RO_DATABASE_URL_FILE)
    url_file.write_text(ro_url + "\n", encoding="utf-8")
    print(f"customers_row_count={final_count}")
    print(f"JUDGE_RO_DATABASE_URL={ro_url}")
    print(f"password_file={PASSWORD_FILE}")
    print(f"url_file={url_file}")


if __name__ == "__main__":
    main()
