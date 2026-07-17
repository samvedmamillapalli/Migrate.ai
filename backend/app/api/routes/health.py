from typing import Any

from fastapi import APIRouter, Request, Response, status

from app.aws import AwsClientFactory, AwsSettings, aws_health_snapshot
from app.config import get_settings
from app.core.logging import get_logger
from app.database import DatabaseSessionManager

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/health")
async def health_check(request: Request, response: Response) -> dict[str, Any]:
    database: DatabaseSessionManager = request.app.state.database
    aws_settings: AwsSettings = request.app.state.aws_settings
    aws_clients: AwsClientFactory | None = request.app.state.aws_clients
    settings = get_settings()

    try:
        version = await database.check_connection()
        database_status = "healthy"
    except Exception:
        logger.exception("Database health check failed")
        version = "unavailable"
        database_status = "unhealthy"

    aws_status = await aws_health_snapshot(aws_settings, aws_clients)

    overall = "healthy"
    if database_status != "healthy":
        overall = "unhealthy"
    elif (
        aws_settings.aws_enabled
        and aws_status.get("status") == "unhealthy"
        and settings.environment.strip().lower() in {"production", "prod"}
    ):
        # Production treats AWS as required infrastructure. Development may
        # still report database-healthy when AWS credentials are absent.
        overall = "unhealthy"

    if overall != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": overall,
        "database": database_status,
        "cockroachdb_version": version,
        "aws": aws_status,
    }
