#!/usr/bin/env python3
"""Run the shadow-cluster orphan sweeper once (cron / EventBridge entrypoint)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main() -> int:
    from app.aws import AwsClientFactory, get_aws_settings
    from app.aws.observability import CloudWatchObservability
    from app.config import get_settings
    from app.database import DatabaseSessionManager
    from app.repositories.shadow_cluster_repository import ShadowClusterRepository
    from app.services.shadow_cluster_service import ShadowClusterService
    from app.shadow.factory import create_shadow_provider
    from app.shadow.sweeper import ShadowClusterSweeper

    settings = get_settings()
    aws_settings = get_aws_settings()
    database = DatabaseSessionManager(settings.database_url.get_secret_value())
    observability = None
    try:
        if aws_settings.aws_enabled:
            factory = AwsClientFactory(aws_settings)
            observability = CloudWatchObservability(factory, aws_settings)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: CloudWatch observability unavailable: {exc}", file=sys.stderr)

    report: dict = {}
    async for session in database.session():
        service = ShadowClusterService(
            repository=ShadowClusterRepository(session),
            session=session,
        )
        provider = create_shadow_provider(settings)
        sweeper = ShadowClusterSweeper(
            service=service,
            provider=provider,
            app_tag=settings.shadow_app_tag,
            max_lifetime_minutes=settings.shadow_max_lifetime_minutes,
            observability=observability,
        )
        report = await sweeper.sweep()
        break

    await database.close()
    print(json.dumps(report, indent=2, default=str))
    return 1 if report.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


def handler(event: object | None = None, context: object | None = None) -> dict:
    """AWS Lambda entrypoint for EventBridge schedule."""
    code = asyncio.run(main())
    return {"ok": code == 0, "exit_code": code}
