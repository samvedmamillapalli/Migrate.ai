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
        default="http://localhost:3000,http://127.0.0.1:3000",
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

    # --- Phase 7: Shadow cluster orchestration ---
    # Provider selection:
    #   "ccloud_api" - real CockroachDB Cloud REST API provisioning (Phase 7A-7C
    #                  verified). Default: every shadow cluster is a real,
    #                  disposable CockroachDB Cloud cluster.
    #   "mock"       - isolated scratch database on the control-plane cluster.
    #                  Offline-only, kept for optional local demos; not used by
    #                  default and not exercised by the Phase 7 verification.
    # (A third "ccloud" CLI provider was removed 2026-08-02: it never ran —
    #  ccloud_api is the default in .env and hardcoded in the SAM template's
    #  Globals — and its command surface was never verified against a real CLI.
    #  See docs/HACKATHON_INTEGRATION_AUDIT.md §6.4.)
    shadow_provider: str = Field(default="ccloud_api")
    # Tag/name prefix applied to every shadow cluster so the sweeper can find
    # orphans that belong to this application.
    shadow_app_tag: str = Field(default="migration-oracle", min_length=1)
    # Single-region provisioning; colocated with the AWS services used elsewhere.
    shadow_cluster_cloud: str = Field(default="aws")
    shadow_cluster_region: str = Field(default="us-east-1")
    # Concurrency cap: at most this many simultaneous shadow clusters. Overflow
    # waits for a free slot (see ShadowSlotManager) rather than provisioning.
    shadow_max_concurrent: int = Field(default=2, ge=1, le=10)
    # Max cluster lifetime; the sweeper reaps active app-tagged clusters older
    # than this, catching leaks from processes that died before teardown.
    shadow_max_lifetime_minutes: int = Field(default=30, ge=1, le=1440)
    # After execute+measure finish, the cluster is HELD (not torn down) for
    # this long so the row-sample/schema-diff box stays inspectable — the
    # sweeper reaps it once this window closes; a user can also end the hold
    # immediately via POST /runs/{id}/shadow-cluster/teardown-now.
    shadow_hold_minutes: int = Field(default=5, ge=1, le=60)
    # How long a caller will wait for a concurrency slot before giving up.
    shadow_slot_wait_timeout_seconds: int = Field(default=600, ge=1, le=3600)
    shadow_slot_poll_interval_seconds: float = Field(default=2.0, ge=0.1, le=60.0)
    # Provisioning latency is the biggest unknown in this phase; measure it for
    # real. These are safety ceilings, not promises.
    shadow_provision_timeout_seconds: int = Field(default=600, ge=1, le=3600)
    shadow_ready_poll_interval_seconds: float = Field(default=5.0, ge=0.5, le=120.0)
    shadow_seed_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    shadow_migrate_timeout_seconds: int = Field(default=600, ge=1, le=3600)
    # After schema load, insert tier-capped synthetic rows so storage/runtime
    # metrics are meaningful (default on for demo/hackathon).
    shadow_seed_synthetic_rows: bool = Field(default=True)
    # CockroachDB Cloud service-account credential. ``ccloud_api_secret`` is the
    # Bearer token used by the REST provider; ``ccloud_api_key`` is the key id.
    # Secrets: never logged, never committed. Later phases move to Secrets Manager.
    ccloud_api_key: SecretStr | None = Field(default=None)
    ccloud_api_secret: SecretStr | None = Field(default=None)
    # CockroachDB Cloud REST API.
    ccloud_api_base_url: str = Field(default="https://cockroachlabs.cloud")
    # Cluster plan for shadow provisioning: BASIC is usage-billed (free allowance).
    shadow_cluster_plan: str = Field(default="BASIC")
    # REST client resiliency.
    ccloud_api_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    ccloud_api_max_retries: int = Field(default=4, ge=0, le=10)
    ccloud_api_backoff_base_seconds: float = Field(default=0.5, ge=0.05, le=10.0)

    # Demo deploy gate (optional). When set, API routes require X-API-Key.
    demo_api_key: str | None = Field(default=None, validation_alias="DEMO_API_KEY")

    # Wave 2 session auth (JWT-like HMAC tokens). Off by default for local demos.
    auth_enabled: bool = Field(default=False, validation_alias="AUTH_ENABLED")
    auth_secret: str | None = Field(default=None, validation_alias="AUTH_SECRET")
    auth_token_ttl_seconds: int = Field(
        default=60 * 60 * 24 * 7,
        ge=300,
        le=60 * 60 * 24 * 30,
        validation_alias="AUTH_TOKEN_TTL_SECONDS",
    )

    # --- Clerk Authentication ---
    # Clerk provides authentication via JWTs. When configured, the backend
    # validates Clerk-issued tokens using the JWKS endpoint.
    clerk_secret_key: str | None = Field(
        default=None,
        validation_alias="CLERK_SECRET_KEY",
    )
    clerk_publishable_key: str | None = Field(
        default=None,
        validation_alias="CLERK_PUBLISHABLE_KEY",
    )
    # Optional: Clerk Frontend API URL (e.g., "clerk.abc123.accounts.dev")
    clerk_frontend_api_url: str | None = Field(
        default=None,
        validation_alias="CLERK_FRONTEND_API_URL",
    )

    # CockroachDB Managed MCP endpoint (hackathon tool #2 alongside Vector Index).
    # Used for documentation and optional job-watch correlation; IDE config lives
    # in .cursor/mcp.json. Runtime job watch uses CRDB SQL (same job surface).
    cockroach_mcp_url: str = Field(
        default="https://cockroachlabs.cloud/mcp",
        validation_alias="COCKROACH_MCP_URL",
    )

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
