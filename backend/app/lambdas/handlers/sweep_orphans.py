"""Shadow orphan sweeper Lambda — EventBridge-scheduled hygiene."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.logging import get_logger
from app.lambdas.runtime import get_runtime, handler_correlation, run_async, with_session
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.services.shadow_cluster_service import ShadowClusterService
from app.shadow.sweeper import ShadowClusterSweeper

logger = get_logger(__name__)


def handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    # EventBridge schedule has no run_id — correlation is optional for this job.
    with handler_correlation(
        event or {},
        context,
        function_name="shadow-sweeper",
        require_run=False,
    ):
        return run_async(_handle(event or {}))


async def _handle(event: dict[str, Any]) -> dict[str, Any]:
    runtime = get_runtime()
    logger.info("ShadowSweeper started", extra={"event_keys": sorted(event.keys())})

    async def _run(session):
        service = ShadowClusterService(
            repository=ShadowClusterRepository(session),
            session=session,
        )
        provider = runtime.create_provider()
        sweeper = ShadowClusterSweeper(
            service=service,
            provider=provider,
            app_tag=runtime.settings.shadow_app_tag,
            max_lifetime_minutes=runtime.settings.shadow_max_lifetime_minutes,
            observability=runtime.observability,
        )
        return await sweeper.sweep()

    report = await with_session(runtime, _run)
    logger.info(
        "ShadowSweeper finished",
        extra={
            "db_rows": len(report.get("swept_db_rows") or []),
            "provider_clusters": len(report.get("swept_provider_clusters") or []),
            "errors": len(report.get("errors") or []),
        },
    )
    # Ensure JSON-serializable for Lambda response.
    return json.loads(json.dumps(report, default=str))
