# Future Feature Plan: Workspaces

Status: **built and live-verified, 2026-08-05.** The human explicitly
authorized building it (edited this doc directly to remove the "do not
build before August 18" recommendation below, and answered the retrieval-
scoping question — see Open Questions). See `docs/backendfix.md`'s
2026-08-05 Change Log entry for exactly what was built, which Open
Questions were resolved and how, and the live verification evidence
(`scripts/prove_workspaces.py`, `scripts/prove_workspace_memory_scope.py`).
The rest of this document is preserved as-written (the original
recommendation-against-building-yet, superseded below) since the schema
design, migration path, and scoping analysis are exactly what got built —
only the "when" changed, not the "what."  Companion documents:
`docs/FUTURE_CONCURRENT_SHADOW_PLAN.md`, `docs/FUTURE_GITHUB_INTEGRATION_PLAN.md`.

## Summary and Recommendation

Workspaces is a genuine new data-model
entity sitting above `migration_runs`, and it directly touches
`owner_identity` scoping and memory retrieval — the mechanism behind this
product's actual differentiator (the closed predict → verify → grade →
remember loop, per `docs/backendfix.md`). That loop is currently demo-ready
and verified. Changing the scoping model underneath it two weeks before a
deadline risks destabilizing something that works, in exchange for a feature
that is not required to demonstrate the closed loop itself. Document it here
with enough precision that it reads as a real technical plan, and build it
after the deadline, not during the deadline crunch.

## Current State (investigated 2026-08, this session)

There is **no workspace or project entity anywhere in this codebase** —
confirmed by reading the code directly, not by absence of a grep hit alone:

- `app/database/models/` has no `workspace.py` / `project.py`. The only
  identity-shaped table is `app_users` (`app/database/models/app_user.py`),
  and it is **confirmed still dead code** as of this investigation: the only
  references to `AppUser` anywhere in `app/` are its own model file and
  `app/api/routes/auth.py`'s legacy custom-HMAC `register`/`login` flow,
  which is gated entirely behind `settings.auth_enabled` (off by default) and
  superseded by the live Clerk auth path per `docs/backendfix.md`'s
  "CORRECTED 2026-07-28" note. Nothing in `migration_runs`, `shadow_clusters`,
  or memory retrieval joins against it. Do not build workspaces as a
  relationship off `app_users` — build `owner_identity` as a plain string
  column, matching the existing convention used everywhere else
  (`MigrationRun.owner_identity`, `Approval.approver_identity`).
- `owner_identity` is the *sole* scoping mechanism today, everywhere:
  `MigrationRun.owner_identity` (`app/database/models/migration_run.py`),
  identical `approver_identity` pattern on `Approval`, and the retrieval
  scope in `HybridMemoryRetrieval` (`app/memory/retrieval.py:160`):
  ```python
  scopes = [owner, CORPUS_OWNER_IDENTITY]
  ```
- `docs/PIXEL_PERFECT_CLONE_INTEGRATION_PLAN.md` (an earlier, independent
  investigation) explicitly confirms the same finding: *"No workspace entity
  in the backend. Owner ≈ `owner_identity` (currently localStorage, synced
  from Clerk...)"* — this plan is not duplicating or contradicting a decision
  made elsewhere.
- The frontend has **dead, unwired shadcn template scaffolding** that looks
  workspace-adjacent but isn't: `components/team-switcher.tsx` and
  `components/nav-projects.tsx` are leftover `sidebar-07` template
  components. `team-switcher.tsx` holds local `React.useState` over a
  hardcoded fake `teams` array; "Add team" has no handler. Neither component
  is imported by `app-sidebar.tsx` (confirmed by grep — zero mount points).
  This is not a partially-built workspace switcher to resume; it is inert
  scaffolding that should either be deleted or genuinely wired up when this
  feature is actually built, not treated as prior art to build on.
- **The connection-credential pattern today is exactly what a workspace would
  replace.** `POST /runs/{id}/discover` (`app/api/routes/runs.py:395`)
  accepts either a raw `database_url` or a pre-existing
  `connection_secret_arn`. When given a raw URL, `_store_connection_url`
  (`app/api/routes/runs.py:866`) creates a **fresh** secret every time, named
  `f"migration-oracle/connections/{run_id}"`. There is no reuse across runs
  today — a user re-provides (or re-pastes) their database connection on
  every single run. This is the concrete gap a workspace's stored connection
  reference would close.
- Step Functions (`infra/stepfunctions/migration_workflow.asl.json`) receives
  `connection_secret_arn` as a plain input parameter at execution start
  (`"connection_secret_arn.$": "$.connection_secret_arn"`) — it has no
  concept of looking up a stored, reusable secret by any other key. A
  workspace-aware flow would resolve `workspace.connection_secret_arn` into
  this same input field before starting the workflow; the ASL itself would
  not need to change.

## Proposed Schema

A new table sitting above `migration_runs`, holding a name, an owning
`owner_identity`, and a pointer to the target database's Secrets Manager
entry — matching the existing "pointer only, never the password" convention
already used by `MigrationRun.connection_secret_arn`:

```python
class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        Index("ix_workspaces_owner_identity", "owner_identity"),
        UniqueConstraint(
            "owner_identity", "name", name="uq_workspaces_owner_identity_name"
        ),
    )

    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # Same pointer-only convention as MigrationRun.connection_secret_arn —
    # never the password, never the raw connection string, at rest.
    connection_secret_arn: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    # Denormalized display-only hint (e.g. "customer_demo" or a redacted
    # host), so the workspace switcher doesn't need a live Secrets Manager
    # round-trip just to render a label. Never the full connection string.
    connection_label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
```

`migration_runs` gains a nullable FK:

```python
workspace_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
)
```

Nullable, not required — see migration path below for why, and note that
`MigrationRun.connection_secret_arn` stays exactly as it is (a per-run
pointer). The relationship is: a run *may* belong to a workspace, and when it
does, `discover` can default `connection_secret_arn` from
`workspace.connection_secret_arn` instead of requiring the user to re-paste a
URL — but the per-run field remains authoritative and overridable (a user
testing a one-off connection without committing to a workspace should still
be able to).

## Scoping Interaction With Memory Retrieval — flagged explicitly

**This proposal touches a decision recorded as locked in `docs/backendfix.md`:**
*"Retrieval scopes to the requesting owner plus the reserved corpus identity
`__migration_oracle_corpus__`. That constant must exist in exactly one place
in the codebase and be imported everywhere else."* Workspaces do not change
`owner_identity` as the account-level identity mechanism, and this plan does
not propose changing that. But workspaces raise a real, adjacent question the
locked decision doesn't currently need to answer: **should retrieval also
narrow by workspace within an owner's own account, or stay owner-wide?**

The tradeoff, stated plainly:

- **Stay owner-scoped (retrieval ignores `workspace_id` entirely).** A
  lesson learned on workspace A's database ("this table's backfill pattern
  causes lock contention") still surfaces when the same owner runs a
  similar-shaped migration under workspace B, even though it's a different
  target database. This is *more* cross-pollination, which is probably
  correct for structural/mechanism-level lessons (the whole point of the
  demo beat in `docs/backendfix.md`: retrieval matching on mechanism, not
  vocabulary) — but it can also surface advice that's specific to a
  database-level property of workspace A (row counts, index layout) that
  doesn't actually transfer to workspace B.
- **Narrow to workspace (retrieval requires the same `workspace_id`).** Less
  cross-pollination, more precision — a user managing five genuinely
  unrelated client databases under five workspaces won't see one client's
  lessons bleed into another's recommendations. But it also means a brand
  new workspace starts with **zero personal history** even if the same owner
  has run fifty migrations elsewhere, which weakens exactly the "the more
  you use it, the smarter it gets" narrative this product is built around,
  and increases how much retrieval leans on the shared open-source corpus
  before an owner accumulates workspace-local history.

**Recommendation, not a decision**: keep retrieval scoped by `owner_identity`
only, ignore `workspace_id` for retrieval purposes, at least initially. This
requires zero change to `HybridMemoryRetrieval`'s scoping logic or the locked
constant's usage — `workspace_id` becomes a pure data-model / provisioning
concept that never enters the retrieval query. This is the safer default
specifically because it requires no change to a locked, verified subsystem.
If workspace-scoped retrieval turns out to be genuinely wanted, it should be
a deliberate, separate, explicitly-approved change to the retrieval scoping
logic — not a side effect of adding workspaces. **This tradeoff needs a human
decision before implementation**, not a default baked in silently; it is
listed again under Open Questions.

## Migration Path for Existing Runs

`workspace_id` is nullable, so existing runs need no migration at write time.
For read-time UX (a workspace switcher needs *something* to show for
history predating workspaces), the two real options:

1. **Backfill an implicit default workspace per existing `owner_identity`.**
   A one-time migration: for every distinct `owner_identity` present in
   `migration_runs`, create a `Workspace` row (`name="Default"`,
   `is_default=True`, no stored connection — since there's no way to recover
   what connection URL each historical run actually used, that field stays
   `NULL` for backfilled workspaces), then set `migration_runs.workspace_id`
   to that owner's default workspace for every existing row. New runs going
   forward require picking (or defaulting to) a workspace.
2. **Workspaces apply only going forward; historical runs stay
   `workspace_id = NULL`.** Simpler migration (no backfill needed), but the
   run-history UI then needs an explicit "no workspace (legacy)" bucket
   forever, which is a permanent UI wart rather than a one-time migration
   cost.

Recommend (1) — the backfill is cheap (one migration, one UPDATE per
distinct owner), and it avoids a permanent "legacy runs" special case in
every workspace-scoped UI view from day one.

## UI Surface Needed

- **Workspace switcher**: sidebar-level control (the dead `team-switcher.tsx`
  scaffolding is visually close to this shape but should be rebuilt against
  real data, not resurrected as-is — it currently has no loading state, no
  empty state, and no create-flow wired to anything).
- **Workspace-scoped run history**: `migrations/history` filtered by the
  active workspace; the existing `owner_identity` query-param pattern already
  used throughout `runs.py` (`?owner_identity=`) extends naturally to
  `?workspace_id=`.
- **Workspace settings**: name, stored connection (create/replace/test), a
  "created N runs" or "last used" summary. This is also where the recurring
  "paste your `database_url` on every discover call" friction noted in
  `docs/backendfix.md`'s Part B UI notes actually gets solved — a real,
  concrete UX win, just not one worth taking on now given the deadline.
- **Workspace creation flow**: name + connection, likely reusing the
  existing `ConnectDatabaseFields` component (`current-migration-workspace.tsx`)
  rather than building new connection-entry UI from scratch.

## Feasibility Before August 18

Not recommended. Reasons, concretely:

- This is a new table, a new FK, a backfill migration, and — the part that
  actually carries risk — a real product decision about retrieval scoping
  that has to be made correctly, not guessed under time pressure, because
  getting it wrong degrades the demo's core differentiator.
- Every existing route that currently trusts `owner_identity` alone
  (`get_owned_run`, the memory browser, the accuracy metrics endpoint, the
  approval flow) would need to be reviewed for whether it also needs
  `workspace_id` awareness, which is a wide surface to touch carefully in
  two weeks alongside whatever else is still open before the deadline.
- It is a **prerequisite** for Feature 3 (GitHub integration — see that
  document's "credential problem" section), but Feature 3 itself is also not
  recommended before August 18, so there's no forcing function to rush this.

## Open Questions

- **Retrieval scoping** (flagged above): owner-wide or workspace-scoped?
  Needs an explicit decision from whoever owns the product's memory/retrieval
  narrative before implementation — this plan's default recommendation
  (owner-wide, unchanged) should not be treated as already decided just
  because it's the path of least resistance.

The memory retrieval should be like every single migration ran should be in the memory, and every migration that does run will use that same memory database and all of the migrations taken into account before proceeding with the user's current one.

- Does a workspace's stored connection get validated (a real read-only test
  connection) at creation time, or only lazily on first `discover`? Affects
  whether workspace creation needs its own AWS round-trip.
- Can a workspace be deleted while it still has runs? If `ondelete="SET NULL"`
  on `migration_runs.workspace_id` is kept as proposed, deleting a workspace
  just orphans its runs back to "no workspace" rather than cascading — is
  that the right default, or should deletion be blocked while runs exist?
- Does `Workspace.connection_secret_arn` reuse the exact same Secrets Manager
  naming convention (`migration-oracle/connections/{id}`) keyed by
  `workspace_id` instead of `run_id`, or does it need a different prefix to
  avoid any possible collision with the existing per-run secret names? (Low
  risk — UUIDs don't collide — but worth a one-line confirmation before
  implementation, not an assumption.)


  Do the recommended action based on what is needed.

## Prompt

Paste the following into a fresh session, after August 18, to build this
feature:

```
Read docs/FUTURE_WORKSPACES_PLAN.md in full before doing anything else, then
read docs/backendfix.md's "Decisions already locked" section — do not
relitigate anything listed there. This plan's schema proposal, migration
path, and UI surface are your starting point, not a suggestion to redesign
from scratch; deviate only if you find something in the current codebase
that has changed since this plan was written; and it's a good idea to update
docs/backendfix.md's Change Log if you make a decision that is not covered
in this doc's "Open Questions" section.

Before writing any code, resolve the "Open Questions" section of this plan —
in particular the retrieval-scoping tradeoff (owner-wide vs workspace-scoped
memory retrieval), which this plan deliberately left as a decision for a
human, not a default to assume. If a human decision has already been made
since this plan was written, follow it and cite where it was made. If not,
ask before touching `app/memory/retrieval.py`.

Then implement, in this order: (1) the `workspaces` table + migration +
backfill of existing runs into implicit default workspaces, (2)
`migration_runs.workspace_id`, (3) wiring `discover` to default
`connection_secret_arn` from the active workspace when present, (4) the
workspace-scoped run history query param, (5) the frontend workspace
switcher and settings UI (do not resurrect components/team-switcher.tsx or
components/nav-projects.tsx as-is — they are dead shadcn template scaffolding
with no real data wiring; either delete them or rebuild against the real
workspace API).

Verify with real evidence, not just passing unit tests: create two workspaces
under one owner_identity with two different stored connections, run a
migration under each, and confirm (a) each run's discover step correctly
used its workspace's stored connection without the user re-pasting a URL,
and (b) memory retrieval behaves according to whatever scoping decision was
made in step one — if owner-wide, confirm a lesson from workspace A's run
surfaces during workspace B's prediction; if workspace-scoped, confirm it
does not. Run the full backend test suite and frontend typecheck before
reporting done.
```
