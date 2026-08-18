# Cross-customer collective memory — implementation plan

Written 2026-08-03. This is a **post-hackathon** feature — it assumes the app
is already deployed with real, separate paying customers, which is not true
today (everything currently in `migration_memories` is either your own graded
runs or the seeded open-source corpus under `CORPUS_OWNER_IDENTITY`). Nothing
here should be built before that's true, except the parts explicitly marked
"buildable now" in §9.

## The pitch, one paragraph

Today, memory retrieval is scoped to `[your owner_identity, CORPUS_OWNER_IDENTITY]`
— you only ever benefit from your own graded history plus the curated
open-source corpus. Cross-customer memory adds a third tier: an anonymized,
opt-in pool where a graded outcome from Company A (stripped of every
identifying detail — table names, column names, actual literals, actual
schema) can surface for Company B when B's migration has a similar *shape*.
Company B never sees A's schema, SQL, or identity. The value compounds with
usage — more customers means more shapes covered means better predictions for
everyone — which is the actual "agentic memory" network-effect story, not
just a bigger corpus.

## Hard constraints — read before designing anything else

These are non-negotiable, decided up front, not something to relax under
implementation pressure:

1. **Opt-in, default OFF, per `owner_identity`.** Nothing from an account is
   ever eligible for the shared pool unless that account explicitly turned it
   on. No "you can opt out later" — no data leaves the private tier until
   consent is affirmatively given first.
2. **No raw identifiers ever leave the anonymization boundary.** Not table
   names, not column names, not literal values, not connection strings, not
   schema summaries containing them. The anonymization pass runs
   server-side, in the same transaction/process boundary as everything else
   that already touches this data — never send raw content to a third party
   or a less-trusted step before it's been through the pipeline in §3.
3. **The shared-pool table stores no tenant identity at all.** Not a
   pseudonym, not a hashed ID — nothing. If the row can't be traced back to
   an account even if the database were fully compromised, "which customer
   contributed this" isn't a secret that can leak, because it isn't stored.
   This is the actual privacy guarantee, not a policy promise on top of
   identifying data.
4. **This needs real legal review before it ships**, not just engineering
   review. ToS/DPA updates, consent language, and a GDPR/CCPA read on what
   "anonymized" has to mean to actually qualify as anonymized (aggregation
   and k-anonymity thresholds, not just "we removed the names") are a
   lawyer's call, not an engineering one. Flag this to whoever owns that at
   the company before Phase 2 (the opt-in toggle going live) ships.

## Current architecture — what this builds on

Verified against the real code, 2026-08-03:

- `migration_memories` (`backend/app/database/models/migration_memory.py`) —
  one row per graded run, `owner_identity` column, `embedding VECTOR(1024)`.
  `CORPUS_OWNER_IDENTITY = "__migration_oracle_corpus__"`
  (`app/memory/constants.py`) is the one existing reserved, non-tenant scope.
- Two CockroachDB Distributed Vector (`cspann`) indexes on that table
  (`alembic/versions/m8h4e1f7a596_vector_index_prefix_columns.py`):
  `ix_migration_memories_embedding_scoped` (partial, `owner_identity` as
  prefix column — owner-scoped retrieval) and
  `ix_migration_memories_embedding_ready` (partial, corpus-wide search).
  Adding cross-customer memory means a **third index on a new table**, not
  reusing either of these — see §5.
- `HybridMemoryRetrieval.retrieve()` (`app/memory/retrieval.py`) currently
  queries `owner_identities=[owner, CORPUS_OWNER_IDENTITY]` and re-ranks
  candidates on five weighted factors (semantic similarity, migration-type
  match, scale-tier proximity, schema shape, risk-flag overlap) — see
  `app/repositories/migration_memory_repository.py::vector_candidates`.
  Cross-customer memory becomes a **third source merged into the same
  re-rank**, not a separate retrieval path the caller has to know about.
- `compose_embed_text()` (`app/memory/embed_text.py`) already de-emphasizes
  raw DDL by design — "Summaries that are just pasted SQL are stripped down
  to a type hint so Titan matches on mechanism... rather than SQL
  vocabulary." The anonymization pipeline in §3 is a stricter version of a
  principle this codebase already applies, not a new one.
- `sqlglot.parse(sql, dialect=DIALECT)` is already the app's SQL-parsing
  tool of choice (`app/policy/engine.py`), which is what the anonymizer in
  §3 should build on rather than hand-rolling a parser.
- There is currently **no org/team concept** — `owner_identity` is an
  individual account. Per your own earlier planning notes, "shared team
  memory" was explicitly scoped as future, not built. This plan follows
  that: consent is per-`owner_identity` (see §6), and an org-level opt-in
  would need the org concept to exist first — don't build that here.
- The existing UI pattern for "this memory isn't your own graded run" is
  already established: `integrity_block()` in
  `app/memory/open_source_corpus.py` produces `not_a_graded_run`,
  `exclude_from_accuracy_metrics`, and a `ui_label` shown in the memory
  panel. Cross-customer memories get a fourth `memory_origin` value in this
  same system (§4), not a parallel one.

## 1. Data model — a new, deliberately minimal table

```sql
CREATE TABLE cross_customer_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- No owner_identity, no org id, no hashed/pseudonymous identity of any
    -- kind. This is the actual privacy guarantee — see Hard Constraint 3.

    shape_hash STRING NOT NULL,        -- dedup/aggregation key, see §7
    migration_type STRING NOT NULL,
    scale_tier STRING NOT NULL,
    parsed_statement_types JSONB NOT NULL,

    -- Generalized text only — every field here has already been through
    -- the anonymization pipeline (§3) before this row is written.
    generalized_summary TEXT NOT NULL,
    generalized_risk_narrative TEXT NOT NULL,
    generalized_lessons_learned TEXT NOT NULL,
    generalized_surprise_notes TEXT,
    sql_shape_template TEXT NOT NULL,  -- see §3 step 1; identifiers replaced

    risk_flags JSONB NOT NULL,         -- rule_id + severity only, no message text
                                        -- with schema-specific wording (see §3 step 2)
    outcome_class STRING NOT NULL,
    scalar_accuracy_score FLOAT8,

    embedding VECTOR(1024),
    embedding_status STRING NOT NULL DEFAULT 'pending',

    contributor_count INT NOT NULL DEFAULT 1,  -- incremented on dedup match, never
                                                -- a list of who — see §7
    first_contributed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_contributed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_cross_customer_memories_shape_hash ON cross_customer_memories (shape_hash);

CREATE VECTOR INDEX ix_cross_customer_memories_embedding_ready
  ON cross_customer_memories (embedding vector_cosine_ops)
  WHERE embedding_status = 'ready';
```

Why a new table and not a new `owner_identity` sentinel on `migration_memories`
(the way `CORPUS_OWNER_IDENTITY` works today): `migration_memories` rows carry
`schema_summary`, `migration_summary`, and other fields that are allowed to
contain real identifiers for the owner/corpus tiers. Reusing that table for
cross-customer data means every future column added to `migration_memories`
has to be re-audited for whether it's safe to expose across tenants. A
separate table with a narrow, append-only, anonymization-only column set
makes "can this leak a real identifier" a question you only have to answer
once, at the table boundary, not on every future migration.

## 2. Consent model

New table, not a column on `app_users` — `app_users` is the legacy
custom-auth table and doesn't have a row for every Clerk-authenticated user,
but `owner_identity` is the one scoping key that's universal across both auth
paths:

```sql
CREATE TABLE memory_sharing_preferences (
    owner_identity STRING PRIMARY KEY,
    cross_customer_sharing_enabled BOOL NOT NULL DEFAULT false,
    enabled_at TIMESTAMPTZ,
    disabled_at TIMESTAMPTZ
);
```

`enabled_at`/`disabled_at` matter for §8 (what happens on opt-out) even
though there's no per-row identity to delete — see that section.

## 3. The anonymization pipeline — the technical core

Runs once, server-side, when a graded run becomes eligible for promotion
(§6). Every step is designed so a failure at any point **skips promotion,
never partially promotes** — this is enrichment on top of an already-complete
grade, same posture as everything else in this app that touches
enrichment (MCP investigation, changefeeds, Slack notifications): best-effort,
never allowed to block or corrupt the thing it's built on top of.

**Step 1 — SQL shape template (sqlglot).** Parse `migration_sql` with the
same `sqlglot.parse(sql, dialect=DIALECT)` already used in
`app/policy/engine.py`. Walk the AST and replace every table identifier with
`TABLE_1`, `TABLE_2`, ...; every column identifier with `COL_1`, `COL_2`,
...; every literal value with a type placeholder (`<int_literal>`,
`<string_literal>`). Keep: the statement type, data types, constraint types
(`NOT NULL`, `UNIQUE`, `REFERENCES`), and structural shape (`CONCURRENTLY`,
number of columns touched). Result:
`ALTER TABLE TABLE_1 ADD COLUMN COL_1 INT NOT NULL DEFAULT <int_literal>;`
— genuinely useful for shape-matching, genuinely free of anything specific to
the contributing account.

**Step 2 — structural metadata only.** Keep `migration_type`, `scale_tier`,
`parsed_statement_types`, `index_count`, `table_complexity` as-is — these
are already scalars/enums with no identifying content. For `risk_flags`,
keep only `rule_id` and `severity`; **drop the `message` field** even though
today's messages are mostly static policy-engine text
(`app/policy/policy.yaml` explanations) — don't rely on that staying true
forever, since a future risk flag generator could start writing
per-run-specific messages, and this pipeline shouldn't have to be revisited
every time something upstream changes.

**Step 3 — narrative generalization (Bedrock).** `risk_narrative`,
`lessons_learned`, and `surprise_notes` are LLM-written prose from the
original prediction/grading pipeline and can plausibly mention real
identifiers if the model happened to reference the actual table/column
names. Run a dedicated Bedrock pass (same client already wired in
`app/prediction/bedrock_client.py`) with a strict system prompt: rewrite the
text replacing every concrete identifier with a generic structural
description ("the target column", "the affected table"), preserve the
*mechanism* being described, output nothing that isn't already generic.
Feed it the Step-1 identifier list explicitly so it knows exactly what to
scrub, not just "use your judgment."

**Step 4 — defense-in-depth validation.** After Step 3, regex/substring-check
the generalized text against the *original* real identifiers (pulled from
the run's `schema_snapshot`, not from the LLM's own output) before allowing
promotion. If any real identifier survived the LLM pass, **fail the
promotion, log it, do not retry with a "try harder" prompt** — treat it as a
pipeline bug to fix, not something to paper over per-run.

**Step 5 — separate embedding.** Embed the generalized text with the same
Titan client, but as its **own** `compose_embed_text()`-style call using only
the generalized fields — never reuse or derive from the original
private-tier embedding. The vector itself must carry no signal from the
original, not just the display text.

## 4. Retrieval integration

Extend `HybridMemoryRetrieval.retrieve()` to add a third source:

```python
cross_customer = await self._cross_customer_repo.vector_candidates(
    query_vector_literal=literal,
    limit=pool,
)
```

Merge into the same candidate list before re-ranking, with a new
`memory_origin` value (`app/memory/constants.py`):

```python
MEMORY_ORIGIN_CROSS_CUSTOMER = "cross_customer_anonymized"
```

Surface it through the same `integrity_block()`-style mechanism already used
for open-source corpus entries, with a UI label along the lines of
`"Anonymized pattern from {contributor_count} other teams"` — reusing the
existing "documented incident, not your graded run" visual treatment
(`ui_label`, dashed-border distinction) rather than inventing a new one.

**Re-rank weighting is an open question, not a default to invent silently**
— see §10. A defensible starting point: weight cross-customer results below
the account's own history but above the generic open-source corpus, since
it's real (if anonymized) production outcome data, closer to what the user's
own future runs will look like than a public GitHub incident is.

## 5. Promotion pipeline — when does a graded run get shared

Hook into `MemoryWriteService.write_memory()` (`app/memory/writer.py`),
which already runs once per graded run. After the existing private-tier
write succeeds:

```python
if await self._sharing_prefs.is_enabled(run.owner_identity):
    await self._cross_customer_promoter.try_promote(run, prediction, execution, grade)
```

`try_promote` runs the full §3 pipeline and is wrapped exactly like every
other enrichment in this app — logged on failure, never raised, never
blocks the run from completing. Matches the existing pattern in
`workflow_orchestration_service.py`'s Slack/ccloud-audit hooks precisely:
enrichment that can't fail the thing it's attached to.

## 6. Consent enforcement — where it actually gets checked

Two places, not one, since either alone is insufficient:

1. **At promotion time** (§5) — the account must currently be opted in.
2. **At the settings toggle itself** — flipping `cross_customer_sharing_enabled`
   to `true` should show, before confirming, a real example of what a
   generalized record looks like (run one of the account's own past graded
   runs through §3 live and show the actual output) — not an abstract
   privacy policy link. Consent needs to be informed, and "here's literally
   what would have been shared from your last migration" is a much stronger
   informed-consent pattern than a checkbox next to legal text nobody reads.

## 7. Dedup and aggregation

Many accounts will hit structurally identical patterns (the Step-1 template
plus scale_tier plus outcome_class is a natural collision key). Hash that
tuple into `shape_hash`. On promotion:

- No existing row with that hash → insert, `contributor_count = 1`.
- Existing row with that hash → **do not insert a near-duplicate.**
  Increment `contributor_count`, bump `last_contributed_at`, and only replace
  the stored generalized text if the new contribution's grade is more
  extreme (a worse outcome than what's stored is more valuable to warn
  future users with; a routine clean success replacing an existing routine
  clean success teaches nothing new).

This does double duty: it caps table growth (thousands of contributions of
the same common pattern become one row, not thousands), and
`contributor_count` becomes real, honest product copy — "this exact pattern
has been seen by N other teams" is a materially stronger trust signal than
"we found a similar migration," and it's true by construction, not
marketing.

## 8. What opt-out actually means

Because no tenant identity is ever stored (Hard Constraint 3), there is no
per-account row to delete when someone disables sharing — nothing on
`cross_customer_memories` points back to them to find. This has to be
disclosed as part of consent (§6), not discovered later: **once contributed,
a generalized pattern remains in the aggregate pool even after you turn
sharing off; turning it off only stops future contributions.** If this isn't
acceptable, the alternative is retaining a private, encrypted
contribution-to-row mapping solely to enable deletion — which reintroduces
exactly the identity-linkage risk Hard Constraint 3 exists to avoid, so
weigh that trade-off explicitly (with legal, per Hard Constraint 4) rather
than defaulting either way silently.

## 9. What's buildable now vs. what needs real customers

Everything above needs real, separate paying customers to be *meaningful* —
but the pipeline can be built and proven today with two synthetic accounts:

1. Create two distinct `owner_identity` values (`demo-company-a`,
   `demo-company-b`), each opted into sharing.
2. Run a real graded migration under `demo-company-a` that produces a
   distinctive, non-trivial outcome (e.g. a NOT NULL backfill that ran over
   the predicted band).
3. Confirm §3 produces a genuinely identifier-free generalized record, and
   §5 promotes it into `cross_customer_memories`.
4. Run a *shaped-similarly but not identical* migration under
   `demo-company-b` and confirm retrieval (§4) surfaces the Company A
   pattern, labeled correctly, with `demo-company-b` never seeing Company
   A's real schema or SQL anywhere in the response.

This is a real, honest way to prove the whole mechanism end-to-end before
a single real second customer exists — and it's exactly the kind of live
verification this project has held itself to everywhere else (see
`docs/cockroach_hookup.md`'s evidence-over-assertion standard). Don't claim
this feature works without having actually run that four-step proof.

## 10. Open questions — yours to decide, not the LLM's to assume

- **Minimum threshold to bother sharing.** Promoting every trivial
  low-risk additive change adds noise, not signal, to the shared pool. Is
  there a minimum severity/scale bar before something's worth promoting?
- **Cross-customer re-rank weight** (§4) — below, at, or above the
  account's own history in the hybrid re-rank?
- **Manual review queue for early promotions**, or fully automatic from
  day one? A human-reviewed queue for the first N promotions (catch
  anonymization pipeline bugs before they compound) is safer but slower to
  prove the network effect.
- **Per-user opt-in now, or wait for the org concept?** This plan assumes
  per-user, matching current `owner_identity` scoping — reconsider once/if
  teams/orgs exist, since individual opt-in inside a company that hasn't
  agreed as an org is a different consent story.

---

## Prompt

Paste this into a fresh session once the app is deployed with real,
separate customer accounts and you're ready to build Phase 1 (the pipeline
itself, proven with the synthetic two-account demo in §9 — not the opt-in
UI or automatic promotion hook yet, those are later phases once Phase 1 is
proven and the open questions in §10 are answered):

```
Read docs/cross_customer.md in full before doing anything else — it's the
plan for this task, already reviewed and approved. Build Phase 1 only:

1. The cross_customer_memories table (§1) and its vector index, as an
   Alembic migration matching this repo's existing style (see
   alembic/versions/m8h4e1f7a596_vector_index_prefix_columns.py for the
   partial-cspann-index pattern, and any recent migration for the
   idempotent existence-check style CockroachDB's per-statement DDL commit
   behavior requires here).
2. The anonymization pipeline (§3) as a standalone, independently testable
   module — sqlglot-based identifier stripping (step 1), a Bedrock
   generalization pass (step 3) using the existing BedrockClient, and the
   defense-in-depth identifier check (step 4). Write real unit tests that
   assert a known identifier from a fixture migration_sql/schema_snapshot
   does NOT appear anywhere in the pipeline's output — that's the test that
   actually matters here, not just "it runs."
3. Dedup/aggregation (§7) — the shape_hash computation and the
   insert-vs-increment logic.
4. Retrieval integration (§4) — extend HybridMemoryRetrieval to merge in
   cross_customer_memories candidates, with the new MEMORY_ORIGIN_CROSS_CUSTOMER
   constant and integrity-block treatment matching the existing open-source
   corpus pattern.
5. A manual promotion script (NOT the automatic write_memory hook from §5 —
   that's Phase 2, after §10's open questions are answered by the user) so
   Phase 1 can be driven and verified by hand.
6. Run the exact four-step synthetic-account proof in §9 for real, and
   report the actual evidence — the generalized record content, confirmation
   no real identifier survived anonymization, and the retrieval result
   showing Company B's query surfacing Company A's pattern. Do not report
   this feature as working without that evidence, per this project's
   established standard (see docs/cockroach_hookup.md).

Do not build the opt-in settings UI, the automatic promotion hook wired into
write_memory, or anything from §10's open questions without asking first —
those need explicit answers from the user before they're implementable, not
assumptions. Do not commit or push without being asked.
```
