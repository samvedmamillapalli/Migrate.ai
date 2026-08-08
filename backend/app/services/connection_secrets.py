"""Shared connection-secret storage/loading — extracted from app/api/routes/runs.py
so app/services/workspace_service.py can reuse the exact same store/load path
(docs/FUTURE_WORKSPACES_PLAN.md) instead of duplicating it.

Never persists a raw password on any ORM row — every caller stores a pointer
(a Secrets Manager ARN, or a local secret name in dev) and looks the real
connection up through here at use time.
"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Request

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.schema_analysis.database_connection import DatabaseConnection, SslMode

logger = get_logger(__name__)


def parse_database_url(url: str) -> DatabaseConnection:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValidationError("database_url must include a host")
    database = (parsed.path or "/").lstrip("/") or "defaultdb"
    query = dict(
        part.split("=", 1) for part in (parsed.query or "").split("&") if "=" in part
    )
    ssl_raw = (query.get("sslmode") or "require").replace("_", "-")
    try:
        ssl_mode = SslMode(ssl_raw)
    except ValueError:
        ssl_mode = SslMode.REQUIRE
    return DatabaseConnection(
        host=parsed.hostname,
        port=parsed.port or 26257,
        database=database,
        username=parsed.username or "root",
        password=parsed.password or "",
        ssl_mode=ssl_mode,
    )


async def store_connection_url(
    request: Request,
    secret_name: str,
    database_url: str,
) -> str:
    """Store URL in local/AWS secret store; return ARN/name pointer.

    ``secret_name`` is caller-built so both runs
    (``migration-oracle/connections/{run_id}``) and workspaces
    (``migration-oracle/connections/workspace/{workspace_id}``) can use
    this one storage path with distinguishable names in the AWS console.
    """
    payload = {"database_url": database_url}
    try:
        from app.lambdas.runtime import get_runtime

        runtime = get_runtime()
        return await runtime.secrets.put_json(secret_name, payload)
    except Exception as exc:
        from app.config import get_settings

        env = get_settings().environment.strip().lower()
        if env not in {"development", "dev", "local", "test"}:
            raise ValidationError(
                "Unable to store connection secret in Secrets Manager / local "
                f"secret store (refusing in-memory fallback in {env}): {exc}"
            ) from exc
        # Dev-only ephemeral fallback — lost on API restart.
        request.app.state._demo_secrets = getattr(request.app.state, "_demo_secrets", {})
        request.app.state._demo_secrets[secret_name] = payload
        logger.warning(
            "Stored connection URL in process memory (dev fallback)",
            extra={"secret_name": secret_name},
        )
        return secret_name


async def load_connection(request: Request, secret_arn: str) -> DatabaseConnection:
    demo = getattr(request.app.state, "_demo_secrets", {})
    if secret_arn in demo:
        url = demo[secret_arn].get("database_url")
        if not url:
            raise ValidationError("Stored secret missing database_url")
        return parse_database_url(url)

    try:
        from app.lambdas.runtime import get_runtime

        runtime = get_runtime()
        raw = await runtime.secrets.get_json(secret_arn)
        if isinstance(raw, dict) and raw.get("database_url"):
            return parse_database_url(str(raw["database_url"]))
        if isinstance(raw, dict) and raw.get("host"):
            ssl_raw = str(raw.get("sslmode") or raw.get("ssl_mode") or "require")
            try:
                ssl_mode = SslMode(ssl_raw.replace("_", "-"))
            except ValueError:
                ssl_mode = SslMode.REQUIRE
            return DatabaseConnection(
                host=str(raw["host"]),
                port=int(raw.get("port") or 26257),
                database=str(raw.get("database") or "defaultdb"),
                username=str(raw.get("username") or "root"),
                password=str(raw.get("password") or ""),
                ssl_mode=ssl_mode,
            )
        raise ValidationError("Secret must contain database_url or connection fields")
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"Unable to load connection secret: {exc}") from exc


async def verify_connection_ping(connection: DatabaseConnection) -> str | None:
    """Lightweight "can we connect" check — a bare ``SELECT version()``, not
    a full schema discovery. Used at workspace-creation time
    (docs/FUTURE_WORKSPACES_PLAN.md, Open Question: validate at creation vs.
    lazily on first discover — resolved as "validate cheaply now, fail fast
    on a broken connection" rather than silently storing a bad pointer that
    only surfaces as an error days later on first real discover).

    Returns the raw ``server_version`` string the probe read (feed it to
    ``infer_engine`` for a display-friendly engine name), or ``None`` if the
    probe didn't get one back. Raises ``ValidationError`` on any failure.
    """
    from app.schema_analysis.connection import SchemaAnalysisConnection

    try:
        database_url = connection.to_database_url()
    except ValueError as exc:
        raise ValidationError(f"Invalid connection: {exc}") from exc

    probe = SchemaAnalysisConnection(database_url)
    try:
        return await probe.ping()
    except Exception as exc:  # noqa: BLE001 - any failure means "can't connect"
        raise ValidationError(f"Could not connect to database: {exc}") from exc
    finally:
        await probe.close()


def infer_engine(server_version: str | None) -> str | None:
    """Classify a raw ``SELECT version()`` string into a stable engine key.

    Shared by workspace connection labeling (``app/api/routes/workspaces.py``)
    and schema discovery persistence (``app/services/schema_discovery_service.py``)
    so both derive the same "cockroachdb"/"postgresql"/"unknown" value from
    the same string instead of drifting.
    """
    if not server_version:
        return None
    lowered = server_version.lower()
    if "cockroachdb" in lowered:
        return "cockroachdb"
    if "postgresql" in lowered or "postgres" in lowered:
        return "postgresql"
    return "unknown"
