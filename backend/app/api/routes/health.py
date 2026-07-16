from fastapi import APIRouter, Request, Response, status

from app.core.logging import get_logger
from app.database import DatabaseSessionManager

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/health")
async def health_check(request: Request, response: Response) -> dict[str, str]:
    database: DatabaseSessionManager = request.app.state.database
    try:
        version = await database.check_connection()
    except Exception:
        logger.exception("Database health check failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unhealthy",
            "database": "unhealthy",
            "cockroachdb_version": "unavailable",
        }

    return {
        "status": "healthy",
        "database": "healthy",
        "cockroachdb_version": version,
    }
