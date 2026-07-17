import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.routes.health import router as health_router
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

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    aws_settings = get_aws_settings()
    database = DatabaseSessionManager(settings.database_url.get_secret_value())
    app.state.database = database
    app.state.aws_settings = aws_settings
    app.state.aws_clients = None

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

    @app.get("/")
    def root() -> dict[str, str]:
        return {"name": settings.app_name, "status": "healthy"}

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(runs_router)

    return app


app = create_app()
