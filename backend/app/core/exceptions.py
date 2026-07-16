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
