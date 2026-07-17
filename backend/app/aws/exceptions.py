from __future__ import annotations

from app.core.exceptions import AppError


class AwsError(AppError):
    """Base error for AWS infrastructure failures."""


class AwsConfigurationError(AwsError):
    """Raised when AWS settings are missing or invalid for the environment."""


class AwsConnectivityError(AwsError):
    """Raised when the control plane cannot reach AWS APIs."""
