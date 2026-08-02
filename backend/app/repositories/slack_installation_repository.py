"""Persistence operations for SlackInstallation entities."""

from __future__ import annotations

from sqlalchemy import select

from app.database.models import SlackInstallation
from app.repositories.base import BaseRepository


class SlackInstallationRepository(BaseRepository[SlackInstallation]):
    """Repository for one Slack installation per owner identity.

    Persistence only; the service layer owns commit/rollback.
    """

    model = SlackInstallation

    async def get_by_owner(self, owner_identity: str) -> SlackInstallation | None:
        query = select(SlackInstallation).where(
            SlackInstallation.owner_identity == owner_identity
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def delete_by_owner(self, owner_identity: str) -> bool:
        """Delete the installation for the given owner.

        Returns True when a row was deleted, False when none existed.
        """
        entity = await self.get_by_owner(owner_identity)
        if entity is None:
            return False
        await self.delete(entity)
        return True
