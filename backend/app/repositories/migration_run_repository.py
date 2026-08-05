from __future__ import annotations

import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import defer, selectinload

from app.core.exceptions import NotFoundError
from app.database.models import Approval, MigrationRun, MigrationRunStatus
from app.repositories.base import BaseRepository

# Whitelisted sort keys. `duration` and `confidence` live outside the runs
# table (execution_results / the explainability JSONB), so they are expressed
# as explicit SQL rather than a column lookup.
_SORTABLE = {"created_at", "updated_at", "status", "compatibility_risk"}


class MigrationRunRepository(BaseRepository[MigrationRun]):
    """Persistence operations for MigrationRun entities."""

    model = MigrationRun

    def _base_query(
        self,
        *,
        load_children: bool = False,
        load_summary_children: bool = False,
        include_schema_snapshot: bool = True,
    ) -> Select[tuple[MigrationRun]]:
        query = select(MigrationRun)
        if not include_schema_snapshot:
            query = query.options(defer(MigrationRun.schema_snapshot))
        if load_children:
            query = query.options(
                selectinload(MigrationRun.prediction),
                selectinload(MigrationRun.execution_result),
                selectinload(MigrationRun.learned_outcome),
                selectinload(MigrationRun.shadow_cluster),
                selectinload(MigrationRun.approval),
                selectinload(MigrationRun.grade),
                selectinload(MigrationRun.memory),
                selectinload(MigrationRun.workspace),
            )
        elif load_summary_children:
            # Narrow loader for list responses: only the four children whose
            # fields MigrationRunSummaryResponse actually surfaces. selectinload
            # issues one batched IN-query per relationship for the whole page,
            # so this is 4 extra queries total — not 4 per row.
            query = query.options(
                selectinload(MigrationRun.approval),
                selectinload(MigrationRun.grade),
                selectinload(MigrationRun.execution_result),
                selectinload(MigrationRun.shadow_cluster),
            )
        return query

    async def create(self, entity: MigrationRun) -> MigrationRun:
        return await super().create(entity)

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
        *,
        load_children: bool = False,
    ) -> MigrationRun | None:
        if not load_children:
            return await super().get_by_id(entity_id)

        # If the run is already in the identity map with children loaded as
        # None (common after grade/memory writes in the same session), expire
        # those relationships so selectinload sees the new rows.
        existing = await self._session.get(MigrationRun, entity_id)
        if existing is not None:
            for rel in (
                "prediction",
                "execution_result",
                "learned_outcome",
                "shadow_cluster",
                "approval",
                "grade",
                "memory",
            ):
                if rel in existing.__dict__:
                    self._session.expire(existing, [rel])

        query = self._base_query(load_children=True).where(MigrationRun.id == entity_id)
        result = await self._session.execute(
            query.execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(
        self,
        entity_id: uuid.UUID,
        *,
        load_children: bool = False,
    ) -> MigrationRun:
        entity = await self.get_by_id(entity_id, load_children=load_children)
        if entity is None:
            raise NotFoundError(f"MigrationRun not found: {entity_id}")
        return entity

    def _apply_filters(
        self,
        query: Select[tuple[MigrationRun]],
        *,
        status: MigrationRunStatus | None,
        owner_identity: str | None,
        workspace_id: uuid.UUID | None = None,
        status_in: list[MigrationRunStatus] | None = None,
        run_kind: str | None,
        exclude_kinds: list[str] | None,
        search: str | None,
        compatibility_risk: str | None,
        approval_decision: str | None,
        approver_identity: str | None,
    ) -> Select[tuple[MigrationRun]]:
        if status is not None:
            query = query.where(MigrationRun.status == status)
        if status_in:
            query = query.where(MigrationRun.status.in_(status_in))
        if owner_identity is not None:
            query = query.where(MigrationRun.owner_identity == owner_identity)
        if workspace_id is not None:
            query = query.where(MigrationRun.workspace_id == workspace_id)
        if run_kind is not None:
            query = query.where(MigrationRun.run_kind == run_kind)
        if exclude_kinds:
            query = query.where(MigrationRun.run_kind.notin_(exclude_kinds))
        if search:
            # Case-insensitive substring over the SQL text. Covers the table
            # name too, since the table always appears in the statement.
            query = query.where(
                func.lower(MigrationRun.migration_sql).like(f"%{search.lower()}%")
            )
        if compatibility_risk:
            query = query.where(
                MigrationRun.compatibility_risk == compatibility_risk
            )
        # Approval-based filters need the child row. "none" means "no decision
        # recorded yet", which is an outer-join IS NULL rather than an equality.
        if approval_decision == "none":
            query = query.outerjoin(
                Approval, Approval.migration_run_id == MigrationRun.id
            ).where(Approval.id.is_(None))
        elif approval_decision:
            query = query.join(
                Approval, Approval.migration_run_id == MigrationRun.id
            ).where(Approval.decision == approval_decision)
        if approver_identity:
            if not approval_decision or approval_decision == "none":
                query = query.join(
                    Approval, Approval.migration_run_id == MigrationRun.id
                )
            query = query.where(Approval.approver_identity == approver_identity)
        return query

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: MigrationRunStatus | None = None,
        status_in: list[MigrationRunStatus] | None = None,
        owner_identity: str | None = None,
        workspace_id: uuid.UUID | None = None,
        run_kind: str | None = None,
        exclude_kinds: list[str] | None = None,
        search: str | None = None,
        compatibility_risk: str | None = None,
        approval_decision: str | None = None,
        approver_identity: str | None = None,
        order_by: str = "created_at",
        order_dir: str = "desc",
        load_children: bool = False,
        load_summary_children: bool = False,
    ) -> list[MigrationRun]:
        query = self._base_query(
            load_children=load_children,
            load_summary_children=load_summary_children,
            include_schema_snapshot=False,
        )
        query = self._apply_filters(
            query,
            status=status,
            status_in=status_in,
            owner_identity=owner_identity,
            workspace_id=workspace_id,
            run_kind=run_kind,
            exclude_kinds=exclude_kinds,
            search=search,
            compatibility_risk=compatibility_risk,
            approval_decision=approval_decision,
            approver_identity=approver_identity,
        )

        key = order_by if order_by in _SORTABLE else "created_at"
        column = getattr(MigrationRun, key)
        # NULLs last in both directions — an unpredicted run should never sort
        # above a real value just because its risk is unset.
        query = query.order_by(
            column.desc().nullslast()
            if order_dir == "desc"
            else column.asc().nullslast(),
            MigrationRun.created_at.desc(),
        )
        return await super().list(offset=offset, limit=limit, statement=query)

    async def count(
        self,
        *,
        status: MigrationRunStatus | None = None,
        status_in: list[MigrationRunStatus] | None = None,
        owner_identity: str | None = None,
        workspace_id: uuid.UUID | None = None,
        run_kind: str | None = None,
        exclude_kinds: list[str] | None = None,
        search: str | None = None,
        compatibility_risk: str | None = None,
        approval_decision: str | None = None,
        approver_identity: str | None = None,
    ) -> int:
        query = self._apply_filters(
            select(MigrationRun),
            status=status,
            status_in=status_in,
            owner_identity=owner_identity,
            workspace_id=workspace_id,
            run_kind=run_kind,
            exclude_kinds=exclude_kinds,
            search=search,
            compatibility_risk=compatibility_risk,
            approval_decision=approval_decision,
            approver_identity=approver_identity,
        )
        return await super().count(query)

    async def distinct_approvers(
        self,
        *,
        owner_identity: str | None = None,
        workspace_id: uuid.UUID | None = None,
        exclude_kinds: list[str] | None = None,
    ) -> list[str]:
        """Approver identities present in the caller's runs, for a filter list."""
        query = (
            select(Approval.approver_identity)
            .join(MigrationRun, MigrationRun.id == Approval.migration_run_id)
            .distinct()
        )
        if owner_identity is not None:
            query = query.where(MigrationRun.owner_identity == owner_identity)
        if workspace_id is not None:
            query = query.where(MigrationRun.workspace_id == workspace_id)
        if exclude_kinds:
            query = query.where(MigrationRun.run_kind.notin_(exclude_kinds))
        rows = await self._session.execute(query)
        return [r for (r,) in rows.all() if r]

    async def update(self, entity: MigrationRun) -> MigrationRun:
        return await super().update(entity)

    async def delete(self, entity: MigrationRun) -> None:
        await super().delete(entity)

    async def delete_by_id(self, entity_id: uuid.UUID) -> None:
        await super().delete_by_id(entity_id)
