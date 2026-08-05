from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.database.models import MemorySharingPreference
from app.repositories.base import BaseRepository


class MemorySharingPreferenceRepository(BaseRepository[MemorySharingPreference]):
    """Consent record lookup for cross-customer memory sharing.

    See docs/cross_customer.md §2 and Hard Constraint 1 — a missing row and
    a row with ``cross_customer_sharing_enabled=False`` both mean "do not
    share"; ``is_enabled`` never treats absence as consent.
    """

    model = MemorySharingPreference

    async def get_by_owner(self, owner_identity: str) -> MemorySharingPreference | None:
        result = await self._session.execute(
            select(MemorySharingPreference).where(
                MemorySharingPreference.owner_identity == owner_identity
            )
        )
        return result.scalar_one_or_none()

    async def is_enabled(self, owner_identity: str) -> bool:
        pref = await self.get_by_owner(owner_identity)
        return bool(pref and pref.cross_customer_sharing_enabled)

    async def set_enabled(
        self, owner_identity: str, *, enabled: bool
    ) -> MemorySharingPreference:
        now = datetime.now(UTC)
        existing = await self.get_by_owner(owner_identity)
        if existing is None:
            entity = MemorySharingPreference(
                owner_identity=owner_identity,
                cross_customer_sharing_enabled=enabled,
                enabled_at=now if enabled else None,
                disabled_at=None if enabled else now,
            )
            return await self.create(entity)

        existing.cross_customer_sharing_enabled = enabled
        if enabled:
            existing.enabled_at = now
        else:
            existing.disabled_at = now
        return await self.update(existing)
