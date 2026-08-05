from __future__ import annotations

import asyncio
import uuid

from app.core.logging import get_logger
from app.database.models import ShadowCluster
from app.services.shadow_cluster_service import ShadowClusterService

logger = get_logger(__name__)


class SlotAcquisitionTimeout(Exception):
    """No shadow cluster slot became available within the wait budget."""


async def acquire_slot(
    service: ShadowClusterService,
    *,
    run_id: uuid.UUID,
    region: str,
    provider: str,
    scale_tier: str,
    max_concurrent: int,
    max_lifetime_minutes: int,
    wait_timeout_seconds: int,
    poll_interval_seconds: float,
    owner_identity: str | None = None,
    max_concurrent_per_owner: int | None = None,
) -> ShadowCluster:
    """Admit a run under the concurrency cap, queuing (waiting) if it is full.

    This is DB-backed admission control: the count-then-insert happens in a
    serializable transaction inside ``try_admit``. When the cap is reached the
    caller waits and retries rather than provisioning a third cluster, which is
    the "overflow queues rather than provisions immediately" behaviour required
    by this phase. It is not a persisted job queue — that overlaps with the
    Phase 8 Step Functions work.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + wait_timeout_seconds
    waited = False
    while True:
        admitted = await service.try_admit(
            run_id=run_id,
            region=region,
            provider=provider,
            scale_tier=scale_tier,
            max_concurrent=max_concurrent,
            max_lifetime_minutes=max_lifetime_minutes,
            owner_identity=owner_identity,
            max_concurrent_per_owner=max_concurrent_per_owner,
        )
        if admitted is not None:
            if waited:
                logger.info(
                    "Shadow slot acquired after waiting",
                    extra={"run_id": str(run_id)},
                )
            return admitted

        if loop.time() >= deadline:
            raise SlotAcquisitionTimeout(
                f"No shadow cluster slot available within {wait_timeout_seconds}s "
                f"(cap={max_concurrent})"
            )
        waited = True
        logger.info(
            "Shadow concurrency cap reached; waiting for a slot",
            extra={"run_id": str(run_id), "cap": max_concurrent},
        )
        await asyncio.sleep(poll_interval_seconds)
