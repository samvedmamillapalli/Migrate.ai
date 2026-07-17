import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Migration Oracle"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    cors_origins_value: str = Field(
        default="http://localhost:3000",
        validation_alias="CORS_ORIGINS",
        exclude=True,
    )
    database_url: SecretStr = Field(
        default=(
            "postgresql://root@localhost:26257/migration_oracle?sslmode=disable"
        )
    )

    # Customer schema discovery timeouts (seconds)
    schema_connection_timeout_seconds: int = Field(default=30, ge=1, le=300)
    schema_discovery_timeout_seconds: int = Field(default=60, ge=1, le=600)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError(f"Invalid log level: {value}")
        return normalized

    @computed_field
    @property
    def cors_origins(self) -> list[str]:
        origins = [
            origin.strip()
            for origin in self.cors_origins_value.split(",")
            if origin.strip()
        ]
        for origin in origins:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"Invalid CORS origin: {origin}")
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
