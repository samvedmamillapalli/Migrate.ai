# Migration Oracle — Final Push Plan (deadline Aug 18)

Owner split: Samved (backend / AWS orchestration / predict→verify→grade→remember
loop) executes this plan. Samrita owns frontend/dashboard/corpus — flag anything
that steps on her surface area before touching it live.

This doc has two parts: **Part 1** is the execution plan, 45-minute blocks,
ordered by dependency. **Part 2** is two ready-to-paste prompts for a coding LLM
to execute Part 1 without check-ins.

---

## Part 1 — Execution Plan

Legend: **[MUST]** = judging-visible or submission-required. **[NICE]** = cut
first if time runs out.

### Block 1 — Fix the connection status indicator [MUST]

**What:** The sidebar workspace switcher shows "No connection set" and only
flips to a connected state after a migration has actually been *submitted* —
looks broken well before that, since a user can legitimately set up a
connection without yet running anything.

**Hypothesis to confirm first, not assumed fact:** the indicator is very
likely reading a per-*run* signal (something like `dbAttached = Boolean(run
?.connection_secret_arn) || run?.schema_discovery_status === "succeeded"` in
the current-migration workspace) instead of the *workspace's own* persisted
connection field. If so, the fix is sourcing the indicator from the
workspace record itself, not from whatever the most recent run happened to
do.

**Prerequisites:** none.

**Done when:** setting up a workspace connection (without submitting any
migration) immediately shows "connected" in the sidebar, in both the demo
workspace and a fresh one; existing per-run behavior is unaffected.

---

### Block 2 — Research & define 10 real-world seed schemas [MUST]

**What:** Pick 10 realistic ~40-column table schemas, each adapted from a
real, well-known open-source project's actual schema (not invented from
scratch) — go find the real column names/types via the project's public
migration files or model definitions, don't guess. Good starting points,
one domain each so the demo reads as a plausible multi-tenant SaaS customer
database: WordPress `wp_users`/`wp_posts`, Discourse `users`/`topics`,
GitLab/Gitea `issues`/`merge_requests`, Chatwoot `contacts`/`conversations`,
Cal.com `bookings`, PostHog `persons`/`events`, Redmine `issues`, Odoo
`res.partner`, a Shopify/Magento-style `products` table, a Stripe-style
`invoices`/`subscriptions` table. Trim/pad each to land near 40 columns —
not 150+, not a bare 10.

**Prerequisites:** none — can run in parallel with Block 1, but do it
first since Blocks 3–5 depend on it.

**Done when:** a short doc (or the top of the generator script from Block 3)
lists all 10 tables, their source project, and their real column list with
types.

**Split/merge note:** this is real research against 10 different repos —
if it's genuinely running long, timebox it hard at 45 min and accept
"good enough, clearly real-shaped" column lists over perfect fidelity.
Don't let this one block eat the whole session.

---

### Block 3 — Build the seed-data generator [MUST]

**What:** One script (Python, matching the pattern already used for the
IRS dataset generator in `test-data/`) that emits, per schema from Block 2:
a `CREATE TABLE` statement and an `IMPORT INTO`/batched `INSERT` seeding
under 10,000 rows of plausible fake data typed to match each column. Reuse
the CockroachDB-shell-ready format already established in
`test-data/irs_soi_zip_income/` (numbered files, a README, primary keys
matching the table's natural grain, no synthetic surrogate keys unless the
real source table uses one).

**Prerequisites:** Block 2 (needs the real column lists).

**Done when:** running the script produces 10 `CREATE TABLE` + seed-data
SQL files without manual per-table hand-editing.

---

### Block 4 — Generate, validate, and package the seed SQL [MUST]

**What:** Run the Block 3 generator, sanity-check the output (column types
make sense, row counts are under 10k, no reserved-word collisions with
CockroachDB), and package into copy-paste-ready files matching the existing
`test-data/<dataset>/README.md` pattern — plus a fallback path if any table
hits CockroachDB Cloud IMPORT restrictions (inline batched INSERTs, same
approach as the existing `03_fallback_inline_inserts` file).

**Prerequisites:** Block 3.

**Done when:** all 10 tables load cleanly into a real CockroachDB Cloud SQL
shell with zero errors, verified by actually running them once.

---

### Block 5 — Write the demo migration document [MUST]

**What:** A separate doc containing exactly one fake migration statement
(e.g. `ALTER TABLE ... ADD COLUMN ...` or `CREATE INDEX ...`) against one of
the newly-seeded tables, chosen to produce a visually interesting result in
the dashboard (a real backfill, not a no-op) — plus the exact click-path to
run it through the app end to end (which workspace, which connection, what
to paste where).

**Prerequisites:** Block 4 (needs a real seeded table to target).

**Done when:** the doc is copy-paste-runnable start to finish by someone
who has never used the app before.

---

### Block 6 — Profile the critical path, pick one backend fix [MUST]

**What:** A meaningful chunk of backend optimization already happened
(SSE payload trimming, N+1 avoidance on the run-detail path, response
caching on Overview analytics, poll-interval tuning, an auth-bridge race
fix — see `docs/backendfix.md`'s recent entries, and `TODO.md`'s
"Performance Optimization Checklist," which explicitly logs what was tried
and what was deliberately *not* done, with reasons — don't redo those).
Fresh, not-yet-covered territory worth 45 minutes: either (a) close the
still-open item flagged earlier — the SSE stream, the REST poll, and the
globally-mounted `ShadowExecutionWindow` widget all independently poll live
run data during a shadow execution, 3–5x more requests than needed — or (b)
audit cold-start latency on the 7 shadow-orchestration Lambdas, which is
real AWS-level latency this app hasn't specifically profiled yet. Pick
whichever has higher demo-visible impact once you look.

**Prerequisites:** Block 4 (profile against the newly-seeded, more
realistic data, not the sparse demo data).

**Done when:** you've picked one concrete fix and written down (a
sentence is enough) why it beats the alternative.

---

### Block 7 — Implement the chosen backend fix [MUST]

**What:** Implement whatever Block 6 selected.

**Prerequisites:** Block 6.

**Done when:** the fix is verified live (not just unit-tested) — a shadow
run, or a Lambda cold invoke, whichever applies, and the improvement is
directly observed, not assumed.

---

### Block 8 — Broader query/index/cold-start audit [NICE]

**What:** Whichever of the two Block 6 options *wasn't* picked, done as a
lighter pass if time allows. First cut if the plan is behind schedule.

**Prerequisites:** Block 7.

**Done when:** either done, or explicitly skipped with a one-line reason
in the final summary.

---

### Block 9 — Scaffold the memory browser inside Settings [NICE]

**What:** The standalone Agent Memory page and nav item already exist and
work — this is a relocation/IA decision, not new functionality. Reuse its
existing data-fetching logic (same backend endpoint, same list/detail
shape) inside a new section of the Settings page, replacing the current
"Agent memory: N memories indexed · Browse corpus →" stub link with the
real inline view.

**Prerequisites:** none functionally, but do it after the backend blocks
so Settings isn't mid-edit while you're touching shared data-fetching code.

**Done when:** the memory list renders inside Settings with real data,
loading/empty/error states intact.

---

### Block 10 — Remove the standalone memory page, finish the move [NICE]

**What:** Delete the standalone `/dashboard/memory` route and its sidebar
nav item now that Settings has the real view; fix any internal links that
pointed at the old route (the Settings stub link itself, and anywhere else
in the app that links to Agent Memory).

**Prerequisites:** Block 9.

**Done when:** no route in the app still points at the removed page; nav
sidebar no longer shows a standalone Agent Memory item.

**Split/merge note:** Blocks 9+10 are a solid candidate to merge into one
90-minute block if reusing the existing data-fetching hook turns out to be
a straight import (likely, since it's the same backend endpoint either way).

---

### Block 11 — Draft the architecture diagram content [MUST]

**What:** Before touching a diagramming tool, write down the actual
structure: predict (FastAPI + Bedrock) → approve (human) → verify (Step
Functions: discover-schema → provision-shadow-cluster [CockroachDB Cloud,
`ccloud_api`] → load-schema → execute-migration → collect-metrics →
persist-results → cleanup) → grade → remember (vector-indexed memory,
CockroachDB's own Distributed Vector Index). Note the two planes clearly:
FastAPI control plane (predict/approve stay off Step Functions, SFN starts
only after human `proceed`) vs. the AWS execution plane (Lambdas + SFN).
Include Clerk auth, CockroachDB Cloud (both control-plane DB and disposable
shadow clusters), and the frontend (Next.js) as boxes.

**Prerequisites:** none — can run any time, but do it after Block 7 so the
diagram reflects the current, not soon-to-change, backend shape.

**Done when:** you have a clear box-and-arrow structure written down (even
as a rough sketch/outline) that block 12 can render directly.

---

### Block 12 — Produce the final diagram + submission blurb [MUST]

**What:** Render the Block 11 structure as an actual diagram (this repo
already has an `artifact-diagramming` pattern available — use it, or any
tool that produces a clean exportable image), and write the short
paragraph explaining it for the submission's judging-criteria / additional
info section — lead with the closed-loop differentiator ("predict, verify
on a real disposable cluster, grade, remember" — no competitor does the
verify step), not a generic architecture summary.

**Prerequisites:** Block 11.

**Done when:** you have an exported image file plus the accompanying
paragraph, both ready to paste into the submission.

---

### Block 13 — Full end-to-end dry run [MUST]

**What:** Using the seeded data (Block 4) and the demo migration doc
(Block 5), actually click through the entire app exactly as a judge or the
demo video would: connect → discover → predict → approve → shadow →
grade → remember, on the real, now-vibrant dashboard. Fix anything broken
that surfaces — this is the last chance before recording.

**Prerequisites:** Blocks 1, 4, 5, 7 (and 9/10 if not skipped).

**Done when:** one full run completes cleanly with no visible errors,
console clean, dashboard showing real populated charts.

---

### Block 14 — Write the demo video script [MUST]

**What:** A timed storyboard — what's on screen, what's said, in what
order, hitting: the problem (blast radius is normally a guess), the
differentiator (real verification on a disposable cluster, not a static
linter), a live run using the seeded data from Block 4/5, the memory/grade
result closing the loop. Keep it tight — most hackathon demo videos run
2–4 minutes.

**Prerequisites:** Block 13 (the script should describe a run you know
actually works).

**Done when:** a written script exists with rough timings per beat.

---

### Block 15 — Record, edit, export the demo video [MUST]

**What:** Record following the Block 14 script, do one edit pass, export
in whatever format the submission requires.

**Prerequisites:** Block 14.

**Done when:** final video file exists and has been watched start to
finish once by you.

**Split/merge note:** recording almost always needs more than one take —
treat this as a soft 90-minute block (recording + editing as two natural
sub-passes) rather than a strict 45, and don't schedule anything
immediately after it on a tight day.

---

## Part 2 — Execution Prompts

Paste **Execution Prompt 1** first. Once that session finishes (or you've
used up the budget you gave it), paste **Execution Prompt 2** into the next
one, with this same planning doc attached/pasted alongside it.

### Execution Prompt 1

```
You're executing a planning doc for Migration Oracle, a CockroachDB x AWS
hackathon project with a hard deadline. The full plan is pasted below (or
attached) — 15 blocks of ~45 minutes each, already ordered by dependency
and flagged [MUST]/[NICE].

First, convert every block into your own todo list, one todo per block, in
the exact order given — don't reorder them, the ordering encodes real
dependencies.

Then begin implementing Blocks 1 through 7 in order. For each block:
write the actual thing it describes — real, runnable CockroachDB SQL for
the seed-data blocks, real working code in this repo following its
existing conventions for the connection-status and backend-optimization
blocks, a real written document for the demo-migration doc. Do not produce
descriptions of what should be built — build it.

Do not ask me clarifying questions and do not check in with me between
blocks. If a block leaves an implementation detail open, make the most
sensible, hackathon-pragmatic call yourself, note the choice briefly when
you report back, and keep moving. Verify each block against its own "done
when" criteria before moving to the next — don't just write code and
assume it works, actually run/test it the way the block describes.

Stop after Block 7 is done and verified. Give me a concise summary: what
you did per block, any judgment calls you made, and anything that looks
like it'll affect Blocks 8–15.
```

### Execution Prompt 2

```
Continue executing the same Migration Oracle planning doc from where the
last session left off (Blocks 1–7 done). The full plan is pasted below
again for reference.

Complete Blocks 8 through 15, in order. Same rules as before: no
clarifying questions, no check-ins mid-plan, verify each block against its
own "done when" criteria before moving on, make pragmatic calls yourself
on anything left open.

If you're running short on time or budget partway through, skip [NICE]
blocks only — never skip a [MUST] block. If a [MUST] block genuinely can't
be completed (e.g. it needs a live credential or human action you don't
have), do as much of it as you can and clearly flag the remaining human
step rather than skipping it silently.

When you're done (or you've made the call to stop), end with three
explicit lists:
1. Every block completed.
2. Every block skipped, and the specific reason (not "ran out of time" —
   what specifically didn't fit, and why it was the lowest-priority thing
   left).
3. Anything a human still needs to do before the Aug 18 submission that
   you could not do yourself (e.g. actually pressing "record," clicking a
   real OAuth consent screen, anything needing a live credential).
```
