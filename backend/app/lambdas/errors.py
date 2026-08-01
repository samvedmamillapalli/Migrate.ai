"""Lambda-specific errors. Secrets must never appear in messages."""

from __future__ import annotations

from app.core.exceptions import AppError


class LambdaHandlerError(AppError):
    """Base error for Lambda handlers."""


class LambdaValidationError(LambdaHandlerError):
    """Invalid or incomplete event payload."""


class LambdaIdempotencyError(LambdaHandlerError):
    """Retry collided with incompatible durable state."""
