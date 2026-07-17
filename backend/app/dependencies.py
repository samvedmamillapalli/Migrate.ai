from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.aws import AwsClientFactory, AwsSettings, get_aws_settings
from app.database import DatabaseSessionManager
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.services.migration_run_service import MigrationRunService
from app.services.schema_discovery_service import SchemaDiscoveryService
from app.services.shadow_cluster_service import ShadowClusterService
from app.services.workflow_orchestration_service import WorkflowOrchestrationService


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped AsyncSession.

    Commit is owned by the service layer. This dependency only ensures rollback
    when an unhandled exception escapes the request.
    """
    database: DatabaseSessionManager = request.app.state.database
    async for session in database.session():
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_aws_settings_dep(request: Request) -> AwsSettings:
    settings = getattr(request.app.state, "aws_settings", None)
    if settings is None:
        return get_aws_settings()
    return settings


AwsSettingsDep = Annotated[AwsSettings, Depends(get_aws_settings_dep)]


def get_aws_client_factory(request: Request) -> AwsClientFactory:
    """Return the process-scoped AWS client factory.

    Raises 503 when AWS is disabled or failed to initialize so route handlers
    that need AWS fail closed rather than constructing ad-hoc clients.
    """
    factory: AwsClientFactory | None = getattr(request.app.state, "aws_clients", None)
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AWS clients are not available",
        )
    return factory


AwsClients = Annotated[AwsClientFactory, Depends(get_aws_client_factory)]


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


def get_workflow_orchestration_service(
    session: DbSession,
    repository: MigrationRunRepo,
    aws_clients: AwsClients,
    aws_settings: AwsSettingsDep,
) -> WorkflowOrchestrationService:
    return WorkflowOrchestrationService(
        repository=repository,
        session=session,
        aws_clients=aws_clients,
        aws_settings=aws_settings,
    )


WorkflowOrchestrationSvc = Annotated[
    WorkflowOrchestrationService,
    Depends(get_workflow_orchestration_service),
]
