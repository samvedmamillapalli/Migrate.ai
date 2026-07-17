from __future__ import annotations

import re
import time
from urllib.parse import urlparse, urlunparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.logging import get_logger
from app.database.session import normalize_database_url
from app.schema_analysis.errors import safe_log_target
from app.shadow.models import ProvisionedCluster, ProvisionSpec, RemoteCluster
from app.shadow.provider import ShadowClusterProvider

logger = get_logger(__name__)

_IDENT_RE = re.compile(r"[^a-z0-9_]")


def _sanitize_identifier(value: str) -> str:
    """Turn an arbitrary tag into a safe lowercase SQL identifier fragment."""
    cleaned = _IDENT_RE.sub("_", value.strip().lower())
    cleaned = cleaned.strip("_") or "shadow"
    if cleaned[0].isdigit():
        cleaned = f"s_{cleaned}"
    return cleaned


def _swap_database(url: str, database: str) -> str:
    """Return ``url`` with its path (database name) replaced."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{database}"))


class MockShadowProvider(ShadowClusterProvider):
    """Offline provider that stands in for real ccloud provisioning.

    Instead of creating a separate CockroachDB Cloud cluster, it creates an
    isolated **scratch database** on the control-plane cluster and hands back a
    connection URL to it. This makes the whole lifecycle real and measurable
    (schema shape is recreated, synthetic rows are inserted, the migration DDL
    actually runs, storage genuinely grows) without needing a ccloud install or
    an API key. Teardown drops the scratch database.

    The scratch database name is the cluster's "tag": ``<prefix>_<run>_<epoch>``
    where ``prefix`` derives from the app tag. That lets ``list_app_clusters``
    (and therefore the sweeper) find orphaned scratch databases and compute
    their age, exactly as the real provider finds orphaned clusters by name.
    """

    name = "mock_local"

    def __init__(self, control_plane_url: str) -> None:
        # Normalized async URL for the control-plane cluster (admin connection).
        self._admin_url = normalize_database_url(control_plane_url)
        # Raw URL is used as the template for scratch DB connection strings so
        # the seeder re-normalizes it (attaching the CA cert) itself.
        self._raw_url = control_plane_url

    async def _admin_execute(self, statement: str) -> None:
        # DDL like CREATE/DROP DATABASE runs outside an explicit transaction.
        engine = create_async_engine(self._admin_url, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                autocommit = await conn.execution_options(
                    isolation_level="AUTOCOMMIT"
                )
                await autocommit.execute(text(statement))
        finally:
            await engine.dispose()

    async def create(self, spec: ProvisionSpec) -> ProvisionedCluster:
        prefix = _sanitize_identifier(spec.app_tag)
        run_short = spec.run_id.hex[:8]
        epoch = int(time.time())
        db_name = f"{prefix}_{run_short}_{epoch}"

        await self._admin_execute(f'CREATE DATABASE IF NOT EXISTS "{db_name}"')
        connection_url = _swap_database(self._raw_url, db_name)

        logger.info(
            "Provisioned mock shadow database",
            extra={"cluster_name": db_name},
        )
        return ProvisionedCluster(
            # For the mock, the scratch DB name is both id and name/tag.
            cluster_id=db_name,
            cluster_name=db_name,
            region=spec.region,
            connection_url=connection_url,
        )

    async def await_ready(
        self,
        cluster: ProvisionedCluster,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        # A freshly created database is immediately usable; nothing to wait on.
        return None

    async def destroy(
        self,
        *,
        cluster_id: str | None = None,
        cluster_name: str | None = None,
    ) -> bool:
        db_name = cluster_id or cluster_name
        if not db_name:
            return True
        # IF EXISTS makes teardown idempotent.
        await self._admin_execute(f'DROP DATABASE IF EXISTS "{db_name}" CASCADE')
        logger.info(
            "Destroyed mock shadow database",
            extra={"cluster_name": db_name},
        )
        return True

    async def list_app_clusters(self, app_tag: str) -> list[RemoteCluster]:
        prefix = _sanitize_identifier(app_tag)
        engine = create_async_engine(self._admin_url, pool_pre_ping=True)
        names: list[str] = []
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SHOW DATABASES"))
                for row in result:
                    name = str(row[0])
                    if name.startswith(f"{prefix}_"):
                        names.append(name)
        except Exception:  # noqa: BLE001 - best-effort listing for the sweeper
            logger.warning(
                "Mock provider could not list scratch databases",
                extra=safe_log_target("control-plane", "*"),
            )
        finally:
            await engine.dispose()

        clusters: list[RemoteCluster] = []
        for name in names:
            clusters.append(
                RemoteCluster(
                    cluster_id=name,
                    cluster_name=name,
                    created_at=_created_at_from_name(name),
                )
            )
        return clusters


def _created_at_from_name(name: str):  # noqa: ANN202 - datetime | None
    from datetime import UTC, datetime

    parts = name.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    return datetime.fromtimestamp(int(parts[1]), tz=UTC)
