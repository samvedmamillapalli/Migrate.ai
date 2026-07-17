from __future__ import annotations

import asyncio
import secrets as _secrets
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.core.logging import get_logger
from app.shadow.models import ProvisionedCluster, ProvisionSpec, RemoteCluster
from app.shadow.provider import (
    ShadowClusterProvider,
    ShadowProviderError,
    ShadowProvisionError,
)

logger = get_logger(__name__)

# Cluster lifecycle states from the CockroachDB Cloud API (ClusterStateType).
_STATE_READY = "CREATED"
_STATE_FAILED = "CREATION_FAILED"
_STATE_DELETED = "DELETED"

# HTTP statuses we never retry (caller/permission errors).
_NON_RETRYABLE = frozenset({400, 401, 403, 404, 409, 422})


class CCloudApiError(ShadowProviderError):
    """A CockroachDB Cloud REST API call failed."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"CockroachDB Cloud API {status}: {message}")


class CCloudApiAuthError(CCloudApiError):
    """401/403 — the API key is invalid or lacks the required role."""


class CCloudApiShadowProvider(ShadowClusterProvider):
    """Real shadow provider backed by the CockroachDB Cloud REST API.

    Uses a service-account API key as a Bearer token (the supported
    non-interactive credential; the ccloud CLI only supports interactive browser
    login). Every cluster is tagged with ``labels`` carrying the app tag and run
    id so the sweeper can identify orphans.

    Resiliency: transient failures (429 throttling, 5xx, network errors) are
    retried with bounded exponential backoff and honour ``Retry-After``. Auth
    and other 4xx caller errors are never retried.

    Secret hygiene: the Bearer token is only ever placed in the Authorization
    header. It is never logged and never included in exceptions.
    """

    name = "cockroachdb_cloud_api"

    def __init__(
        self,
        *,
        api_secret: str,
        base_url: str,
        plan: str,
        provider_cloud: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
        backoff_base_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_secret:
            raise ShadowProviderError("ccloud_api_secret is required")
        self._base_url = base_url.rstrip("/")
        self._plan = plan
        self._cloud = provider_cloud
        self._max_retries = max_retries
        self._backoff = backoff_base_seconds
        # ``transport`` is a test seam (httpx.MockTransport) so retry/throttle/
        # auth handling can be verified deterministically without live calls.
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers={
                "Authorization": f"Bearer {api_secret}",
                "Content-Type": "application/json",
            },
            transport=transport,
        )

    # -- HTTP plumbing ------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.request(method, path, json=json_body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt > self._max_retries:
                    raise CCloudApiError(0, f"network error: {exc}") from exc
                await self._sleep_backoff(attempt)
                continue

            if response.status_code < 400:
                return response

            # Retry throttling and server errors within the retry budget.
            if response.status_code == 429 or response.status_code >= 500:
                if attempt > self._max_retries:
                    raise CCloudApiError(
                        response.status_code, _safe_message(response)
                    )
                await self._sleep_backoff(attempt, response)
                continue

            # Non-retryable caller/permission error.
            if response.status_code in {401, 403}:
                raise CCloudApiAuthError(response.status_code, _safe_message(response))
            raise CCloudApiError(response.status_code, _safe_message(response))

    async def _sleep_backoff(
        self,
        attempt: int,
        response: httpx.Response | None = None,
    ) -> None:
        delay = self._backoff * (2 ** (attempt - 1))
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass
        logger.info(
            "Retrying CockroachDB Cloud API call",
            extra={"attempt": attempt, "delay_seconds": round(delay, 2)},
        )
        await asyncio.sleep(delay)

    # -- provider interface -------------------------------------------------

    async def create(self, spec: ProvisionSpec) -> ProvisionedCluster:
        name = _cluster_name(spec.run_id)
        body = {
            "name": name,
            "provider": self._cloud,
            "spec": {
                "plan": self._plan,
                "serverless": {"regions": [spec.region]},
                # Labels are the durable tag the sweeper matches on.
                "labels": {"app": spec.app_tag, "run": spec.run_id.hex},
            },
        }
        response = await self._request("POST", "/api/v1/clusters", json_body=body)
        payload = response.json()
        cluster_id = str(payload.get("id") or "")
        if not cluster_id:
            raise ShadowProvisionError("create did not return a cluster id")
        logger.info(
            "Created shadow cluster",
            extra={"cluster_id": cluster_id, "cluster_name": name},
        )
        # connection_url is populated later (Phase 7B) once a SQL user exists.
        return ProvisionedCluster(
            cluster_id=cluster_id,
            cluster_name=name,
            region=spec.region,
            connection_url="",
        )

    async def await_ready(
        self,
        cluster: ProvisionedCluster,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout_seconds
        while True:
            payload = await self._get_cluster(cluster.cluster_id)
            state = str(payload.get("state") or "")
            if state == _STATE_READY:
                return
            if state == _STATE_FAILED:
                raise ShadowProvisionError(
                    f"cluster {cluster.cluster_id} entered {state}"
                )
            if loop.time() >= deadline:
                raise ShadowProvisionError(
                    f"cluster {cluster.cluster_id} not ready after "
                    f"{timeout_seconds}s (last state: {state or 'unknown'})"
                )
            await asyncio.sleep(poll_interval_seconds)

    async def get_state(self, cluster_id: str) -> str:
        payload = await self._get_cluster(cluster_id)
        return str(payload.get("state") or "")

    async def provision_sql_access(self, cluster: ProvisionedCluster) -> str:
        """Create a SQL user on the (ready) cluster and attach a connection URL.

        Serverless clusters use a per-cluster public DNS (``sql_dns``); the
        routing id is encoded in the host, so a standard connection string works.
        The generated password is never logged. Returns the connection URL and
        also attaches it to ``cluster``.
        """
        payload = await self._get_cluster(cluster.cluster_id)
        sql_dns = str(payload.get("sql_dns") or "")
        if not sql_dns:
            regions = payload.get("regions") or []
            if regions and isinstance(regions[0], dict):
                sql_dns = str(regions[0].get("sql_dns") or "")
        if not sql_dns:
            raise ShadowProvisionError("cluster has no sql_dns for connection")

        username = "mo_app"
        password = _gen_password()
        await self._request(
            "POST",
            f"/api/v1/clusters/{cluster.cluster_id}/sql-users",
            json_body={"name": username, "password": password},
        )
        url = _build_connection_url(sql_dns, username, password)
        cluster.attach_connection_url(url)
        logger.info(
            "Provisioned shadow SQL user",
            extra={"cluster_id": cluster.cluster_id, "sql_user": username},
        )
        return url

    async def _get_cluster(self, cluster_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/api/v1/clusters/{cluster_id}")
        return response.json()

    async def destroy(
        self,
        *,
        cluster_id: str | None = None,
        cluster_name: str | None = None,
    ) -> bool:
        target_id = cluster_id
        if not target_id and cluster_name:
            target_id = await self._resolve_id_by_name(cluster_name)
        if not target_id:
            # Never created / already gone.
            return True
        try:
            await self._request("DELETE", f"/api/v1/clusters/{target_id}")
        except CCloudApiError as exc:
            if exc.status == 404:
                return True  # already deleted — idempotent success
            raise
        logger.info("Destroyed shadow cluster", extra={"cluster_id": target_id})
        return True

    async def _resolve_id_by_name(self, cluster_name: str) -> str | None:
        for item in await self._list_clusters():
            if item.get("name") == cluster_name:
                return str(item.get("id"))
        return None

    async def list_app_clusters(self, app_tag: str) -> list[RemoteCluster]:
        result: list[RemoteCluster] = []
        for item in await self._list_clusters():
            labels = item.get("labels") or {}
            if labels.get("app") != app_tag:
                continue
            if str(item.get("state")) == _STATE_DELETED:
                continue
            result.append(
                RemoteCluster(
                    cluster_id=str(item.get("id") or ""),
                    cluster_name=str(item.get("name") or ""),
                    created_at=_parse_ts(item.get("created_at")),
                )
            )
        return result

    async def _list_clusters(self) -> list[dict[str, Any]]:
        clusters: list[dict[str, Any]] = []
        page_token = ""
        while True:
            path = "/api/v1/clusters?pagination.limit=200"
            if page_token:
                path += f"&pagination.page={page_token}"
            payload = (await self._request("GET", path)).json()
            clusters.extend(payload.get("clusters") or [])
            page = payload.get("pagination") or {}
            page_token = page.get("next_page") or ""
            if not page_token:
                break
        return clusters

    async def aclose(self) -> None:
        await self._client.aclose()


def _cluster_name(run_id: Any) -> str:
    """A valid CockroachDB Cloud cluster name (<=20 chars, starts with a letter)."""
    return f"mo-{run_id.hex[:16]}"


def _gen_password() -> str:
    # CockroachDB Cloud requires a reasonably strong password; token_urlsafe is
    # long and mixes letters/digits. Never logged.
    return _secrets.token_urlsafe(24)


def _build_connection_url(sql_dns: str, username: str, password: str) -> str:
    # sslmode=require: the connection is encrypted but we don't pin the server
    # CA. Serverless clusters present a public-CA cert (not the self-hosted
    # root.crt the rest of the app uses), and the shadow is a disposable cluster
    # we just created over an authenticated API call and connect to immediately.
    # This avoids cross-platform CA-bundle path issues (Windows/Lambda).
    return (
        f"postgresql://{quote(username, safe='')}:{quote(password, safe='')}"
        f"@{sql_dns}:26257/defaultdb?sslmode=require"
    )


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_message(response: httpx.Response) -> str:
    """Extract an API error message without leaking secrets."""
    try:
        data = response.json()
        if isinstance(data, dict):
            return str(data.get("message") or data.get("error") or data)[:300]
    except Exception:  # noqa: BLE001
        pass
    return (response.text or "")[:300]
