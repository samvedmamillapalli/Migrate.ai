from __future__ import annotations

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.shadow.ccloud_api_provider import CCloudApiShadowProvider
from app.shadow.ccloud_provider import CCloudShadowProvider
from app.shadow.mock_provider import MockShadowProvider
from app.shadow.provider import ShadowClusterProvider, ShadowProviderError

logger = get_logger(__name__)


# Reverse lookup: a shadow_clusters row stores the *provider instance's*
# `.name` (e.g. "mock_local"), not the SHADOW_PROVIDER *setting* value that
# created it (e.g. "mock") — these are deliberately different strings. Tearing
# a specific cluster down (teardown-now, the sweep loop) must reconstruct the
# provider that actually created it, not whatever SHADOW_PROVIDER currently
# happens to be — those can differ, e.g. right after a verify-local run
# (which forces SHADOW_PROVIDER=mock only for its own duration) followed by a
# real ccloud_api run, or in this dev environment where both get exercised in
# the same process across different requests.
_PROVIDER_NAME_TO_CHOICE: dict[str, str] = {
    "mock_local": "mock",
    "cockroachdb_cloud_api": "ccloud_api",
    "cockroachdb_cloud": "ccloud",
}


def provider_choice_for_name(stored_provider_name: str) -> str | None:
    """``shadow.provider`` (a provider `.name`) -> the SHADOW_PROVIDER choice
    that would reconstruct it, or None if unrecognized (caller should fall
    back to the current setting rather than error, since this is a
    best-effort reverse mapping for legacy/unexpected values)."""
    return _PROVIDER_NAME_TO_CHOICE.get(stored_provider_name.strip().lower())


def resolve_ccloud_api_bearer_token(settings: Settings) -> str:
    """The Bearer token for the CockroachDB Cloud REST API — shared by the
    ``ccloud_api`` shadow provider and the Managed MCP Server (same
    service-account credential, same account, same RBAC; confirmed against a
    real cluster — see docs/COCKROACHDB_MCP_INTEGRATION_PLAN.md §1)."""
    secret = (
        settings.ccloud_api_secret.get_secret_value()
        if settings.ccloud_api_secret
        else ""
    )
    key = (
        settings.ccloud_api_key.get_secret_value() if settings.ccloud_api_key else ""
    )
    # Cockroach returns the full Bearer secret once as CCDB1_<a>_<b>.
    # Prefer that shape if CCLOUD_API_SECRET was truncated / swapped with KEY.
    bearer = secret
    if key.count("_") >= 2 and (
        not bearer or bearer.count("_") < 2 or key.startswith(bearer)
    ):
        if bearer != key:
            logger.warning(
                "CCLOUD_API_SECRET does not look like a full Cloud API secret; "
                "using CCLOUD_API_KEY value as Bearer token"
            )
        bearer = key
    if not bearer:
        raise ShadowProviderError(
            "CCLOUD_API_SECRET is required (the full service-account API "
            "secret shown once at creation)"
        )
    return bearer


def create_shadow_provider(
    settings: Settings | None = None,
    *,
    provider_choice: str | None = None,
) -> ShadowClusterProvider:
    """Construct a shadow provider.

    * ``mock``       — offline scratch-database provider on the control-plane cluster.
    * ``ccloud_api`` — real CockroachDB Cloud provisioning via the REST API.
    * ``ccloud``     — ccloud CLI (interactive browser auth only; not headless).

    Defaults to ``settings.SHADOW_PROVIDER`` (the normal "what should new
    clusters use" case). Pass ``provider_choice`` explicitly when
    reconstructing the provider for an *existing* cluster instead — see
    ``provider_choice_for_name`` — since the current setting may not match
    what actually created that specific cluster.
    """
    settings = settings or get_settings()
    choice = (provider_choice or settings.shadow_provider).strip().lower()

    if choice == "mock":
        return MockShadowProvider(settings.database_url.get_secret_value())

    if choice == "ccloud_api":
        bearer = resolve_ccloud_api_bearer_token(settings)
        return CCloudApiShadowProvider(
            api_secret=bearer,
            base_url=settings.ccloud_api_base_url,
            plan=settings.shadow_cluster_plan,
            provider_cloud=settings.shadow_cluster_cloud.upper(),
            timeout_seconds=settings.ccloud_api_timeout_seconds,
            max_retries=settings.ccloud_api_max_retries,
            backoff_base_seconds=settings.ccloud_api_backoff_base_seconds,
        )

    if choice == "ccloud":
        if settings.ccloud_api_key is None:
            raise ShadowProviderError(
                "SHADOW_PROVIDER=ccloud requires CCLOUD_API_KEY to be set"
            )
        api_key = settings.ccloud_api_key.get_secret_value()
        if not api_key or api_key.startswith("dummy"):
            raise ShadowProviderError(
                "CCLOUD_API_KEY looks like a placeholder; set a real "
                "service-account API key before using the ccloud provider"
            )
        return CCloudShadowProvider(
            binary=settings.ccloud_binary,
            api_key=api_key,
            cloud=settings.shadow_cluster_cloud,
            region=settings.shadow_cluster_region,
        )

    raise ShadowProviderError(f"Unknown SHADOW_PROVIDER: {settings.shadow_provider!r}")
