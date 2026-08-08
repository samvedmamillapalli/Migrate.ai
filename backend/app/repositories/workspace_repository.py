from __future__ import annotations

import uuid

from sqlalchemy import or_, select

from app.database.models import Workspace, WorkspaceMember
from app.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    model = Workspace

    async def list_for_owner(self, owner_identity: str) -> list[Workspace]:
        query = (
            select(Workspace)
            .where(Workspace.owner_identity == owner_identity)
            .order_by(Workspace.is_default.desc(), Workspace.name.asc())
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_accessible(self, user_identity: str) -> list[Workspace]:
        """Workspaces this identity owns OR is a member of.

        Membership grants visibility only — a member's workspace still
        shows up here so "accept an invite" isn't a dead end, but this is
        deliberately not used anywhere run-scoped access is decided (see
        app/database/models/workspace_member.py).
        """
        query = (
            select(Workspace)
            .outerjoin(
                WorkspaceMember,
                WorkspaceMember.workspace_id == Workspace.id,
            )
            .where(
                or_(
                    Workspace.owner_identity == user_identity,
                    WorkspaceMember.user_identity == user_identity,
                )
            )
            .distinct()
            .order_by(Workspace.is_default.desc(), Workspace.name.asc())
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_accessible(
        self, workspace_id: uuid.UUID, user_identity: str
    ) -> Workspace | None:
        """Same owner-or-member visibility as ``list_accessible``, for a
        single workspace (GET /workspaces/{id})."""
        owned = await self.get_owned(workspace_id, user_identity)
        if owned is not None:
            return owned
        query = (
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(
                Workspace.id == workspace_id,
                WorkspaceMember.user_identity == user_identity,
            )
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_owner_and_name(
        self, owner_identity: str, name: str
    ) -> Workspace | None:
        query = select(Workspace).where(
            Workspace.owner_identity == owner_identity, Workspace.name == name
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_default_for_owner(self, owner_identity: str) -> Workspace | None:
        query = select(Workspace).where(
            Workspace.owner_identity == owner_identity, Workspace.is_default.is_(True)
        )
        result = await self._session.execute(query)
        return result.scalars().first()

    async def get_owned(
        self, workspace_id: uuid.UUID, owner_identity: str
    ) -> Workspace | None:
        query = select(Workspace).where(
            Workspace.id == workspace_id, Workspace.owner_identity == owner_identity
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_github_repo_full_name(self, repo_full_name: str) -> Workspace | None:
        """docs/FUTURE_GITHUB_INTEGRATION_PLAN.md — one repo maps to at most
        one workspace (enforced by a partial unique index on the column)."""
        query = select(Workspace).where(
            Workspace.github_repo_full_name == repo_full_name
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()
