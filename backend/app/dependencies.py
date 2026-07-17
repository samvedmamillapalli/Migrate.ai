from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseSessionManager
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.services.migration_run_service import MigrationRunService
from app.services.schema_discovery_service import SchemaDiscoveryService
from app.services.shadow_cluster_service import ShadowClusterService


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped AsyncSession.

    Commit is owned by the service layer. This dependency only ensures rollback
    when an unhandled exception escapes the request.
    """
    database: DatabaseSessionManager = request.app.state.database
    async for session in database.session():
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_migration_run_repository(session: DbSession) -> MigrationRunRepository:
    return MigrationRunRepository(session)


MigrationRunRepo = Annotated[
    MigrationRunRepository,
    Depends(get_migration_run_repository),
]


def get_migration_run_service(
    session: DbSession,
    repository: MigrationRunRepo,
) -> MigrationRunService:
    return MigrationRunService(repository=repository, session=session)


MigrationRunSvc = Annotated[MigrationRunService, Depends(get_migration_run_service)]


def get_schema_discovery_service(
    session: DbSession,
    repository: MigrationRunRepo,
) -> SchemaDiscoveryService:
    return SchemaDiscoveryService(repository=repository, session=session)


SchemaDiscoverySvc = Annotated[
    SchemaDiscoveryService,
    Depends(get_schema_discovery_service),
]


def get_shadow_cluster_repository(session: DbSession) -> ShadowClusterRepository:
    return ShadowClusterRepository(session)


ShadowClusterRepo = Annotated[
    ShadowClusterRepository,
    Depends(get_shadow_cluster_repository),
]


def get_shadow_cluster_service(
    session: DbSession,
    repository: ShadowClusterRepo,
) -> ShadowClusterService:
    return ShadowClusterService(repository=repository, session=session)


ShadowClusterSvc = Annotated[
    ShadowClusterService,
    Depends(get_shadow_cluster_service),
]
