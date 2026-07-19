import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.errors import register_exception_handlers
from app.api.middleware import DemoApiKeyMiddleware
from app.api.routes.health import router as health_router
from app.api.routes.runs import router as runs_router
from app.aws import (
    AwsClientFactory,
    AwsConfigurationError,
    get_aws_settings,
    validate_aws_startup,
)
from app.config import PROJECT_ROOT, get_settings
from app.core.logging import get_logger, setup_logging
from app.database import DatabaseSessionManager
from app.prediction.bedrock_client import MockBedrockClient

logger = get_logger(__name__)

FRONTEND_DIR = PROJECT_ROOT / "frontend"


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

    try:
        yield
    finally:
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
    # Outer-most after CORS: gate mutating API when DEMO_API_KEY is set.
    app.add_middleware(DemoApiKeyMiddleware)

    @app.get("/")
    def root() -> dict[str, str]:
        return {"name": settings.app_name, "status": "healthy"}

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(runs_router)

    if FRONTEND_DIR.is_dir():
        app.mount(
            "/ui",
            StaticFiles(directory=str(FRONTEND_DIR), html=True),
            name="smoke-ui",
        )

    return app


app = create_app()
