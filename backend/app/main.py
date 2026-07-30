import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.middleware import DemoApiKeyMiddleware
from app.api.middleware_auth import SessionAuthMiddleware
from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.memories import router as memories_router
from app.api.routes.runs import router as runs_router
from app.aws import (
    AwsClientFactory,
    AwsConfigurationError,
    get_aws_settings,
    validate_aws_startup,
)
from app.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.database import DatabaseSessionManager
from app.prediction.bedrock_client import MockBedrockClient

logger = get_logger(__name__)

# How often the in-process background sweep checks for HOLDING/expired shadow
# clusters. In production this job is a separately-scheduled Lambda (SAM
# template: ShadowSweeperFunction, every 15 minutes) — this loop exists so the
# same reaping happens locally too, at a much tighter interval appropriate for
# testing a several-minute hold window rather than waiting on a 15-minute
# EventBridge schedule. Reuses the exact same ShadowClusterSweeper the
# deployed Lambda uses; nothing here is a separate/parallel implementation.
_SHADOW_SWEEP_INTERVAL_SECONDS = 30.0


async def _shadow_sweep_loop(database, settings) -> None:
    import contextlib
    from datetime import UTC, datetime

    from app.repositories.shadow_cluster_repository import ShadowClusterRepository
    from app.services.shadow_cluster_service import ShadowClusterService
    from app.shadow.factory import create_shadow_provider, provider_choice_for_name

    while True:
        await asyncio.sleep(_SHADOW_SWEEP_INTERVAL_SECONDS)
        try:
            async with contextlib.aclosing(database.session()) as gen:
                session = await gen.__anext__()
                service = ShadowClusterService(
                    repository=ShadowClusterRepository(session), session=session
                )

                # Group by each row's *own* stored provider — not the current
                # SHADOW_PROVIDER setting — since a mock-provider cluster
                # (e.g. from verify-local, which only overrides the setting
                # for its own duration) and a real ccloud_api cluster can both
                # be active at once in this dev environment, and destroying
                # one with the other's provider fails outright (confirmed:
                # calling the real Cloud API DELETE with a mock database name
                # 400s). Production deployments only ever use one
                # SHADOW_PROVIDER, so this grouping is a no-op there.
                expired = await service.list_expired_active(datetime.now(UTC))
                by_provider: dict[str, list] = {}
                for row in expired:
                    by_provider.setdefault(row.provider, []).append(row)

                reaped = 0
                for provider_name, rows in by_provider.items():
                    provider = create_shadow_provider(
                        settings,
                        provider_choice=provider_choice_for_name(provider_name),
                    )
                    try:
                        for row in rows:
                            await service.teardown_now(row.id, provider=provider)
                            reaped += 1
                    finally:
                        await provider.aclose()

                if reaped:
                    logger.info(
                        "Background shadow sweep reaped expired clusters",
                        extra={"count": reaped},
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one bad tick must not kill the loop
            logger.warning("Background shadow sweep tick failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    aws_settings = get_aws_settings()
    database = DatabaseSessionManager(settings.database_url.get_secret_value())
    app.state.database = database
    app.state.aws_settings = aws_settings
    app.state.aws_clients = None
    app.state.bedrock_client = None

    # Development convenience: injectable mock Bedrock so Phase 9 can be
    # exercised from the smoke UI without live model access.
    if (
        settings.environment.strip().lower() in {"development", "dev", "local", "test"}
        and not aws_settings.bedrock_prediction_model_id
    ):
        app.state.bedrock_client = MockBedrockClient()
        logger.info(
            "Using MockBedrockClient (no BEDROCK_PREDICTION_MODEL_ID in development)"
        )

    if aws_settings.aws_enabled:
        try:
            app.state.aws_clients = AwsClientFactory(aws_settings)
        except AwsConfigurationError:
            logger.exception(
                "Failed to initialize AWS client factory",
                extra={
                    "environment": settings.environment,
                    "aws_region": aws_settings.region,
                    "aws_auth_mode": aws_settings.auth_mode,
                },
            )
            if settings.environment.strip().lower() in {"production", "prod"}:
                raise

    logger.info(
        "Starting %s",
        settings.app_name,
        extra={
            "environment": settings.environment,
            "aws_enabled": aws_settings.aws_enabled,
            "aws_region": aws_settings.region,
            "aws_auth_mode": aws_settings.auth_mode,
        },
    )

    await validate_aws_startup(
        aws_settings,
        app.state.aws_clients,
        environment=settings.environment,
    )

    # Phase 9: load and validate the committed policy YAML at startup.
    # Malformed policy must fail loudly — no permissive fallback.
    from app.policy import get_policy_file
    from app.grading import get_grading_file

    policy = get_policy_file()
    grading = get_grading_file()
    logger.info(
        "Loaded migration policy",
        extra={
            "policy_version": policy.version,
            "policy_rule_count": len(policy.rules),
        },
    )
    logger.info(
        "Loaded grading config",
        extra={
            "grading_version": grading.version,
            "retrieval_final_limit": grading.retrieval.final_limit,
            "candidate_pool_size": grading.retrieval.candidate_pool_size,
        },
    )

    # Curated open-source corpus (Temporal index incident, etc.) for hybrid retrieval.
    try:
        from app.memory.open_source_corpus import ensure_open_source_corpus

        async for session in database.session():
            result = await ensure_open_source_corpus(session, aws_settings=aws_settings)
            if result.get("seeded") or result.get("repaired_embeddings"):
                logger.info(
                    "Open-source corpus ensured",
                    extra=result,
                )
            break
    except Exception:
        logger.warning("Open-source corpus seed skipped (non-fatal)", exc_info=True)

    sweep_task = asyncio.create_task(_shadow_sweep_loop(database, settings))

    try:
        yield
    finally:
        sweep_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweep_task
        aws_clients: AwsClientFactory | None = app.state.aws_clients
        if aws_clients is not None:
            aws_clients.close()
        await database.close()
        logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Outer-most after CORS: session auth (when enabled), then optional demo API key.
    app.add_middleware(DemoApiKeyMiddleware)
    app.add_middleware(SessionAuthMiddleware)

    @app.get("/")
    def root() -> dict[str, str]:
        return {"name": settings.app_name, "status": "healthy"}

    register_exception_handlers(app)
    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(runs_router)
    app.include_router(memories_router)

    # Legacy static /ui console retired — operators use the Next.js app
    # (frontend/oracle). Keep frontend/ on disk only as historical reference.

    return app


app = create_app()
