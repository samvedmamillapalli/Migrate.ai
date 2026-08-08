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
    # Optional per-owner cap, additive on top of the global cap above — unset
    # (default) means no per-owner limit, identical to today's behavior. Only
    # meaningful when set below shadow_max_concurrent; the point is fairness
    # (one owner can't exhaust every slot), not extra total capacity — raising
    # the global cap is the lever for more total capacity, not this one.
    shadow_max_concurrent_per_owner: int | None = Field(default=None, ge=1, le=10)
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

    # --- Slack OAuth Integration ---
    # Slack App OAuth v2 credentials and callback configuration. The bot
    # access token is encrypted at rest with `slack_token_encryption_key`
    # (a Fernet key) before persistence. `slack_state_secret` signs the
    # OAuth `state` parameter so Slack's callback can be validated against
    # CSRF / login-tampering.
    slack_client_id: str | None = Field(
        default=None,
        validation_alias="SLACK_CLIENT_ID",
    )
    slack_client_secret: SecretStr | None = Field(
        default=None,
        validation_alias="SLACK_CLIENT_SECRET",
    )
    slack_redirect_uri: str | None = Field(
        default=None,
        validation_alias="SLACK_REDIRECT_URI",
    )
    # Fernet key (base64, 32 url-safe bytes) used to encrypt the bot token.
    # When unset in non-production, tokens are stored plaintext with a warning.
    slack_token_encryption_key: SecretStr | None = Field(
        default=None,
        validation_alias="SLACK_TOKEN_ENCRYPTION_KEY",
    )
    # Secret used to sign/verify the OAuth `state` parameter (HMAC-SHA256).
    slack_state_secret: str | None = Field(
        default=None,
        validation_alias="SLACK_STATE_SECRET",
    )
    # Minimum Slack OAuth v2 bot scopes requested during installation.
    slack_bot_scope: str = Field(
        default="chat:write",
        validation_alias="SLACK_BOT_SCOPE",
    )
    # Where to send the browser after OAuth completes.
    slack_install_success_redirect: str = Field(
        default="/dashboard/settings?slack=connected",
        validation_alias="SLACK_INSTALL_SUCCESS_REDIRECT",
    )
    slack_install_error_redirect: str = Field(
        default="/dashboard/settings?slack=error",
        validation_alias="SLACK_INSTALL_ERROR_REDIRECT",
    )
    # How long an issued `state` value is valid before it expires.
    slack_state_ttl_seconds: int = Field(
        default=600,
        ge=60,
        le=3600,
        validation_alias="SLACK_STATE_TTL_SECONDS",
    )
    # Public base URL of the web app, used to build deep links in Slack
    # notifications (e.g. the "Open in Migration Oracle" button).
    frontend_url: str = Field(
        default="http://localhost:3000",
        validation_alias="FRONTEND_URL",
    )
    # Last-resort fallback channel for lifecycle notifications, used only
    # when SlackNotificationService has no explicit channel and the
    # installation predates the authed_user_id column (see
    # slack_installations migration q2l8i5d9e6a7) — the normal path DMs the
    # user who completed the OAuth install instead of posting to a named
    # channel, which requires no scope beyond chat:write and cannot fail
    # with not_in_channel the way an un-joined named channel can.
    slack_default_channel: str = Field(
        default="general",
        validation_alias="SLACK_DEFAULT_CHANNEL",
    )

    # --- GitHub App Integration ---
    # docs/FUTURE_GITHUB_INTEGRATION_PLAN.md. A GitHub App (not OAuth, not a
    # personal access token) receives `pull_request` webhooks and posts back
    # a PR comment + check run. Unlike Slack, there is no user-driven OAuth
    # install flow here: a repo owner installs the App on github.com, and the
    # link to a Migration Oracle workspace is made explicitly in-app via
    # `Workspace.github_repo_full_name` (see app/database/models/workspace.py).
    github_app_id: str | None = Field(
        default=None,
        validation_alias="GITHUB_APP_ID",
    )
    # PEM-encoded RSA private key downloaded once at App-registration time.
    # Used to sign short-lived JWTs (RS256) that are exchanged for
    # per-installation access tokens — never stored or transmitted itself.
    github_app_private_key: SecretStr | None = Field(
        default=None,
        validation_alias="GITHUB_APP_PRIVATE_KEY",
    )
    # HMAC-SHA256 secret configured on the App's webhook settings page.
    # Every inbound webhook's `X-Hub-Signature-256` header is verified
    # against this before the payload is trusted at all.
    github_webhook_secret: SecretStr | None = Field(
        default=None,
        validation_alias="GITHUB_WEBHOOK_SECRET",
    )
    github_api_base_url: str = Field(
        default="https://api.github.com",
        validation_alias="GITHUB_API_BASE_URL",
    )

    # --- GitHub OAuth Identity ("who is this GitHub identity") ---
    # A *different* credential pair from the App above: this is a standard
    # OAuth 2.0 web-application flow (client_id/client_secret), used only to
    # verify which GitHub account a user is, for workspace-invite matching
    # (e.g. "invite by GitHub handle" showing a confirmed identity instead of
    # a typed string). Never used to act on any repo. Every GitHub App also
    # has its own Client ID/Client Secret pair (shown on the same App
    # settings page as the private key) — reuse the same App's credentials
    # here rather than registering a second one.
    github_oauth_client_id: str | None = Field(
        default=None,
        validation_alias="GITHUB_OAUTH_CLIENT_ID",
    )
    github_oauth_client_secret: SecretStr | None = Field(
        default=None,
        validation_alias="GITHUB_OAUTH_CLIENT_SECRET",
    )
    # Must match the callback URL registered on the App's OAuth settings,
    # exactly — GitHub rejects on any mismatch. Points at the BACKEND, not
    # the frontend (this app's own callback route lives on the FastAPI server).
    github_oauth_redirect_uri: str | None = Field(
        default=None,
        validation_alias="GITHUB_OAUTH_REDIRECT_URI",
    )
    # Signs/verifies the OAuth `state` param (HMAC-SHA256). Required — a
    # blank value makes /api/github/install fail outright.
    github_oauth_state_secret: str | None = Field(
        default=None,
        validation_alias="GITHUB_OAUTH_STATE_SECRET",
    )
    github_oauth_state_ttl_seconds: int = Field(
        default=600,
        ge=60,
        le=3600,
        validation_alias="GITHUB_OAUTH_STATE_TTL_SECONDS",
    )
    # Fernet key encrypting the access token at rest, same convention as
    # SLACK_TOKEN_ENCRYPTION_KEY — unset falls back to a dev-only derived
    # key outside production.
    github_oauth_token_encryption_key: SecretStr | None = Field(
        default=None,
        validation_alias="GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY",
    )
    github_oauth_install_success_redirect: str = Field(
        default="/dashboard/settings?github=connected",
        validation_alias="GITHUB_OAUTH_INSTALL_SUCCESS_REDIRECT",
    )
    github_oauth_install_error_redirect: str = Field(
        default="/dashboard/settings?github=error",
        validation_alias="GITHUB_OAUTH_INSTALL_ERROR_REDIRECT",
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
