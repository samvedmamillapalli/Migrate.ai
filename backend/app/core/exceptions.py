from __future__ import annotations


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    """Raised when a requested entity does not exist."""


class ValidationError(AppError):
    """Raised when input fails domain validation."""


class ConflictError(AppError):
    """Raised when an operation conflicts with current state."""


class UnauthorizedError(AppError):
    """Raised when authentication is missing or invalid."""


class ReadWriteCredentialsError(AppError):
    """Raised when customer database credentials allow writes."""


class SchemaConnectionError(AppError):
    """Base error for customer-database connectivity failures."""


class SchemaAuthenticationError(SchemaConnectionError):
    """Invalid username or password."""


class SchemaDatabaseNotFoundError(SchemaConnectionError):
    """Target database does not exist."""


class SchemaTimeoutError(SchemaConnectionError):
    """Connection or discovery timed out."""


class SchemaSSLError(SchemaConnectionError):
    """TLS/SSL handshake or certificate validation failed."""


class SchemaNetworkError(SchemaConnectionError):
    """Host unreachable, connection refused, or similar network failure."""


class UnsupportedDatabaseError(SchemaConnectionError):
    """Database engine or URL scheme is not supported."""


class SlackOAuthError(AppError):
    """Raised when the Slack OAuth exchange or installation fails."""


class SlackStateError(AppError):
    """Raised when the Slack OAuth `state` parameter is invalid or expired."""
