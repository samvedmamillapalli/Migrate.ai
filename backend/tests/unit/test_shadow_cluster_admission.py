"""ShadowClusterService.try_admit — docs/FUTURE_CONCURRENT_SHADOW_PLAN.md.

Covers the existing global-cap admission (unchanged) and the new, additive
per-owner cap: unset by default (identical to today's behavior), and when
set, checked in the same admission decision as the global cap so one owner
can't exhaust every slot.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.shadow_cluster_service import ShadowClusterService


@pytest.fixture
def repository() -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_migration_run_id = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def session() -> AsyncMock:
    mock = AsyncMock()
    mock.commit = AsyncMock()
    mock.rollback = AsyncMock()
    mock.refresh = AsyncMock()
    return mock


@pytest.fixture
def service(repository: AsyncMock, session: AsyncMock) -> ShadowClusterService:
    return ShadowClusterService(repository=repository, session=session)


def _admit_kwargs(**overrides) -> dict:
    defaults = dict(
        run_id=uuid.uuid4(),
        region="us-east-1",
        provider="ccloud_api",
        scale_tier="small",
        max_concurrent=2,
        max_lifetime_minutes=30,
    )
    defaults.update(overrides)
    return defaults


# ----------------------------------------------------- global cap (unchanged)


@pytest.mark.asyncio
async def test_admits_when_global_count_under_cap(
    service: ShadowClusterService, repository: AsyncMock
) -> None:
    repository.count_active = AsyncMock(return_value=1)
    result = await service.try_admit(**_admit_kwargs(max_concurrent=2))
    assert result is not None
    repository.count_active_for_owner.assert_not_called()


@pytest.mark.asyncio
async def test_rejects_when_global_count_at_cap(
    service: ShadowClusterService, repository: AsyncMock
) -> None:
    repository.count_active = AsyncMock(return_value=2)
    result = await service.try_admit(**_admit_kwargs(max_concurrent=2))
    assert result is None


@pytest.mark.asyncio
async def test_no_per_owner_check_when_cap_unset(
    service: ShadowClusterService, repository: AsyncMock
) -> None:
    """Default behavior: owner_identity given but no per-owner cap configured
    (the out-of-the-box setting) must not consult count_active_for_owner at
    all — identical to pre-existing global-only admission."""
    repository.count_active = AsyncMock(return_value=0)
    result = await service.try_admit(
        **_admit_kwargs(owner_identity="owner-a", max_concurrent_per_owner=None)
    )
    assert result is not None
    repository.count_active_for_owner.assert_not_called()


# ----------------------------------------------------------- per-owner cap


@pytest.mark.asyncio
async def test_rejects_when_owner_at_per_owner_cap_even_under_global_cap(
    service: ShadowClusterService, repository: AsyncMock
) -> None:
    repository.count_active = AsyncMock(return_value=1)  # under global cap of 5
    repository.count_active_for_owner = AsyncMock(return_value=1)  # at per-owner cap
    result = await service.try_admit(
        **_admit_kwargs(
            max_concurrent=5,
            owner_identity="owner-a",
            max_concurrent_per_owner=1,
        )
    )
    assert result is None
    repository.create.assert_not_called()


@pytest.mark.asyncio
async def test_admits_when_owner_under_per_owner_cap(
    service: ShadowClusterService, repository: AsyncMock
) -> None:
    repository.count_active = AsyncMock(return_value=1)
    repository.count_active_for_owner = AsyncMock(return_value=0)
    result = await service.try_admit(
        **_admit_kwargs(
            max_concurrent=5,
            owner_identity="owner-a",
            max_concurrent_per_owner=1,
        )
    )
    assert result is not None
    repository.count_active_for_owner.assert_awaited_once_with("owner-a")


@pytest.mark.asyncio
async def test_reuses_existing_shadow_for_run_without_checking_caps(
    service: ShadowClusterService, repository: AsyncMock
) -> None:
    """One shadow per run (unique constraint) — a re-admit call for a run
    that already has a cluster returns it directly, no cap check at all."""
    from app.database.models import ShadowCluster, ShadowClusterStatus

    existing = ShadowCluster(
        id=uuid.uuid4(),
        migration_run_id=uuid.uuid4(),
        provider="ccloud_api",
        region="us-east-1",
        status=ShadowClusterStatus.READY,
        scale_tier="small",
    )
    repository.get_by_migration_run_id = AsyncMock(return_value=existing)
    result = await service.try_admit(**_admit_kwargs(owner_identity="owner-a"))
    assert result is existing
    repository.count_active.assert_not_called()
