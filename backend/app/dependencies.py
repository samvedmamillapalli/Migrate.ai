from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.aws import AwsClientFactory, AwsSettings, get_aws_settings
from app.aws.exceptions import AwsConfigurationError
from app.config import get_settings
from app.database import DatabaseSessionManager
from app.prediction.bedrock_client import AwsBedrockClient, BedrockClient, MockBedrockClient
from app.repositories.approval_repository import ApprovalRepository
from app.repositories.cross_customer_memory_repository import (
    CrossCustomerMemoryRepository,
)
from app.repositories.execution_result_repository import ExecutionResultRepository
from app.repositories.github_pull_request_link_repository import (
    GithubPullRequestLinkRepository,
)
from app.repositories.grade_repository import GradeRepository
from app.repositories.memory_sharing_preference_repository import (
    MemorySharingPreferenceRepository,
)
from app.repositories.migration_memory_repository import MigrationMemoryRepository
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.prediction_repository import PredictionRepository
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.repositories.slack_installation_repository import SlackInstallationRepository
from app.repositories.workspace_invite_repository import WorkspaceInviteRepository
from app.repositories.workspace_member_repository import WorkspaceMemberRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.approval_service import ApprovalService
from app.services.closed_loop_service import ClosedLoopService
from app.services.cross_customer_promotion_service import CrossCustomerPromotionService
from app.services.email_service import EmailService
from app.services.execution_service import ExecutionService
from app.services.github_notification_service import GithubNotificationService
from app.services.github_webhook_service import GithubWebhookService
from app.services.grading_pipeline_service import GradingPipelineService
from app.services.migration_run_service import MigrationRunService
from app.services.prediction_pipeline_service import PredictionPipelineService
from app.services.schema_discovery_service import SchemaDiscoveryService
from app.services.shadow_cluster_service import ShadowClusterService
from app.services.slack_notification_service import SlackNotificationService
from app.services.slack_oauth_service import SlackOAuthService
from app.services.workflow_orchestration_service import WorkflowOrchestrationService
from app.services.local_shadow_verify_service import LocalShadowVerifyService
from app.services.workspace_invite_service import WorkspaceInviteService
from app.services.workspace_service import WorkspaceService
from app.memory.embedding_client import (
    AwsTitanEmbeddingClient,
    EmbeddingClient,
    MockEmbeddingClient,
)
from app.memory.retrieval import HybridMemoryRetrieval
from app.memory.skills_retrieval import CockroachDBSkillsRetrieval
from app.memory.writer import MemoryWriteService
from app.prediction.memory import MemoryRetrieval
from app.prediction.skills import SkillsRetrieval, StubSkillsRetrieval
from app.repositories.skill_doc_repository import SkillDocRepository


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


def get_workspace_repository(session: DbSession) -> WorkspaceRepository:
    return WorkspaceRepository(session)


WorkspaceRepo = Annotated[WorkspaceRepository, Depends(get_workspace_repository)]


def get_workspace_member_repository(session: DbSession) -> WorkspaceMemberRepository:
    return WorkspaceMemberRepository(session)


WorkspaceMemberRepo = Annotated[
    WorkspaceMemberRepository, Depends(get_workspace_member_repository)
]


def get_workspace_invite_repository(session: DbSession) -> WorkspaceInviteRepository:
    return WorkspaceInviteRepository(session)


WorkspaceInviteRepo = Annotated[
    WorkspaceInviteRepository, Depends(get_workspace_invite_repository)
]


def get_workspace_service(
    session: DbSession,
    repository: WorkspaceRepo,
    member_repository: WorkspaceMemberRepo,
) -> WorkspaceService:
    return WorkspaceService(
        repository=repository, session=session, member_repository=member_repository
    )


WorkspaceSvc = Annotated[WorkspaceService, Depends(get_workspace_service)]


def get_email_service(request: Request) -> EmailService | None:
    """None when AWS isn't available — email is best-effort, and invite
    creation/listing/revocation for every method (not just email) must keep
    working even when this app runs with AWS disabled entirely (local dev),
    same posture as the optional Slack/workflow wiring below."""
    try:
        factory = getattr(request.app.state, "aws_clients", None)
        aws_settings = getattr(request.app.state, "aws_settings", None)
        if factory is not None and aws_settings is not None:
            return EmailService(aws_clients=factory, aws_settings=aws_settings)
    except Exception:  # noqa: BLE001
        pass
    return None


EmailSvc = Annotated[EmailService | None, Depends(get_email_service)]


def get_workspace_invite_service(
    session: DbSession,
    repository: WorkspaceInviteRepo,
    workspace_service: WorkspaceSvc,
    email_service: EmailSvc,
) -> WorkspaceInviteService:
    return WorkspaceInviteService(
        repository=repository,
        workspace_service=workspace_service,
        session=session,
        email_service=email_service,
    )


WorkspaceInviteSvc = Annotated[
    WorkspaceInviteService, Depends(get_workspace_invite_service)
]


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


def get_slack_installation_repository(
    session: DbSession,
) -> SlackInstallationRepository:
    return SlackInstallationRepository(session)


SlackInstallationRepo = Annotated[
    SlackInstallationRepository,
    Depends(get_slack_installation_repository),
]


def get_slack_oauth_service(
    session: DbSession,
    repository: SlackInstallationRepo,
) -> SlackOAuthService:
    return SlackOAuthService(repository=repository, session=session)


SlackOAuthSvc = Annotated[
    SlackOAuthService,
    Depends(get_slack_oauth_service),
]


def get_slack_notification_service(
    session: DbSession,
    repository: SlackInstallationRepo,
    oauth_service: SlackOAuthSvc,
) -> SlackNotificationService:
    """Build the Slack notification service from shared dependencies."""
    return SlackNotificationService(
        repository=repository,
        session=session,
        oauth_service=oauth_service,
    )


SlackNotificationSvc = Annotated[
    SlackNotificationService,
    Depends(get_slack_notification_service),
]


def get_github_pull_request_link_repository(
    session: DbSession,
) -> GithubPullRequestLinkRepository:
    return GithubPullRequestLinkRepository(session)


GithubPullRequestLinkRepo = Annotated[
    GithubPullRequestLinkRepository, Depends(get_github_pull_request_link_repository)
]


def get_github_notification_service(
    session: DbSession,
    pr_link_repository: GithubPullRequestLinkRepo,
) -> GithubNotificationService:
    return GithubNotificationService(
        pr_link_repository=pr_link_repository,
        session=session,
    )


GithubNotificationSvc = Annotated[
    GithubNotificationService, Depends(get_github_notification_service)
]


def get_workflow_orchestration_service(
    session: DbSession,
    repository: MigrationRunRepo,
    aws_clients: AwsClients,
    aws_settings: AwsSettingsDep,
    slack_notifications: SlackNotificationSvc,
    github_notifications: GithubNotificationSvc,
) -> WorkflowOrchestrationService:
    return WorkflowOrchestrationService(
        repository=repository,
        session=session,
        aws_clients=aws_clients,
        aws_settings=aws_settings,
        slack_notifications=slack_notifications,
        github_notifications=github_notifications,
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
        # Anonymized, opt-in cross-tenant pool — docs/cross_customer.md.
        # Optional by construction (HybridMemoryRetrieval degrades to
        # "no cross-customer results" if this were ever None), passed here
        # so the real /predict path actually benefits from it, not just
        # code that supports it in isolation.
        cross_customer_repository=CrossCustomerMemoryRepository(session),
    )


MemoryRetrievalDep = Annotated[MemoryRetrieval, Depends(get_memory_retrieval)]


# CockroachDB Agent Skills Repo retrieval (docs/cockroach_hookup.md §5),
# sidelined 2026-08-02 per user decision: proven live and functional, but
# judged not impactful enough to a core feature to keep active. Flip this
# back to True to re-enable — CockroachDBSkillsRetrieval below is untouched
# and fully tested.
_AGENT_SKILLS_ENABLED = False


def get_skills_retrieval(
    request: Request,
    session: DbSession,
    embedding: EmbeddingClientDep,
) -> SkillsRetrieval:
    override = getattr(request.app.state, "skills_retrieval", None)
    if override is not None:
        return override
    if not _AGENT_SKILLS_ENABLED:
        return StubSkillsRetrieval()
    return CockroachDBSkillsRetrieval(
        session=session,
        embedding_client=embedding,
        repository=SkillDocRepository(session),
    )


SkillsRetrievalDep = Annotated[SkillsRetrieval, Depends(get_skills_retrieval)]


def get_prediction_pipeline_service(
    session: DbSession,
    run_repo: MigrationRunRepo,
    prediction_repo: PredictionRepo,
    run_service: MigrationRunSvc,
    bedrock: BedrockClientDep,
    aws_settings: AwsSettingsDep,
    memory: MemoryRetrievalDep,
    skills: SkillsRetrievalDep,
    slack_notifications: SlackNotificationSvc,
    github_notifications: GithubNotificationSvc,
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
        skills_retrieval=skills,
        slack_notifications=slack_notifications,
        github_notifications=github_notifications,
    )


PredictionPipelineSvc = Annotated[
    PredictionPipelineService,
    Depends(get_prediction_pipeline_service),
]


def get_github_webhook_service(
    session: DbSession,
    workspace_repository: WorkspaceRepo,
    pr_link_repository: GithubPullRequestLinkRepo,
    migration_run_service: MigrationRunSvc,
    discovery: SchemaDiscoverySvc,
    prediction: PredictionPipelineSvc,
) -> GithubWebhookService:
    return GithubWebhookService(
        session=session,
        workspace_repository=workspace_repository,
        pr_link_repository=pr_link_repository,
        migration_run_service=migration_run_service,
        discovery_service=discovery,
        prediction_service=prediction,
        settings=get_settings(),
    )


GithubWebhookSvc = Annotated[
    GithubWebhookService, Depends(get_github_webhook_service)
]


def build_github_webhook_service_for_session(
    request: Request, session: AsyncSession
) -> GithubWebhookService:
    """Build the webhook service against a caller-supplied session.

    The webhook route answers GitHub immediately and does the real work
    (discover + two Bedrock calls) afterwards, because GitHub's delivery
    timeout is 10s and that work takes far longer. By the time the
    background work runs, the request-scoped session from ``get_db_session``
    is already closed — so that path opens its own session and rebuilds the
    service here, reusing the exact same dependency factories the normal
    request path uses rather than duplicating their wiring.

    ``request`` is only read for ``request.app.state`` (app-scoped: AWS
    clients, settings, test overrides), which stays valid after the response
    has been sent.
    """
    aws_settings = get_aws_settings_dep(request)
    run_repo = MigrationRunRepository(session)
    embedding = get_embedding_client(request, aws_settings)
    slack_notifications = get_slack_notification_service(
        session,
        SlackInstallationRepository(session),
        get_slack_oauth_service(session, SlackInstallationRepository(session)),
    )
    github_notifications = get_github_notification_service(
        session, GithubPullRequestLinkRepository(session)
    )
    prediction = get_prediction_pipeline_service(
        session=session,
        run_repo=run_repo,
        prediction_repo=PredictionRepository(session),
        run_service=MigrationRunService(repository=run_repo, session=session),
        bedrock=get_bedrock_client(request, aws_settings),
        aws_settings=aws_settings,
        memory=get_memory_retrieval(request, session, embedding),
        skills=get_skills_retrieval(request, session, embedding),
        slack_notifications=slack_notifications,
        github_notifications=github_notifications,
    )
    return GithubWebhookService(
        session=session,
        workspace_repository=WorkspaceRepository(session),
        pr_link_repository=GithubPullRequestLinkRepository(session),
        migration_run_service=MigrationRunService(
            repository=run_repo, session=session
        ),
        discovery_service=SchemaDiscoveryService(
            repository=run_repo, session=session
        ),
        prediction_service=prediction,
        settings=get_settings(),
    )


def get_grade_repository(session: DbSession) -> GradeRepository:
    return GradeRepository(session)


GradeRepo = Annotated[GradeRepository, Depends(get_grade_repository)]


def get_memory_repository(session: DbSession) -> MigrationMemoryRepository:
    return MigrationMemoryRepository(session)


MemoryRepo = Annotated[MigrationMemoryRepository, Depends(get_memory_repository)]


def get_cross_customer_promotion_service(
    session: DbSession,
    bedrock: BedrockClientDep,
    embedding: EmbeddingClientDep,
    aws_settings: AwsSettingsDep,
) -> CrossCustomerPromotionService:
    """docs/cross_customer.md §5 — the automatic promotion hook's service.

    Same model-id fallback already used for prediction/recommendation calls
    elsewhere in this module (recommendation model first, prediction model
    as a fallback) since generalization is a recommendation-shaped task, not
    a from-scratch prediction.
    """
    return CrossCustomerPromotionService(
        session=session,
        cross_customer_repository=CrossCustomerMemoryRepository(session),
        sharing_preference_repository=MemorySharingPreferenceRepository(session),
        bedrock_client=bedrock,
        bedrock_model_id=(
            aws_settings.bedrock_recommendation_model_id
            or aws_settings.bedrock_prediction_model_id
            or "mock-model"
        ),
        embedding_client=embedding,
        embedding_model_id=aws_settings.bedrock_embedding_model_id,
    )


CrossCustomerPromotionSvc = Annotated[
    CrossCustomerPromotionService, Depends(get_cross_customer_promotion_service)
]


def get_memory_write_service(
    session: DbSession,
    memory_repo: MemoryRepo,
    embedding: EmbeddingClientDep,
    aws_settings: AwsSettingsDep,
    cross_customer_promotion: CrossCustomerPromotionSvc,
) -> MemoryWriteService:
    return MemoryWriteService(
        session=session,
        repository=memory_repo,
        embedding_client=embedding,
        embedding_model_id=aws_settings.bedrock_embedding_model_id,
        cross_customer_promotion=cross_customer_promotion,
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
    slack_notifications: SlackNotificationSvc,
    github_notifications: GithubNotificationSvc,
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
                slack_notifications=slack_notifications,
                github_notifications=github_notifications,
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
    slack_notifications: SlackNotificationSvc,
    github_notifications: GithubNotificationSvc,
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
                slack_notifications=slack_notifications,
                github_notifications=github_notifications,
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
