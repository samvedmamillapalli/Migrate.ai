from __future__ import annotations

import enum
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class SslMode(str, enum.Enum):
    DISABLE = "disable"
    ALLOW = "allow"
    PREFER = "prefer"
    REQUIRE = "require"
    VERIFY_CA = "verify-ca"
    VERIFY_FULL = "verify-full"


class DatabaseConnection(BaseModel):
    """Customer database connection parameters (never persisted with password).

    The application builds SQLAlchemy/psycopg URLs from these fields. Passwords
    are held as ``SecretStr`` and must never be written to logs.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    host: str = Field(min_length=1)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1)
    username: str = Field(min_length=1)
    password: SecretStr
    ssl_mode: SslMode = SslMode.REQUIRE

    @field_validator("host", "database", "username")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    def to_database_url(self) -> str:
        """Build a postgresql:// URL for schema analysis."""
        user = quote(self.username, safe="")
        password = quote(self.password.get_secret_value(), safe="")
        database = quote(self.database, safe="")
        return (
            f"postgresql://{user}:{password}"
            f"@{self.host}:{self.port}/{database}"
            f"?sslmode={self.ssl_mode.value}"
        )

    def safe_log_fields(self) -> dict[str, str]:
        """Host/database only — safe for structured logs."""
        return {"host": self.host, "database": self.database}

    def redacted_label(self) -> str:
        """Human-readable target without password."""
        return f"{self.host}/{self.database}"

    def __repr__(self) -> str:
        return (
            "DatabaseConnection("
            f"host={self.host!r}, port={self.port}, "
            f"database={self.database!r}, username={self.username!r}, "
            f"password=***, ssl_mode={self.ssl_mode.value!r})"
        )
