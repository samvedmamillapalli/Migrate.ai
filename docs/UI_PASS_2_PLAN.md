# UI pass 2 + security review — plan

Written 2026-08-16. Work stays **uncommitted on localhost**, tabled for your next
redeploy. Every item below is traced to a file and line.

---

## A. Layout

| # | Item | Where |
|---|---|---|
| A1 | Top margin too tight — content sits hard against the top edge | dashboard page shells |

Fix: raise the top padding on the dashboard content wrapper so headers breathe.

---

## B. Sidebar

| # | Item | Where |
|---|---|---|
| B1 | "Settings" opens a dropdown; should navigate straight to `/dashboard/settings` | `sidebar-settings-menu.tsx:42-49` |
| B2 | Sign out moves out of the sidebar dropdown, into Settings at the bottom | `sidebar-settings-menu.tsx:67` → `settings/page.tsx` |
| B3 | "Owner Identity" → **"User"** | `app-sidebar.tsx:218` |

---

## C. Settings page removals

| # | Remove | Where |
|---|---|---|
| C1 | "Tied to your account — applies everywhere…" under Theme | `settings/page.tsx` ~229 |
| C2 | "Everyone with access to this workspace's runs and settings." | `workspace-members-panel.tsx:79` |
| C3 | The **Environment** row under Execution | `settings/page.tsx:579` |
| C4 | The **AI prediction** row under Execution | `settings/page.tsx:555` |
| C5 | Add **Sign out** at the bottom (from B2) | `settings/page.tsx` |

---

## D. Loading text + word bank

| # | Item | Where |
|---|---|---|
| D1 | "Calling AWS Bedrock for prediction (us.anthropic.claude-haiku-…)" leaks the model id at the user | `new/page.tsx:803` and `:1039` |
| D2 | Build a whimsical loading word bank (Claude-Code style: *fidgeting, tinkering, pondering…*) and use it wherever a loading caption sits under a spinner/bar | new shared module |

D1 becomes plain **"Prediction running"**. The word bank supplies the *secondary*
caption so loading states feel alive without exposing internals. Words cycle on
a timer and are seeded per-run so they don't reshuffle on every render.

---

## E. Shadow Execution page

| # | Item | Where |
|---|---|---|
| E1 | Drop `run a55d42bf · created 4m ago` | `current/shadow/page.tsx:327` |
| E2 | "Seeding tables … onto mo-a55d42bf95124113…" → "…onto your newly created shadow cluster" | `shadow-live-view.tsx:131` |
| E3 | Delete the "The source side is your own database exactly as discovered…" paragraph | `shadow-cluster-comparison.tsx:610` |
| E4 | "mo-a55… is live." → **"Your shadow cluster is live."** | shadow controls |
| E5 | Event log entries drop `provision_ms=…, ready_ms=…` noise — just the event | `mapShadowEventLog` |

---

## F. Floating side panel

| # | Item |
|---|---|
| F1 | Remove `run a55d42bf · live` header line |
| F2 | Remove the **Prediction vs actual** block entirely from the panel |
| F3 | Remove the **Event log** entirely from the panel |

The panel already accepts `showComparisons` / `showEventLog` props, so this is
passing `false` rather than new code.

---

## G. Migration Run page

| # | Item | Where |
|---|---|---|
| G1 | Remove the small grey `stage.outcome` line under every timeline step (cluster UUIDs, "Running shadow", `policy=allow`) | `[id]/page.tsx:175+` |
| G2 | Remove **Raw stage timings** | `[id]/page.tsx:633` |
| G3 | Remove **Jobs observed** section | `[id]/page.tsx:654` |
| G4 | Remove **Live Change Events** section | `[id]/page.tsx:698` |
| G5 | No `mo-…` cluster names anywhere user-facing | shadow cluster section |

---

## H. Grade / approval flow

The core confusion: "Grade" appears as a raw data dump with no obvious action,
and there is no prompt telling the user what to do once the shadow finishes.

| # | Item |
|---|---|
| H1 | When the shadow run completes, prompt on the Shadow Execution page: the migration was verified, here is what to do next |
| H2 | A **Grade** action at the bottom of the Shadow Execution page |
| H3 | The same action in the floating side panel |
| H4 | The same action on the Migration Run page |
| H5 | Grade display reduced to **what it measured + its status** — drop `dimension_details` JSON, `scalar_formula`, raw error dumps |
| H6 | **Grade** section → collapsed dropdown |
| H7 | **Memory** section → collapsed dropdown |
| H8 | **Model Traces** section → collapsed dropdown |

---

## I. Security review — findings

Checked: auth enforcement, tenancy, credential handling, CORS, debug routes, and
SQL construction.

### 🟡 Finding 1 — SQL identifiers are quoted but not escaped

`app/shadow/seeder.py:429-432`:

```python
return f'"{table.schema_name}"."{table.name}"'
```

Column names are interpolated the same way (`f'"{c.name}"'`). Double quotes wrap
the identifier but an embedded `"` is not doubled, so a table or column named
`foo"; DROP TABLE bar; --` would break out of the quoting.

**Real risk is low but not zero:** identifiers come from a customer's *own*
discovered schema, and the generated SQL runs against a *disposable shadow
cluster*, not their production database. Nothing a customer could inject would
reach their own data or ours. It predates this week's work — `_create_table` and
`_create_indexes` have always done it — but the server-side seeding change added
more interpolation sites, so it is worth closing now.

**Fix:** one `_quote_ident()` helper that doubles embedded quotes, used
everywhere an identifier is interpolated.

### ✅ Clean

- **No credential logging.** Grepped every `logger`/`print` touching
  `connection_url` / `database_url` across the shadow and Lambda handlers —
  zero hits. `ProvisionedCluster` keeps the URL in `__slots__` and its docstring
  states it is never logged or persisted.
- **Auth is enforced, not optional.** `SessionAuthMiddleware` returns 401
  without a valid token; verified live (`GET /runs` → 401).
- **Tenant isolation is structural.** Every `/{run_id}` route resolves through
  `get_owned_run(_with_children)`, so a new route has to actively opt out to
  leak. This week's workspace-member widening is scoped to runs with a non-null
  `workspace_id`.
- **CORS is exact-origin.** Verified live: the console origin is echoed,
  `https://evil.example` gets no header. No wildcards.
- **Secrets at rest.** Customer/shadow credentials live in Secrets Manager, not
  in DB columns; tokens are Fernet-encrypted, and production refuses to start
  without the keys.
- **IAM least privilege** per Lambda: only `persist-results` and
  `execute-migration` reach Bedrock; only `cleanup` can delete a secret.

### ⚪ Noted, not changed

`/runs/debug/demo-with-db` and `/runs/debug/fake-migration` have no environment
guard. `demo-with-db` is the judge demo button and is wanted in production; both
require a valid session and act only on the caller's own runs. Left as-is
deliberately — flagging so it is a decision, not an oversight.

---

## Out of scope

Nothing outside the list above is touched. The three Clerk dashboard items
(name required, app rename, email branding) remain yours.
