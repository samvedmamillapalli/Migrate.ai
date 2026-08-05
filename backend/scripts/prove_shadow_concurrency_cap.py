"""Live proof: per-owner shadow concurrency cap — docs/FUTURE_CONCURRENT_SHADOW_PLAN.md.

Calls ``ShadowClusterService.try_admit`` directly against the real
CockroachDB Cloud database (real rows, real serializable transactions) —
the same admission decision the ProvisionShadowCluster Lambda makes before
it ever calls a cluster provider. Deliberately never calls a provider, so
this creates zero real CockroachDB Cloud *shadow* clusters and costs
nothing beyond a handful of rows in the app's own control-plane database,
which this script deletes again at the end.

Scenario: two owners, a per-owner cap of 1 (global cap set high so it never
binds), verifying:
  1. Owner A's first run is admitted.
  2. Owner A's second run is rejected — even though the *global* count is
     nowhere near its cap — because owner A is already at its own cap.
  3. Owner B's run is admitted independently of owner A's state.
  4. The no-per-owner-cap default path (no owner_identity/cap passed) is
     unaffected by any of this.

Run: python scripts/prove_shadow_concurrency_cap.py
"""

from __future__ import annotations

import asyncio
import selectors
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OWNER_A = "concurrency-test-owner-a"
OWNER_B = "concurrency-test-owner-b"

failures: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        failures.append(label)


async def main() -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import get_settings
    from app.database.models import MigrationRun
    from app.database.session import normalize_database_url
    from app.repositories.migration_run_repository import MigrationRunRepository
    from app.repositories.shadow_cluster_repository import ShadowClusterRepository
    from app.services.shadow_cluster_service import ShadowClusterService

    settings = get_settings()
    # NullPool: a fresh physical connection per checkout, no pooled-connection
    # reuse. Works around a MissingGreenlet error this standalone script hits
    # on repeated commit-then-checkout cycles under Windows + a bare
    # asyncio.run() loop (the real app never hits this — uvicorn's request
    # lifecycle checks out connections differently) — same category of
    # Windows-only environment quirk as the documented --no-reload DB issue.
    engine = create_async_engine(
        normalize_database_url(settings.database_url.get_secret_value()),
        poolclass=NullPool,
        connect_args={"connect_timeout": 30, "application_name": "migration-oracle-proof"},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    created_run_ids = []
    created_shadow_ids = []

    async with session_factory() as session:
        run_repo = MigrationRunRepository(session)
        shadow_repo = ShadowClusterRepository(session)
        shadow_service = ShadowClusterService(repository=shadow_repo, session=session)

        print(f"Owner A: {OWNER_A}")
        print(f"Owner B: {OWNER_B}")
        print("Cap config for this proof: global max_concurrent=5, per-owner=1\n")

        run_a1 = MigrationRun(
            migration_sql="-- concurrency cap proof, not a real migration (a1)",
            owner_identity=OWNER_A,
            run_kind="debug",
        )
        run_a1 = await run_repo.create(run_a1)
        await session.commit()
        created_run_ids.append(run_a1.id)

        run_a2 = MigrationRun(
            migration_sql="-- concurrency cap proof, not a real migration (a2)",
            owner_identity=OWNER_A,
            run_kind="debug",
        )
        run_a2 = await run_repo.create(run_a2)
        await session.commit()
        created_run_ids.append(run_a2.id)

        run_b1 = MigrationRun(
            migration_sql="-- concurrency cap proof, not a real migration (b1)",
            owner_identity=OWNER_B,
            run_kind="debug",
        )
        run_b1 = await run_repo.create(run_b1)
        await session.commit()
        created_run_ids.append(run_b1.id)

        print("1) Owner A, run 1 — expect ADMITTED")
        admitted_a1 = await shadow_service.try_admit(
            run_id=run_a1.id,
            region="us-east-1",
            provider="ccloud_api",
            scale_tier="small",
            max_concurrent=5,
            max_lifetime_minutes=30,
            owner_identity=OWNER_A,
            max_concurrent_per_owner=1,
        )
        if admitted_a1 is not None:
            created_shadow_ids.append(admitted_a1.id)
        check("owner A run 1 admitted", admitted_a1 is not None)

        print("\n2) Owner A, run 2 — expect REJECTED (owner already at its cap of 1)")
        admitted_a2 = await shadow_service.try_admit(
            run_id=run_a2.id,
            region="us-east-1",
            provider="ccloud_api",
            scale_tier="small",
            max_concurrent=5,
            max_lifetime_minutes=30,
            owner_identity=OWNER_A,
            max_concurrent_per_owner=1,
        )
        if admitted_a2 is not None:
            created_shadow_ids.append(admitted_a2.id)
        check("owner A run 2 rejected", admitted_a2 is None)

        print("\n3) Owner B, run 1 — expect ADMITTED (independent of owner A)")
        admitted_b1 = await shadow_service.try_admit(
            run_id=run_b1.id,
            region="us-east-1",
            provider="ccloud_api",
            scale_tier="small",
            max_concurrent=5,
            max_lifetime_minutes=30,
            owner_identity=OWNER_B,
            max_concurrent_per_owner=1,
        )
        if admitted_b1 is not None:
            created_shadow_ids.append(admitted_b1.id)
        check("owner B run 1 admitted", admitted_b1 is not None)

        print("\n4) Cross-check counts against the real database")
        global_count = await shadow_repo.count_active()
        owner_a_count = await shadow_repo.count_active_for_owner(OWNER_A)
        owner_b_count = await shadow_repo.count_active_for_owner(OWNER_B)
        print(f"  global active: {global_count}")
        print(f"  owner A active: {owner_a_count}")
        print(f"  owner B active: {owner_b_count}")
        check("global active == 2 (a1 + b1, a2 was never inserted)", global_count == 2)
        check("owner A active == 1 (at its cap)", owner_a_count == 1)
        check("owner B active == 1", owner_b_count == 1)

        print(
            "\n5) Confirm the *global-only* cap (no owner_identity given) still "
            "behaves exactly as before this change — the no-per-owner-cap "
            "default path is unaffected"
        )
        run_a3 = MigrationRun(
            migration_sql="-- concurrency cap proof, not a real migration (a3)",
            owner_identity=OWNER_A,
            run_kind="debug",
        )
        run_a3 = await run_repo.create(run_a3)
        await session.commit()
        created_run_ids.append(run_a3.id)

        admitted_global_only = await shadow_service.try_admit(
            run_id=run_a3.id,
            region="us-east-1",
            provider="ccloud_api",
            scale_tier="small",
            max_concurrent=5,
            max_lifetime_minutes=30,
            # no owner_identity / max_concurrent_per_owner — default path
        )
        if admitted_global_only is not None:
            created_shadow_ids.append(admitted_global_only.id)
        check(
            "owner A's 3rd run admitted when no per-owner cap is passed "
            "(global count 2 < global cap 5) — same owner that was capped above",
            admitted_global_only is not None,
        )

        print("\nCleaning up test rows...")
        for shadow_id in created_shadow_ids:
            await shadow_repo.delete_by_id(shadow_id)
        await session.commit()
        for run_id in created_run_ids:
            await run_repo.delete_by_id(run_id)
        await session.commit()
        print(
            f"Deleted {len(created_shadow_ids)} shadow_cluster row(s) and "
            f"{len(created_run_ids)} migration_run row(s)."
        )

    await engine.dispose()

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} check(s) failed)")
        return 1
    print("RESULT: PASS — all checks passed against the real database.")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        raise SystemExit(
            asyncio.run(
                main(),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        )
    raise SystemExit(asyncio.run(main()))
