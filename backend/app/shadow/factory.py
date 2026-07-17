from __future__ import annotations

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.shadow.ccloud_api_provider import CCloudApiShadowProvider
from app.shadow.ccloud_provider import CCloudShadowProvider
from app.shadow.mock_provider import MockShadowProvider
from app.shadow.provider import ShadowClusterProvider, ShadowProviderError

logger = get_logger(__name__)


def create_shadow_provider(settings: Settings | None = None) -> ShadowClusterProvider:
    """Construct the shadow provider selected by ``SHADOW_PROVIDER``.

    * ``mock``       — offline scratch-database provider on the control-plane cluster.
    * ``ccloud_api`` — real CockroachDB Cloud provisioning via the REST API.
    * ``ccloud``     — ccloud CLI (interactive browser auth only; not headless).
    """
    settings = settings or get_settings()
    choice = settings.shadow_provider.strip().lower()

    if choice == "mock":
        return MockShadowProvider(settings.database_url.get_secret_value())

    if choice == "ccloud_api":
        if settings.ccloud_api_secret is None:
            raise ShadowProviderError(
                "SHADOW_PROVIDER=ccloud_api requires CCLOUD_API_SECRET to be set"
            )
        return CCloudApiShadowProvider(
            api_secret=settings.ccloud_api_secret.get_secret_value(),
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
