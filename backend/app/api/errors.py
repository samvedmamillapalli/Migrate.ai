from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.aws.exceptions import AwsConfigurationError, AwsConnectivityError
from app.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    ReadWriteCredentialsError,
    SchemaAuthenticationError,
    SchemaConnectionError,
    SchemaDatabaseNotFoundError,
    SchemaNetworkError,
    SchemaSSLError,
    SchemaTimeoutError,
    UnsupportedDatabaseError,
    ValidationError,
)
from app.core.logging import get_logger
from app.policy.config import PolicyConfigError
from app.grading.config import GradingConfigError
from app.prediction.bedrock_client import BedrockAccessError, BedrockInvocationError
from app.prediction.predictor import PredictionValidationError
from app.prediction.recommender import RecommendationValidationError
from app.memory.embedding_client import EmbeddingAccessError, EmbeddingInvocationError

logger = get_logger(__name__)

_HTTP_422_UNPROCESSABLE = 422

_STATUS_BY_ERROR: dict[type[AppError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ValidationError: _HTTP_422_UNPROCESSABLE,
    ConflictError: status.HTTP_409_CONFLICT,
    ReadWriteCredentialsError: status.HTTP_403_FORBIDDEN,
    SchemaAuthenticationError: status.HTTP_401_UNAUTHORIZED,
    SchemaDatabaseNotFoundError: status.HTTP_404_NOT_FOUND,
    SchemaTimeoutError: status.HTTP_408_REQUEST_TIMEOUT,
    SchemaSSLError: status.HTTP_400_BAD_REQUEST,
    SchemaNetworkError: status.HTTP_503_SERVICE_UNAVAILABLE,
    UnsupportedDatabaseError: status.HTTP_400_BAD_REQUEST,
    SchemaConnectionError: status.HTTP_400_BAD_REQUEST,
    AwsConfigurationError: status.HTTP_503_SERVICE_UNAVAILABLE,
    AwsConnectivityError: status.HTTP_503_SERVICE_UNAVAILABLE,
    BedrockAccessError: status.HTTP_503_SERVICE_UNAVAILABLE,
    BedrockInvocationError: status.HTTP_502_BAD_GATEWAY,
    PredictionValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    RecommendationValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    PolicyConfigError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    GradingConfigError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    EmbeddingAccessError: status.HTTP_503_SERVICE_UNAVAILABLE,
    EmbeddingInvocationError: status.HTTP_502_BAD_GATEWAY,
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        for error_type in type(exc).__mro__:
            if error_type in _STATUS_BY_ERROR:
                status_code = _STATUS_BY_ERROR[error_type]
                break

        if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.exception(
                "Unhandled application error",
                extra={"error": exc.message},
            )
        return JSONResponse(
            status_code=status_code,
            content={"detail": exc.message},
        )
