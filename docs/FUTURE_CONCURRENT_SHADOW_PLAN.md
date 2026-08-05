# Future Feature Plan: Concurrent Shadow Executions Per User

Status: **investigated, mostly already true today**. Companion documents:
`docs/FUTURE_WORKSPACES_PLAN.md`, `docs/FUTURE_GITHUB_INTEGRATION_PLAN.md`.

## Summary and Recommendation

**The literal ask — a single user able to have more than one shadow run in
flight at the same time — already works today, with zero backend code
changes**, confirmed by reading `try_admit` and `count_active` directly
(below). The only genuinely missing piece is a small, additive, low-risk
**frontend** change (a "your active runs" list), because the Current
Migration page's UI assumes one run in focus. That frontend piece is cheap
enough to be worth actually shipping before August 18, if there's spare
capacity — it touches no backend logic, no schema, and nothing locked. The
richer version of this feature — a real per-user concurrency policy layered
on top of the global cap — is **not** already true, is real new work with a
real cost tradeoff, and should be documented as a roadmap item, not built
now.

## Investigation: does the existing global cap already permit this?

Yes. Traced exactly, not assumed.

**`app/services/shadow_cluster_service.py`, `try_admit` (lines 82–134):**

```python
async def try_admit(
    self,
    *,
    run_id: uuid.UUID,
    region: str,
    provider: str,
    scale_tier: str,
    max_concurrent: int,
    max_lifetime_minutes: int,
) -> ShadowCluster | None:
    existing = await self._repository.get_by_migration_run_id(run_id)
    if existing is not None:
        return existing  # one shadow per run (unique constraint); reuse

    async def _commit() -> ShadowCluster | None:
        active = await self._repository.count_active()
        if active >= max_concurrent:
            await self._session.rollback()
            return None
        ...
        cluster = ShadowCluster(migration_run_id=run_id, ...)
        created = await self._repository.create(cluster)
        await self._session.commit()
        return created

    created = await with_txn_retry(_commit, on_retry=self._session.rollback)
    ...
```

The admission decision is `active >= max_concurrent`, where `active` comes
from `count_active()`.

**`app/repositories/shadow_cluster_repository.py`, `count_active` (lines
31–43):**

```python
async def count_active(self) -> int:
    query = (
        select(func.count())
        .select_from(ShadowCluster)
        .where(ShadowCluster.status.in_(ACTIVE_SHADOW_STATUSES))
    )
    result = await self._session.execute(query)
    return int(result.scalar_one())
```

This counts every `ShadowCluster` row in an active status
(`PROVISIONING`/`READY`/`SEEDING`/`MIGRATING`/`HOLDING`/`DESTROYING`, per
`ACTIVE_SHADOW_STATUSES` in `app/database/models/shadow_cluster.py`)
**system-wide**. There is no `owner_identity` filter, no join to
`migration_runs` to find out who owns each cluster, nothing. `try_admit`
itself never receives an owner — only `run_id`.

**Confirmed there is no other gate anywhere else in the call chain either**:

- The only caller of `acquire_slot`/`try_admit` is
  `app/lambdas/handlers/provision_shadow.py` (the real Step-Functions-invoked
  Lambda, `ProvisionShadowCluster`). It passes `run_id`, `region`, `provider`,
  `scale_tier`, `max_concurrent=settings.shadow_max_concurrent`, and
  lifetime/timeout/poll settings — never an owner.
- Grepped `app/services/*.py` and `app/api/routes/*.py` for any
  "already has an active run" / "only one active" style check at run
  creation or `start-workflow` time. Nothing exists.
- `settings.shadow_max_concurrent` (`app/config.py:60`, default `2`,
  currently set to `2` per `docs/backendfix.md`) is a single global config
  value, read once per Lambda invocation, not scoped per owner.

**Conclusion**: today, if one owner starts two shadow runs back to back,
both compete for the same shared pool of `SHADOW_MAX_CONCURRENT` slots as
everyone else's runs, with no special treatment either way. Nothing prevents
a single owner from occupying both slots when the cap is 2. This is real,
current behavior — not something that needs to be built.

This investigation was done by reading code, not by running two real
concurrent shadow clusters (this document is planning-only, per the task
scope — no implementation or live verification was performed in this pass).
If a human wants stronger confidence than a code read before relying on this
in a demo, the cheapest way to get it is a single live test: start two real
shadow runs under the same `owner_identity` back to back and confirm both
get admitted (not queued) when the cap is ≥ 2 and nothing else is running.
That is a verification step, not a new feature, and carries only the normal
cost of two real (short-lived, ~1 minute) CockroachDB Cloud BASIC clusters.

## If Richer Per-User Policy Is Wanted (not recommended now)

The deeper version of this ask — "a global cap of N plus a per-user cap of M
where M can be less than N" — is genuinely new logic, not free. It would
require:

1. A per-owner variant of `count_active()`, e.g.
   `count_active_for_owner(owner_identity)`, joining `ShadowCluster` to
   `MigrationRun` on `migration_run_id` and filtering by
   `MigrationRun.owner_identity` — `ShadowCluster` itself carries no owner
   column today, so this join is unavoidable for any owner-aware query.
2. A second config value, e.g. `shadow_max_concurrent_per_owner`, defaulting
   to something ≤ `shadow_max_concurrent` (if it equals the global cap, it's
   a no-op; the whole point is `M < N`).
3. `try_admit` checking **both** conditions before admitting: global count
   under `N` *and* this owner's count under `M`. This is a second read
   inside the same serializable transaction `try_admit` already opens for
   the global count, so it doesn't introduce a new race-condition risk beyond
   what already exists — but it does make the admission transaction do more
   work per attempt.

**The real tradeoff to state plainly, not just an engineering one**: the
entire point of a per-user cap smaller than the global cap is to guarantee
fairness — so one busy user (or one runaway retry loop) can't starve every
other user of shadow capacity. But the *global* cap itself doesn't change
just because a per-user cap gets added underneath it — if the honest goal is
"more total concurrent shadow capacity across all users," raising
`SHADOW_MAX_CONCURRENT` is the actual lever, and that means **more
simultaneous CockroachDB Cloud BASIC clusters running at once**, which is a
real, direct cost increase, not just a code change. A per-user cap without
also raising the global cap doesn't add capacity, it only redistributes the
existing two slots more fairly among users — worth being explicit about
which problem is actually being solved before building either half.

## UI Implication

The Current Migration page (`current-migration-workspace.tsx`) and its
`localStorage`-backed `current_run_id` (`lib/api/owner.ts`) are built around
one run in focus at a time — this is a **frontend/UX limitation**, not a
backend one; the backend already tracks and serves as many concurrent runs
as exist via `GET /runs`. The concrete gap: there is currently no page that
shows "here are all your runs currently in a non-terminal state," so if a
user genuinely does start two shadow runs concurrently today, the second one
has no obvious place to watch from without manually navigating to
`/dashboard/migrations/{id}` by ID.

Minimal, additive fix (worth doing regardless of whether the richer per-user
policy is ever built): a small "Active runs" list/panel — query
`GET /runs?owner_identity=...` filtered client-side (or via a new
`status_in=` query param, mirroring the existing `exclude_kinds` pattern
already used by that endpoint) to non-terminal statuses
(`pending`/`predicting`/`awaiting_approval`/`running`), rendered as a short
list with a link into each run's own page. This requires no backend schema
change, no new endpoint (a query-param addition to the existing `GET /runs`
route at most), and touches nothing locked.

## Feasibility Before August 18

**Worth doing, cheaply**: the "Active runs" list. It's additive, frontend-
only (or frontend + one optional query-param addition), doesn't touch
`owner_identity` semantics, memory retrieval, or the approval model, and
directly demonstrates the "already works" finding above in a way a judge can
actually see, rather than leaving it as an invisible backend fact.

**Not recommended before August 18**: the per-user cap (`M < N`) policy. It's
real work, it's not needed to demonstrate concurrent shadow executions (the
existing global cap already permits that), and its actual point — fairness
under contention — only matters once there are enough simultaneous users to
create contention, which is not the situation during a demo.

## Open Questions

- Is a live two-concurrent-runs verification (real CockroachDB Cloud
  clusters, ~1 minute each) worth doing before the demo just for confidence,
  given this plan's conclusion rests on a code read rather than a live
  observation? Low cost either way; a human call on whether that confidence
  is worth the two extra clusters and a few minutes.

It would allow the user to have basically 2 migrations running at one time.

- If the per-user cap is ever built: should `M` be a fixed global setting
  (same for every owner) or something workspace/plan-tier aware? This plan
  assumes a single fixed `M` for simplicity; anything more granular is a
  bigger design question tied to whatever the product's eventual
  multi-tenancy/billing model looks like, which doesn't exist yet.


honestly just be smart about how to implement it and do the recommended action. if there is anything related to deployment then put it in the deployment reference doc

## Prompt

Paste the following into a fresh session if the richer per-user policy is
ever wanted:

```
Read docs/FUTURE_CONCURRENT_SHADOW_PLAN.md in full before doing anything
else. It already established, by reading the code directly, that a single
owner can occupy multiple shadow-cluster concurrency slots today with no
per-user restriction — do not re-investigate that from scratch, trust it or
re-verify it live in under five minutes, then move on.

Two independent pieces of work in this plan, do them separately and confirm
each works before starting the next:

1. The "Active runs" list (recommended to have been done already — check
   docs/backendfix.md's Change Log before assuming it's still missing). If
   it's still missing: add a status_in= query param to GET /runs (or filter
   client-side against the existing owner_identity-scoped list), and a small
   panel/page listing the requesting owner's non-terminal runs
   (pending/predicting/awaiting_approval/running) with links into each.

2. The per-user concurrency cap, ONLY if a human has explicitly asked for it
   (this plan recommends against building it speculatively). If asked for:
   add ShadowClusterRepository.count_active_for_owner(owner_identity) (join
   ShadowCluster to MigrationRun on migration_run_id, filter by
   MigrationRun.owner_identity, same ACTIVE_SHADOW_STATUSES predicate as
   count_active), a new settings.shadow_max_concurrent_per_owner config
   value, and wire both checks into ShadowClusterService.try_admit inside
   the same serializable transaction that already exists there. Do not
   change the meaning or default of the existing global
   shadow_max_concurrent — this is additive, not a replacement.

Verify with a real live test, not just unit tests: start shadow runs under
two different owner_identity values plus a second run under one of those
same owners, and confirm the admission behavior matches whatever cap
configuration was set. Report the actual CockroachDB Cloud cost implication
(number of concurrent BASIC clusters, approximate lifetime) honestly in your
final report, since this plan explicitly flagged that as a real tradeoff,
not just an engineering one.
```
