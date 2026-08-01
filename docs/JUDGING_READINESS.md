# Judging Readiness — Scorecard & Roadmap

Grades the app against the five stated hackathon criteria, checks the judge
feedback pasted in against the actual code (not assumptions), and lays out
what to do before August 18. Nothing here has been implemented — planning only.

---

## Scorecard

| # | Criterion | Grade | One line |
|---|---|---|---|
| 1 | Agentic Memory Design | **A−** | Real closed loop — CockroachDB holds run state *and* graded vector memory, not just chat logs. |
| 2 | Technical Implementation | **B+** | Engineering is solid; the only real risk is verbal overclaiming about MCP/`ccloud` CLI — and the written docs already avoid it. |
| 3 | Real-World Impact | **A−** | Clear DBA/SRE pain point, credible workflow fit. Sell decision quality, not market size. |
| 4 | Production Readiness | **B** | Better than it looks (real CloudWatch alarms, real Clerk auth) — just not surfaced anywhere a judge would see it. |
| 5 | Creativity & Originality | **A** | The actual differentiator. Verify-and-remember beats RAG-over-docs, and the landing page already leads with it. |

**Overall: competitive**, contingent on the demo actually showing a retrieval hit and a real shadow run, and on nobody saying "we call Managed MCP end-to-end" out loud.

---

## Checked against the code, not assumed

The judge feedback was written from the outside and hedges a lot ("if you
claim...", "may still be soft..."). Here's what's actually true:

- **MCP claim — already framed safely, in two places.** `README.md:40` and
  `docs/HACKATHON_TOOLS.md` both already say "same job surface MCP agents
  use" / "MCP-compatible," never "we call Managed MCP in production." The
  code (`job_watch.py`) backs that up exactly — it's SQL `SHOW JOBS`, labeled
  honestly. **The risk is 100% in what gets said out loud on demo day, not in
  anything written down.** Nothing to fix in docs; just brief whoever
  presents.
- **`ccloud` CLI — already not the default, already documented as such.**
  `SHADOW_PROVIDER=ccloud_api` (REST) is the default; `docs/HACKATHON_TOOLS.md`
  explicitly says not to claim the CLI as a primary tool. Confirmed correct.
- **Auth is not soft anymore.** Judge feedback assumed `owner_identity` is
  always client-supplied. As of this pass, Clerk auth is real and enforced
  (`SessionAuthMiddleware`) whenever Clerk keys are configured on the
  deployment — the only open item is confirming those keys are actually set
  on the **judge-facing** deployment specifically (see roadmap).
- **The landing page already leads with the closed loop.** Headline is
  "Migration Oracle," subtitle is "Predict → verify → grade → remember...
  Distributed Vector Indexing so the next guess is smarter." This is not
  generic "AI migration assistant" copy — no change needed here.
- **CloudWatch alarms are real, not just metric publishing.** `ensure_standard_alarms()` / `put_metric_alarm` exist and create real alarms, not a
  theatrical metrics dashboard. This is stronger than "Observability is
  present but not a polished ops console" suggests — it's just not
  *visible* anywhere in the product UI, which reads as weaker than it is.
- **Corpus is 11 documented open-source incidents + real graded runs from
  this project's own judge walkthrough** — small, but every entry is a real
  incident with a source URL, not synthetic filler, and it's excluded from
  accuracy metrics by an integrity rule enforced in SQL. Worth saying exactly
  that ("designed for multi-tenant memory at serializable isolation; demo
  corpus is intentionally small and fully sourced") instead of hoping nobody
  asks.
- **The one thing that's genuinely unresolved:** exact per-run USD cost for
  the shadow cluster. Still an open question in `backendfix.md` — this is
  the "one crisp sentence on cost" the feedback asks for, and it needs a real
  number from the Cockroach Cloud invoice before it can be said with a
  straight face.

---

## Roadmap

### Now — zero code, highest leverage
1. **Write the exact verbal framing for MCP/`ccloud` into the demo script**,
   copied straight from `HACKATHON_TOOLS.md`'s wording. This is the single
   biggest score-risk in the whole submission and it costs nothing to fix.
2. **Get the real per-run shadow cost in USD** from the Cockroach Cloud
   invoice and put it in the demo script as one sentence.
3. **Confirm Clerk keys are set on the judge-facing deployment**, not just
   local dev — auth being real only helps the score if judges can actually
   see it enforced.
4. **Rehearse the exact 5-beat demo order** the feedback recommends: predict
   with sparse memory → real shadow on CRDB Cloud → grade + memory write →
   second similar migration retrieves the first → one failure beat (abort or
   a blocked policy). This is the sequence that touches all five criteria
   without narration filler.

### Soon — small, concrete changes worth making before demo day
5. **Surface the "production-shaped, not production-scale" framing in the
   product itself**, not just in your head — e.g., a one-line caption near
   the memory browser or accuracy card stating the corpus is a small, fully
   sourced seed set by design. Turns a defensive answer into a stated
   design decision.
6. **Put the CloudWatch alarm story somewhere visible** — a settings/health
   panel line listing what's alarmed (orphaned shadow clusters, workflow
   failures) turns real infrastructure that's currently invisible into a
   scoring point for Production Readiness.
7. **Double-check the memory-retrieval demo beat is bulletproof** — the
   documented requirement is that embedding text is summary/lesson-dominant,
   not raw-DDL-dominant, or the "different SQL, same underlying mechanism"
   retrieval hit (the single most impressive live moment) won't fire
   reliably. Worth a dry run against the actual seeded corpus before demo day,
   not just trusting it works.
8. **Add one sentence to the pitch about multi-tenant isolation** — CockroachDB's serializable isolation is already doing real work here
   (admission control race-safety, owner scoping); it's currently an
   implementation detail nobody would notice unless asked.

### If time allows — bigger lifts, real differentiation
9. **Make the MCP claim literally true instead of "compatible."** Right now
   it's SQL `SHOW JOBS` with an attribution string. Actually calling the
   Managed MCP endpoint (`cockroach_mcp_url`, already configured) for job
   introspection would remove the hedge word entirely — this is a genuine
   technical upgrade, not just a framing fix, and it's the one item on this
   list that turns a defensible answer into an unambiguous one.
10. **A visible fleet/ops view** (which shadow clusters are active right now,
    sweeper history) would make Production Readiness read as "operated," not
    just "resilient in code." Lower priority than the above — it's a nice-to-have polish item, not a risk to close.

---

## What not to touch

Don't rewrite the landing copy, don't add hedging language to the README,
don't try to make the corpus bigger by seeding synthetic rows — all three
would make things worse, not better. The written materials are already
calibrated correctly; the only real gap is what gets said live and one
missing dollar figure.
