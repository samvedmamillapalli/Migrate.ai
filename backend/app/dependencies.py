from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.aws import AwsClientFactory, AwsSettings, get_aws_settings
from app.aws.exceptions import AwsConfigurationError
from app.database import DatabaseSessionManager
from app.prediction.bedrock_client import AwsBedrockClient, BedrockClient, MockBedrockClient
from app.repositories.approval_repository import ApprovalRepository
from app.repositories.execution_result_repository import ExecutionResultRepository
from app.repositories.grade_repository import GradeRepository
from app.repositories.migration_memory_repository import MigrationMemoryRepository
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.prediction_repository import PredictionRepository
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.services.approval_service import ApprovalService
from app.services.closed_loop_service import ClosedLoopService
from app.services.execution_service import ExecutionService
from app.services.grading_pipeline_service import GradingPipelineService
from app.services.migration_run_service import MigrationRunService
from app.services.prediction_pipeline_service import PredictionPipelineService
from app.services.schema_discovery_service import SchemaDiscoveryService
from app.services.shadow_cluster_service import ShadowClusterService
from app.services.workflow_orchestration_service import WorkflowOrchestrationService
from app.services.local_shadow_verify_service import LocalShadowVerifyService
from app.memory.embedding_client import (
    AwsTitanEmbeddingClient,
    EmbeddingClient,
    MockEmbeddingClient,
)
from app.memory.retrieval import HybridMemoryRetrieval
from app.memory.writer import MemoryWriteService
from app.prediction.memory import MemoryRetrieval


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


def get_prediction_repository(session: DbSession) -> PredictionRepository:
    return PredictionRepository(session)


PredictionRepo = Annotated[PredictionRepository, Depends(get_prediction_repository)]


def get_approval_repository(session: DbSession) -> ApprovalRepository:
    return ApprovalRepository(session)


ApprovalRepo = Annotated[ApprovalRepository, Depends(get_approval_repository)]


def get_bedrock_client(request: Request, aws_settings: AwsSettingsDep) -> BedrockClient:
    """Return an injectable Bedrock client.

    Prefer ``app.state.bedrock_client`` when set (tests / verification scripts).
    Otherwise construct a live AwsBedrockClient from settings.
    """
    override = getattr(request.app.state, "bedrock_client", None)
    if override is not None:
        return override

    try:
        return AwsBedrockClient(settings=aws_settings)
    except AwsConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc


BedrockClientDep = Annotated[BedrockClient, Depends(get_bedrock_client)]


def get_embedding_client(
    request: Request,
    aws_settings: AwsSettingsDep,
) -> EmbeddingClient:
    override = getattr(request.app.state, "embedding_client", None)
    if override is not None:
        return override
    settings = getattr(request.app.state, "settings", None)
    env = ""
    if settings is not None:
        env = str(getattr(settings, "environment", "")).strip().lower()
    allow_mock = env in {"development", "dev", "local", "test"}
    try:
        if allow_mock and not (
            aws_settings.bedrock_embedding_model_id and aws_settings.aws_enabled
        ):
            return MockEmbeddingClient()
        return AwsTitanEmbeddingClient(settings=aws_settings)
    except AwsConfigurationError as exc:
        if allow_mock:
            return MockEmbeddingClient()
        raise
    except Exception as exc:
        if allow_mock:
            return MockEmbeddingClient()
        raise RuntimeError(
            "Failed to construct AwsTitanEmbeddingClient; "
            "refusing MockEmbeddingClient outside local/dev"
        ) from exc


EmbeddingClientDep = Annotated[EmbeddingClient, Depends(get_embedding_client)]


def get_memory_retrieval(
    request: Request,
    session: DbSession,
    embedding: EmbeddingClientDep,
) -> MemoryRetrieval:
    override = getattr(request.app.state, "memory_retrieval", None)
    if override is not None:
        return override
    return HybridMemoryRetrieval(
        session=session,
        embedding_client=embedding,
        repository=MigrationMemoryRepository(session),
    )


MemoryRetrievalDep = Annotated[MemoryRetrieval, Depends(get_memory_retrieval)]


def get_prediction_pipeline_service(
    session: DbSession,
    run_repo: MigrationRunRepo,
    prediction_repo: PredictionRepo,
    run_service: MigrationRunSvc,
    bedrock: BedrockClientDep,
    aws_settings: AwsSettingsDep,
    memory: MemoryRetrievalDep,
) -> PredictionPipelineService:
    model_id = aws_settings.bedrock_prediction_model_id
    if not model_id and not isinstance(bedrock, MockBedrockClient):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "BEDROCK_PREDICTION_MODEL_ID is not set. Request Anthropic model "
                "access in the Bedrock console, then configure the model id."
            ),
        )
    return PredictionPipelineService(
        session=session,
        migration_run_repository=run_repo,
        prediction_repository=prediction_repo,
        migration_run_service=run_service,
        bedrock_client=bedrock,
        prediction_model_id=model_id or "mock-model",
        recommendation_model_id=aws_settings.bedrock_recommendation_model_id,
        memory_retrieval=memory,
    )


PredictionPipelineSvc = Annotated[
    PredictionPipelineService,
    Depends(get_prediction_pipeline_service),
]


def get_grade_repository(session: DbSession) -> GradeRepository:
    return GradeRepository(session)


GradeRepo = Annotated[GradeRepository, Depends(get_grade_repository)]


def get_memory_repository(session: DbSession) -> MigrationMemoryRepository:
    return MigrationMemoryRepository(session)


MemoryRepo = Annotated[MigrationMemoryRepository, Depends(get_memory_repository)]


def get_memory_write_service(
    session: DbSession,
    memory_repo: MemoryRepo,
    embedding: EmbeddingClientDep,
    aws_settings: AwsSettingsDep,
) -> MemoryWriteService:
    return MemoryWriteService(
        session=session,
        repository=memory_repo,
        embedding_client=embedding,
        embedding_model_id=aws_settings.bedrock_embedding_model_id,
    )


MemoryWriteSvc = Annotated[MemoryWriteService, Depends(get_memory_write_service)]


def get_grading_pipeline_service(
    session: DbSession,
    run_repo: MigrationRunRepo,
    grade_repo: GradeRepo,
    memory_write: MemoryWriteSvc,
    bedrock: BedrockClientDep,
    aws_settings: AwsSettingsDep,
) -> GradingPipelineService:
    return GradingPipelineService(
        session=session,
        migration_run_repository=run_repo,
        grade_repository=grade_repo,
        memory_write_service=memory_write,
        bedrock_client=bedrock,
        prose_model_id=aws_settings.bedrock_prediction_model_id or "mock-model",
    )


GradingPipelineSvc = Annotated[
    GradingPipelineService,
    Depends(get_grading_pipeline_service),
]


def get_execution_service(
    session: DbSession,
    grading: GradingPipelineSvc,
) -> ExecutionService:
    return ExecutionService(
        repository=ExecutionResultRepository(session),
        session=session,
        grading_pipeline=grading,
    )


ExecutionSvc = Annotated[ExecutionService, Depends(get_execution_service)]


def get_approval_service(
    request: Request,
    session: DbSession,
    run_repo: MigrationRunRepo,
    approval_repo: ApprovalRepo,
    run_service: MigrationRunSvc,
) -> ApprovalService:
    workflow = None
    try:
        factory = getattr(request.app.state, "aws_clients", None)
        aws_settings = getattr(request.app.state, "aws_settings", None)
        if (
            factory is not None
            and aws_settings is not None
            and aws_settings.migration_workflow_arn
        ):
            workflow = WorkflowOrchestrationService(
                repository=run_repo,
                session=session,
                aws_clients=factory,
                aws_settings=aws_settings,
            )
    except Exception:  # noqa: BLE001
        workflow = None
    return ApprovalService(
        session=session,
        migration_run_repository=run_repo,
        approval_repository=approval_repo,
        migration_run_service=run_service,
        workflow_orchestration=workflow,
        auto_start_workflow=True,
    )


ApprovalSvc = Annotated[ApprovalService, Depends(get_approval_service)]


def get_closed_loop_service(
    prediction: PredictionPipelineSvc,
    approval: ApprovalSvc,
    request: Request,
    session: DbSession,
    run_repo: MigrationRunRepo,
) -> ClosedLoopService:
    workflow = None
    try:
        factory = getattr(request.app.state, "aws_clients", None)
        aws_settings = getattr(request.app.state, "aws_settings", None)
        if (
            factory is not None
            and aws_settings is not None
            and aws_settings.migration_workflow_arn
        ):
            workflow = WorkflowOrchestrationService(
                repository=run_repo,
                session=session,
                aws_clients=factory,
                aws_settings=aws_settings,
            )
    except Exception:  # noqa: BLE001
        workflow = None
    return ClosedLoopService(
        runs=run_repo,
        prediction=prediction,
        approval=approval,
        workflow=workflow,
    )


ClosedLoopSvc = Annotated[ClosedLoopService, Depends(get_closed_loop_service)]


def get_local_shadow_verify_service(
    session: DbSession,
    run_repo: MigrationRunRepo,
) -> LocalShadowVerifyService:
    return LocalShadowVerifyService(session=session, repository=run_repo)


LocalShadowVerifySvc = Annotated[
    LocalShadowVerifyService, Depends(get_local_shadow_verify_service)
]
