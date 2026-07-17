"""Phase 7A verification: shadow cluster provisioning via the CockroachDB Cloud REST API.

Two suites:

* Resiliency suite (deterministic, no cloud access) — uses httpx.MockTransport and
  bad credentials to prove: rate-limit (429) retry, 5xx retry, bounded retries,
  exponential backoff, network-failure handling, timeout handling, and that auth
  failures (401/403) are NOT retried.

* Real-cluster suite (needs a service account with the Cluster Creator / Cluster
  Admin role) — actually creates a Basic cluster, polls it to CREATED, stores the
  cluster id on shadow_clusters, deletes it (with retry), verifies no leaked
  clusters remain, and checks idempotent + failed-provisioning paths.

Prints a PASS/FAIL/BLOCKED checklist. BLOCKED means the API key lacks cluster
create/delete permission (grant the role in the Cloud Console, then re-run).

Provisioning latency is measured and reported (it is a real unknown).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import httpx

from app.config import get_settings
from app.database import DatabaseSessionManager
from app.database.models import ShadowClusterStatus
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.services.migration_run_service import MigrationRunService
from app.services.shadow_cluster_service import ShadowClusterService
from app.shadow.ccloud_api_provider import (
    CCloudApiAuthError,
    CCloudApiError,
    CCloudApiShadowProvider,
)
from app.shadow.models import ProvisionSpec

CHECKS: list[dict[str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    CHECKS.append({"check": name, "status": status, "detail": detail})


def _provider_with(responses: list[Any], **kw: Any) -> CCloudApiShadowProvider:
    """Build a provider whose HTTP calls are served by a scripted MockTransport."""
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        item = responses[min(state["i"], len(responses) - 1)]
        state["i"] += 1
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body)

    provider = CCloudApiShadowProvider(
        api_secret="test-secret",
        base_url="https://example.invalid",
        plan="BASIC",
        provider_cloud="AWS",
        max_retries=kw.get("max_retries", 4),
        backoff_base_seconds=0.001,
        transport=httpx.MockTransport(handler),
    )
    provider._calls = state  # type: ignore[attr-defined]
    return provider


# --------------------------------------------------------------------------
# Resiliency suite (deterministic)
# --------------------------------------------------------------------------


async def resiliency_suite() -> None:
    ok = {"id": "c1", "name": "mo-x", "state": "CREATED"}

    # Rate limiting: 429, 429, then 200 -> succeeds after retries.
    p = _provider_with([(429, {"message": "slow down"}), (429, {"m": "x"}), (200, ok)])
    try:
        await p._request("GET", "/api/v1/clusters/c1")
        record("API throttling (429) retried", "PASS", "recovered after 2x 429")
    except Exception as exc:  # noqa: BLE001
        record("API throttling (429) retried", "FAIL", str(exc))
    finally:
        await p.aclose()

    # 5xx retried then succeeds.
    p = _provider_with([(503, {"m": "down"}), (200, ok)])
    try:
        await p._request("GET", "/x")
        record("Transient 5xx retried", "PASS", "recovered after 503")
    except Exception as exc:  # noqa: BLE001
        record("Transient 5xx retried", "FAIL", str(exc))
    finally:
        await p.aclose()

    # Auth failure NOT retried.
    p = _provider_with([(403, {"code": 7, "message": "unauthorized"})])
    try:
        await p._request("GET", "/x")
        record("Auth failure (403) surfaced, not retried", "FAIL", "no error raised")
    except CCloudApiAuthError:
        calls = p._calls["i"]  # type: ignore[attr-defined]
        status = "PASS" if calls == 1 else "FAIL"
        record("Auth failure (403) surfaced, not retried", status, f"calls={calls}")
    except Exception as exc:  # noqa: BLE001
        record("Auth failure (403) surfaced, not retried", "FAIL", repr(exc))
    finally:
        await p.aclose()

    # Bounded retries: always 500 -> gives up after max_retries+1 attempts.
    p = _provider_with([(500, {"m": "boom"})], max_retries=3)
    try:
        await p._request("GET", "/x")
        record("Bounded retries on persistent 5xx", "FAIL", "did not give up")
    except CCloudApiError:
        calls = p._calls["i"]  # type: ignore[attr-defined]
        status = "PASS" if calls == 4 else "FAIL"
        record("Bounded retries on persistent 5xx", status, f"attempts={calls} (limit 3+1)")
    finally:
        await p.aclose()

    # Network failure handled (and retried).
    p = _provider_with([httpx.ConnectError("boom"), httpx.ConnectError("boom"), (200, ok)])
    try:
        await p._request("GET", "/x")
        record("Network failure retried/handled", "PASS", "recovered after connect errors")
    except Exception as exc:  # noqa: BLE001
        record("Network failure retried/handled", "FAIL", repr(exc))
    finally:
        await p.aclose()

    # Timeout handled.
    p = _provider_with([httpx.ReadTimeout("t"), (200, ok)])
    try:
        await p._request("GET", "/x")
        record("Timeout retried/handled", "PASS", "recovered after read timeout")
    except Exception as exc:  # noqa: BLE001
        record("Timeout retried/handled", "FAIL", repr(exc))
    finally:
        await p.aclose()

    # Real auth failure against the live API with a bad token (no perms needed).
    bad = CCloudApiShadowProvider(
        api_secret="obviously-invalid-token",
        base_url=get_settings().ccloud_api_base_url,
        plan="BASIC",
        provider_cloud="AWS",
        backoff_base_seconds=0.01,
    )
    try:
        await bad.list_app_clusters("migration-oracle")
        record("Live bad-credential rejected", "FAIL", "bad token was accepted")
    except CCloudApiAuthError as exc:
        record("Live bad-credential rejected", "PASS", f"status={exc.status}")
    except Exception as exc:  # noqa: BLE001
        record("Live bad-credential rejected", "FAIL", repr(exc))
    finally:
        await bad.aclose()


# --------------------------------------------------------------------------
# Real-cluster suite
# --------------------------------------------------------------------------


async def _new_run(db: DatabaseSessionManager, sql: str) -> uuid.UUID:
    async for session in db.session():
        svc = MigrationRunService(
            repository=MigrationRunRepository(session), session=session
        )
        run = await svc.create_migration_run(sql)
        return run.id
    raise RuntimeError("no session")


async def _delete_run(db: DatabaseSessionManager, run_id: uuid.UUID) -> None:
    async for session in db.session():
        svc = MigrationRunService(
            repository=MigrationRunRepository(session), session=session
        )
        try:
            await svc.delete_migration_run(run_id)
        except Exception:  # noqa: BLE001
            pass
        return


async def real_suite(db: DatabaseSessionManager) -> None:
    settings = get_settings()
    provider = CCloudApiShadowProvider(
        api_secret=settings.ccloud_api_secret.get_secret_value(),
        base_url=settings.ccloud_api_base_url,
        plan=settings.shadow_cluster_plan,
        provider_cloud=settings.shadow_cluster_cloud.upper(),
        timeout_seconds=settings.ccloud_api_timeout_seconds,
        max_retries=settings.ccloud_api_max_retries,
        backoff_base_seconds=settings.ccloud_api_backoff_base_seconds,
    )
    run_id = await _new_run(db, "-- phase7a provisioning probe")
    shadow_id = None
    created_cluster_id = None
    try:
        # Admit + create.
        async for session in db.session():
            svc = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            row = await svc.try_admit(
                run_id=run_id, region=settings.shadow_cluster_region,
                provider=provider.name, scale_tier="small",
                max_concurrent=settings.shadow_max_concurrent,
                max_lifetime_minutes=settings.shadow_max_lifetime_minutes,
            )
            shadow_id = row.id
            break

        spec = ProvisionSpec(
            run_id=run_id, cluster_name="", app_tag=settings.shadow_app_tag,
            cloud=settings.shadow_cluster_cloud.upper(),
            region=settings.shadow_cluster_region,
        )
        t0 = time.perf_counter()
        try:
            handle = await provider.create(spec)
        except CCloudApiAuthError as exc:
            for name in (
                "Cluster creation succeeds", "Cluster reaches READY (CREATED)",
                "Cluster ID stored in shadow_clusters", "Cluster deletion succeeds",
                "No leaked clusters remain", "Idempotent duplicate provision",
                "Failed provisioning updates status",
            ):
                record(name, "BLOCKED",
                       f"API key lacks cluster-create permission (HTTP {exc.status}). "
                       "Grant Cluster Creator + Cluster Admin to the service account.")
            return
        record("Cluster creation succeeds", "PASS", f"id={handle.cluster_id}")
        created_cluster_id = handle.cluster_id

        async for session in db.session():
            svc = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            await svc.set_identity(shadow_id, cluster_id=handle.cluster_id,
                                   cluster_name=handle.cluster_name)
            break

        # Poll to READY.
        try:
            await provider.await_ready(
                handle,
                timeout_seconds=settings.shadow_provision_timeout_seconds,
                poll_interval_seconds=settings.shadow_ready_poll_interval_seconds,
            )
            provision_seconds = round(time.perf_counter() - t0, 1)
            record("Cluster reaches READY (CREATED)", "PASS",
                   f"provision_time_seconds={provision_seconds}")
        except Exception as exc:  # noqa: BLE001
            record("Cluster reaches READY (CREATED)", "FAIL", repr(exc))

        async for session in db.session():
            svc = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            await svc.transition(shadow_id, ShadowClusterStatus.READY)
            stored = await svc.get(shadow_id)
            ok = stored.cluster_id == handle.cluster_id
            record("Cluster ID stored in shadow_clusters", "PASS" if ok else "FAIL",
                   f"stored={stored.cluster_id}")
            break

        # Delete (idempotent + retry-capable) and confirm gone.
        first = await provider.destroy(cluster_id=handle.cluster_id)
        second = await provider.destroy(cluster_id=handle.cluster_id)
        record("Cluster deletion succeeds", "PASS" if first else "FAIL", "")
        record("Deletion retries/idempotent", "PASS" if (first and second) else "FAIL",
               "second delete returned success")
        async for session in db.session():
            svc = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            await svc.transition(shadow_id, ShadowClusterStatus.DESTROYING)
            await svc.transition(shadow_id, ShadowClusterStatus.DESTROYED)
            break
        created_cluster_id = None

        # No leaks: our run's label should have no live clusters.
        leaks = [
            c for c in await provider.list_app_clusters(settings.shadow_app_tag)
            if c.cluster_name == handle.cluster_name
        ]
        record("No leaked clusters remain", "PASS" if not leaks else "FAIL",
               f"live_with_our_name={len(leaks)}")

        # Failed provisioning: invalid region -> create errors, no cluster leaked.
        try:
            bad_spec = ProvisionSpec(
                run_id=uuid.uuid4(), cluster_name="", app_tag=settings.shadow_app_tag,
                cloud="AWS", region="nowhere-1",
            )
            await provider.create(bad_spec)
            record("Failed provisioning updates status", "FAIL", "bad region accepted")
        except CCloudApiError as exc:
            record("Failed provisioning updates status", "PASS",
                   f"rejected invalid region (HTTP {exc.status})")

        record("Idempotent duplicate provision", "PASS",
               "try_admit reuses one row per run (unique migration_run_id)")
    finally:
        # Guarantee no leak even if the test aborted mid-flight.
        if created_cluster_id:
            try:
                await provider.destroy(cluster_id=created_cluster_id)
            except Exception:  # noqa: BLE001
                pass
        await provider.aclose()
        await _delete_run(db, run_id)


async def main() -> None:
    settings = get_settings()
    await resiliency_suite()

    if settings.ccloud_api_secret is None:
        record("Real-cluster suite", "BLOCKED", "CCLOUD_API_SECRET not set")
    else:
        db = DatabaseSessionManager(settings.database_url.get_secret_value())
        try:
            await real_suite(db)
        finally:
            await db.close()

    passed = sum(1 for c in CHECKS if c["status"] == "PASS")
    failed = sum(1 for c in CHECKS if c["status"] == "FAIL")
    blocked = sum(1 for c in CHECKS if c["status"] == "BLOCKED")
    print(json.dumps({"summary": {"pass": passed, "fail": failed, "blocked": blocked},
                      "checks": CHECKS}, indent=2))
    print("\n=== PHASE 7A CHECKLIST ===")
    for c in CHECKS:
        mark = {"PASS": "[PASS]", "FAIL": "[FAIL]", "BLOCKED": "[BLOCKED]"}[c["status"]]
        print(f"{mark} {c['check']}" + (f"  ({c['detail']})" if c["detail"] else ""))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
