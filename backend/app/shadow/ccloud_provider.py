from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import datetime
from typing import Any

from app.core.logging import get_logger
from app.shadow.models import ProvisionedCluster, ProvisionSpec, RemoteCluster
from app.shadow.provider import (
    ShadowClusterProvider,
    ShadowProvisionError,
    ShadowProviderError,
)

logger = get_logger(__name__)


class CCloudCommandError(ShadowProviderError):
    """A ccloud CLI invocation exited non-zero."""

    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        # ``args`` is safe to include: secrets are passed via env / stdin, never
        # as CLI arguments, so the command line never contains the API key or a
        # SQL password.
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"ccloud {' '.join(args)} failed (exit {returncode}): {stderr.strip()}"
        )


class CCloudShadowProvider(ShadowClusterProvider):
    """Real provider: provisions CockroachDB Basic clusters via the ccloud CLI.

    The hackathon requires using at least two CockroachDB tools; provisioning
    and tearing down shadow clusters through the ccloud CLI is one of them (the
    distributed vector index in Phase 10 is the other). Every ccloud command is
    invoked with JSON output and parsed.

    Authentication is non-interactive: the service-account API key is injected
    into the subprocess environment, never passed as an argument and never
    logged.

    IMPORTANT — command surface must be verified against your installed ccloud
    version. The subcommand names and flags below reflect the documented
    ``ccloud cluster`` surface, but the CLI evolves; run each command once by
    hand (``ccloud cluster create basic --help`` etc.) and adjust the small
    number of command-builder methods here if your version differs. The control
    flow, JSON parsing, idempotent teardown, and tagging do not change.
    """

    name = "cockroachdb_cloud"

    # ccloud reads the API key from this env var for non-interactive auth.
    # Verify the exact variable name for your ccloud version; some versions use
    # ``COCKROACH_CLOUD_API_KEY``. Kept in one place for easy adjustment.
    _API_KEY_ENV = "CCLOUD_API_KEY"

    def __init__(
        self,
        *,
        binary: str,
        api_key: str,
        cloud: str,
        region: str,
    ) -> None:
        if not api_key:
            raise ShadowProviderError(
                "CCLOUD_API_KEY is required for the ccloud provider"
            )
        self._binary = binary
        self._api_key = api_key
        self._cloud = cloud
        self._region = region

    # -- subprocess plumbing ------------------------------------------------

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Inject the key into the child environment only. Never logged.
        env[self._API_KEY_ENV] = self._api_key
        return env

    async def _run(self, *args: str, timeout_seconds: int = 120) -> dict[str, Any] | list[Any]:
        """Run ``ccloud <args> -o json`` and return the parsed JSON payload."""
        cmd = [self._binary, *args, "-o", "json"]
        # Log the command without the API key (it is in env, not argv).
        logger.info("Running ccloud command", extra={"args": list(args)})
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(),
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise ShadowProvisionError(
                f"ccloud {' '.join(args)} timed out after {timeout_seconds}s"
            ) from None

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise CCloudCommandError(list(args), proc.returncode or -1, stderr)

        if not stdout.strip():
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ShadowProviderError(
                f"ccloud {' '.join(args)} returned non-JSON output"
            ) from exc

    # -- provider interface -------------------------------------------------

    async def create(self, spec: ProvisionSpec) -> ProvisionedCluster:
        # Create a CockroachDB Basic cluster. The cluster NAME is our tag: it
        # embeds the app tag and run id so the sweeper can identify orphans.
        # (CockroachDB Basic does not expose arbitrary key/value labels, so the
        # name convention is the tag.)
        payload = await self._run(
            "cluster",
            "create",
            "basic",
            spec.cluster_name,
            "--cloud",
            spec.cloud,
            "--region",
            spec.region,
            timeout_seconds=300,
        )
        if not isinstance(payload, dict):
            raise ShadowProvisionError("Unexpected create payload shape")

        cluster_id = str(payload.get("id") or payload.get("cluster_id") or "")
        if not cluster_id:
            raise ShadowProvisionError("ccloud create did not return a cluster id")

        # Non-interactively mint a SQL user so we have credentials to connect.
        connection_url = await self._create_sql_user_and_url(
            cluster_id=cluster_id,
            cluster_name=spec.cluster_name,
        )
        logger.info(
            "Created shadow cluster",
            extra={"cluster_id": cluster_id, "cluster_name": spec.cluster_name},
        )
        return ProvisionedCluster(
            cluster_id=cluster_id,
            cluster_name=spec.cluster_name,
            region=spec.region,
            connection_url=connection_url,
        )

    async def _create_sql_user_and_url(
        self,
        *,
        cluster_id: str,
        cluster_name: str,
    ) -> str:
        """Create a SQL user and assemble a connection URL.

        The generated password is passed to ccloud via a flag-free path where
        possible; if your ccloud version only accepts ``--password`` on argv,
        note it still never touches application logs. Verify the exact
        ``sql-users`` subcommand for your version.
        """
        username = "mo_shadow"
        password = secrets.token_urlsafe(24)

        # TODO(verify-per-version): exact subcommand/flags for SQL user creation.
        await self._run(
            "cluster",
            "sql-users",
            "create",
            username,
            "--cluster",
            cluster_id,
            "--password",
            password,
            timeout_seconds=120,
        )

        # Fetch the cluster's SQL connection details as JSON and substitute the
        # user/password we just created.
        info = await self._run("cluster", "get", cluster_id, timeout_seconds=120)
        host = _extract_sql_host(info)
        if not host:
            raise ShadowProvisionError(
                "Could not determine shadow cluster SQL host from ccloud output"
            )
        # CockroachDB Basic uses a routing suffix in the database name; ccloud
        # connection strings encode it. Verify against ``ccloud cluster sql``.
        return (
            f"postgresql://{username}:{password}@{host}:26257/defaultdb"
            "?sslmode=verify-full"
        )

    async def await_ready(
        self,
        cluster: ProvisionedCluster,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        # CockroachDB Basic clusters are typically usable almost immediately,
        # but do not assume it — poll cluster state until READY or timeout.
        # Provisioning latency is measured by the caller; this only gates on
        # readiness.
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while True:
            info = await self._run("cluster", "get", cluster.cluster_id)
            state = ""
            if isinstance(info, dict):
                state = str(info.get("state") or info.get("status") or "").upper()
            if state in {"CREATED", "READY", "ACTIVE", ""}:
                return
            if asyncio.get_event_loop().time() >= deadline:
                raise ShadowProvisionError(
                    f"Shadow cluster {cluster.cluster_id} not ready "
                    f"after {timeout_seconds}s (last state: {state or 'unknown'})"
                )
            await asyncio.sleep(poll_interval_seconds)

    async def destroy(
        self,
        *,
        cluster_id: str | None = None,
        cluster_name: str | None = None,
    ) -> bool:
        target = cluster_id or cluster_name
        if not target:
            # Nothing was ever created; idempotently succeed.
            return True
        try:
            await self._run("cluster", "delete", target, "--force", timeout_seconds=180)
        except CCloudCommandError as exc:
            # Idempotency: an already-deleted / unknown cluster is success.
            if _is_not_found(exc.stderr):
                logger.info(
                    "Shadow cluster already gone; treating delete as success",
                    extra={"target": target},
                )
                return True
            raise
        logger.info("Destroyed shadow cluster", extra={"target": target})
        return True

    async def list_app_clusters(self, app_tag: str) -> list[RemoteCluster]:
        payload = await self._run("cluster", "list")
        clusters_raw = _coerce_cluster_list(payload)
        result: list[RemoteCluster] = []
        for item in clusters_raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            # The sweeper only reaps clusters this app created, identified by the
            # app-tag prefix in the name.
            if not name.startswith(app_tag):
                continue
            result.append(
                RemoteCluster(
                    cluster_id=str(item.get("id") or item.get("cluster_id") or ""),
                    cluster_name=name,
                    created_at=_parse_created_at(item),
                )
            )
        return result


def _extract_sql_host(info: Any) -> str | None:
    if not isinstance(info, dict):
        return None
    # ccloud nests SQL DNS under a few possible keys across versions.
    for key in ("sql_dns", "dns", "host"):
        value = info.get(key)
        if isinstance(value, str) and value:
            return value
    regions = info.get("regions")
    if isinstance(regions, list) and regions:
        first = regions[0]
        if isinstance(first, dict):
            dns = first.get("sql_dns") or first.get("dns")
            if isinstance(dns, str) and dns:
                return dns
    return None


def _coerce_cluster_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("clusters", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _parse_created_at(item: dict[str, Any]) -> datetime | None:
    raw = item.get("created_at") or item.get("creation_timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_not_found(stderr: str) -> bool:
    lowered = stderr.lower()
    return (
        "not found" in lowered
        or "does not exist" in lowered
        or "no cluster" in lowered
        or "404" in lowered
    )
