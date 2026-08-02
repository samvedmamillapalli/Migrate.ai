from __future__ import annotations

import abc

from app.shadow.models import ProvisionedCluster, ProvisionSpec, RemoteCluster


class ShadowProviderError(Exception):
    """Base error for shadow cluster provider operations."""


class ShadowProvisionError(ShadowProviderError):
    """Cluster creation or readiness failed."""


class ShadowClusterProvider(abc.ABC):
    """Abstraction over a shadow cluster backend.

    Two implementations exist:

    * ``CCloudApiShadowProvider`` — the real backend, and the default
      (``SHADOW_PROVIDER=ccloud_api``). Creates/destroys CockroachDB Basic
      clusters through the CockroachDB Cloud REST API using a service-account
      Bearer token, which — unlike the ccloud CLI — works headlessly.
    * ``MockShadowProvider`` — provisions an isolated scratch database on the
      control-plane cluster so the full seed -> migrate -> destroy path can be
      exercised offline, with no Cloud API key.

    Contract notes:

    * ``destroy`` MUST be idempotent — destroying an already-destroyed or
      never-created cluster returns ``True``, never raises.
    * Every created cluster MUST be tagged/named with the app tag and run id so
      ``list_app_clusters`` can find orphans for the sweeper.

    NOTE (warm pool, deferred to a later phase): on-demand ``create`` is the only
    strategy implemented here. If provisioning latency proves too slow for the
    demo, a pre-warmed pool would slot in behind this same interface — a warm
    provider would return an already-ready ``ProvisionedCluster`` from ``create``
    and make ``await_ready`` a no-op. That pool is intentionally NOT built now.
    """

    #: Short provider identifier persisted on the ShadowCluster row.
    name: str = "abstract"

    @abc.abstractmethod
    async def create(self, spec: ProvisionSpec) -> ProvisionedCluster:
        """Create a cluster tagged with ``spec.app_tag`` and ``spec.run_id``.

        Returns as soon as the cluster exists; readiness is awaited separately.
        """

    @abc.abstractmethod
    async def await_ready(
        self,
        cluster: ProvisionedCluster,
        *,
        timeout_seconds: int,
        poll_interval_seconds: float,
    ) -> None:
        """Block until the cluster accepts SQL connections or ``timeout``."""

    @abc.abstractmethod
    async def destroy(
        self,
        *,
        cluster_id: str | None = None,
        cluster_name: str | None = None,
    ) -> bool:
        """Idempotently destroy a cluster by id and/or name.

        Returns ``True`` whether or not the cluster still existed. Never raises
        for an already-gone cluster.
        """

    @abc.abstractmethod
    async def list_app_clusters(self, app_tag: str) -> list[RemoteCluster]:
        """List clusters that belong to this application (for the sweeper)."""

    async def provision_sql_access(self, cluster: ProvisionedCluster) -> str:
        """Ensure ``cluster.connection_url`` is a usable SQL connection string.

        Some providers (e.g. ``MockShadowProvider``) already attach a working
        ``connection_url`` in ``create()``, so the default is a no-op that just
        returns it. ``CCloudApiShadowProvider`` overrides this: a real
        serverless cluster only knows its connection shape once a SQL user is
        minted, which requires this separate call after ``await_ready``.
        """
        return cluster.connection_url

    async def aclose(self) -> None:
        """Release any provider-held resources. Default is a no-op."""
        return None
