from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.logging import get_logger
from app.database.models import ShadowClusterStatus
from app.services.shadow_cluster_service import ShadowClusterService
from app.shadow.provider import ShadowClusterProvider

logger = get_logger(__name__)


class ShadowClusterSweeper:
    """Reaps leaked shadow clusters older than the max lifetime.

    Because CockroachDB Basic is billed by usage (not by how long a cluster
    exists), the sweeper is about hygiene: never leak orphaned clusters when a
    process dies mid-lifecycle. It works two ways:

    1. **DB-driven** — active ``shadow_clusters`` rows whose ``expires_at`` has
       passed are destroyed and marked DESTROYED.
    2. **Provider-driven** — clusters the provider reports under this app's tag
       that are older than the max lifetime are destroyed even if no DB row
       remains (the true "process died" case).

    Teardown is idempotent, so overlap between the two paths is harmless.
    """

    def __init__(
        self,
        *,
        service: ShadowClusterService,
        provider: ShadowClusterProvider,
        app_tag: str,
        max_lifetime_minutes: int,
    ) -> None:
        self._service = service
        self._provider = provider
        self._app_tag = app_tag
        self._max_lifetime = timedelta(minutes=max_lifetime_minutes)

    async def sweep(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        report: dict[str, Any] = {
            "swept_db_rows": [],
            "swept_provider_clusters": [],
            "errors": [],
        }

        await self._sweep_db_rows(now, report)
        await self._sweep_provider(now, report)

        logger.info(
            "Shadow sweeper finished",
            extra={
                "db_rows": len(report["swept_db_rows"]),
                "provider_clusters": len(report["swept_provider_clusters"]),
                "errors": len(report["errors"]),
            },
        )
        return report

    async def _sweep_db_rows(self, now: datetime, report: dict[str, Any]) -> None:
        expired = await self._service.list_expired_active(now)
        for row in expired:
            try:
                await self._service.transition(
                    row.id, ShadowClusterStatus.DESTROYING
                )
                await self._provider.destroy(
                    cluster_id=row.cluster_id,
                    cluster_name=row.cluster_name,
                )
                await self._service.transition(
                    row.id, ShadowClusterStatus.DESTROYED
                )
                report["swept_db_rows"].append(str(row.id))
            except Exception as exc:  # noqa: BLE001 - keep sweeping other rows
                await self._service.set_error(row.id, f"sweep failed: {exc}")
                try:
                    await self._service.transition(
                        row.id, ShadowClusterStatus.FAILED
                    )
                except Exception:  # noqa: BLE001
                    pass
                report["errors"].append({"shadow_id": str(row.id), "error": str(exc)})

    async def _sweep_provider(self, now: datetime, report: dict[str, Any]) -> None:
        cutoff = now - self._max_lifetime
        try:
            clusters = await self._provider.list_app_clusters(self._app_tag)
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"list_app_clusters": str(exc)})
            return

        for cluster in clusters:
            # Only reap clusters we can prove are older than the max lifetime.
            # An unknown-age cluster might be provisioning right now in another
            # process, so we leave it alone.
            if cluster.created_at is None or cluster.created_at > cutoff:
                continue
            try:
                await self._provider.destroy(
                    cluster_id=cluster.cluster_id,
                    cluster_name=cluster.cluster_name,
                )
                report["swept_provider_clusters"].append(cluster.cluster_name)
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(
                    {"cluster": cluster.cluster_name, "error": str(exc)}
                )
