# Improvement Roadmap — Phase by Phase

This is a plain-English version of `docs/JUDGING_READINESS.md`, organized as
phases you can work through in order before the August 18 deadline. Each
phase builds on the one before it. Nothing in this doc has been built yet —
it's a plan to follow, not a record of what's done.

---

## Phase 1 — Say it right (no coding, do this first)

This phase is entirely about words, not code. It's the highest-value phase
because it's free and it removes the single biggest risk in the whole
project: judges thinking you're claiming something you're not actually doing.

1. **Get the CockroachDB job-watching story straight.** The app watches what
   CockroachDB is doing during a migration using plain SQL (`SHOW JOBS`), not
   by actually calling CockroachDB's "Managed MCP" service. That's fine and
   still counts as a real CockroachDB tool — but only if you describe it
   correctly. Say "we watch the same job information that CockroachDB's MCP
   tool exposes, using SQL" — never say "we call Managed MCP." Your written
   docs already say this correctly. The only risk is someone saying it wrong
   out loud during the pitch. Write the exact sentence down and have whoever
   presents read it, don't paraphrase from memory.

2. **Don't mention the `ccloud` command-line tool as a main feature.** The
   app provisions shadow clusters using CockroachDB's web API, not the
   command-line tool. That's the right choice (the command-line tool can't
   run inside AWS Lambda), but don't bring up the command-line tool unless
   you're going to show it running.

3. **Find the real dollar cost of one shadow-cluster run.** Right now nobody
   knows exactly how much one test run costs in real money. Look at your
   Cockroach Cloud bill and get an actual number, even a rough one like
   "about 2 cents per run." Judges will ask about cost and "I don't know" is
   a worse answer than a real number, even a small one.

4. **Make sure sign-in is actually turned on for the version judges will
   see.** The app now has real login (through Clerk). That only helps your
   score if it's switched on for the copy of the app judges actually open,
   not just on your own laptop. Check this explicitly.

5. **Practice the demo in this exact order:** first, predict a migration
   when the system has little or no memory to draw on. Second, run it for
   real on a disposable CockroachDB cluster. Third, grade the result and
   store it as a memory. Fourth, predict a *different* migration that's
   similar under the hood and show the system pulling up the first one as a
   relevant memory. Fifth, show one thing going wrong on purpose (a blocked
   migration, or stopping a run early) to prove the safety nets work. This
   order proves every judging category in one smooth pass.

---

## Phase 2 — Small, concrete fixes

These are small changes to the actual app that make things you're already
doing well more visible and more honest-looking.

1. **Say out loud, inside the app, that your memory collection is small on
   purpose.** You have 11 real, sourced examples of past migration problems
   plus your own graded test runs — not thousands. That's fine for a demo,
   but if a judge notices it's small they might assume it's incomplete
   rather than intentional. Add a short note near the memory list saying
   something like "small, hand-picked set of real documented incidents,
   kept deliberately small and cleanly separated from real graded runs."

2. **Show off your safety alarms.** The app already sets up real monitoring
   alerts in AWS (for example, catching a shadow cluster that didn't get
   cleaned up properly). Right now this is invisible — it only lives in the
   AWS console, not in your app. Add a small settings or health page that
   lists what's being watched, so judges can see you thought about failure
   cases instead of just hoping nothing breaks.

3. **Test the "remembers a similar migration" moment ahead of time, don't
   assume it works.** This is the single most impressive moment in the whole
   demo — the system recognizing that two completely different-looking SQL
   statements have the same underlying risk. It depends on how the system's
   memory descriptions are written internally (they need to focus on *what
   happened and why*, not just repeat the raw SQL). Actually run this exact
   demo moment yourself before the real presentation to make sure it works,
   rather than trusting it will.

4. **Mention CockroachDB's multi-user safety in the pitch.** The app uses a
   CockroachDB feature (serializable transactions) to safely handle multiple
   people using shadow clusters at the same time without stepping on each
   other. This is already built and working — it just needs one sentence in
   the pitch so judges know it's there.

---

## Phase 3 — Bigger upgrades, if there's time left

These take more real engineering work. Only start these after Phases 1 and 2
are done, since those are cheaper and higher-value.

1. **Make the MCP claim fully true instead of "close enough."** Right now
   the app reads job status with plain SQL. The bigger upgrade is to
   actually call CockroachDB's real Managed MCP web service for that same
   information. The connection details for this are already sitting in the
   app's settings, unused. This would remove the need for any careful
   wording at all — it would just be true. This is the single most
   impressive upgrade on this list, but also the most technical one.

2. **Build a simple screen showing all shadow clusters across every run.**
   Right now you can only see the shadow cluster for one migration at a
   time. A page showing "here's every disposable cluster that's ever been
   created, and here's proof they all got cleaned up" would make the app
   feel more like a real operated product and less like a one-off demo.
   Nice to have, not required.

---

## Phase 4 — Leave these alone

A short list of things that would feel like improvements but would actually
hurt you:

- **Don't rewrite the homepage text.** It already leads with the right
  story (predict, verify, grade, remember) instead of generic "AI assistant"
  language. Changing it risks making it worse.
- **Don't add extra "just in case" disclaimers to the README.** The
  documentation is already careful and accurate about what the app does and
  doesn't do. Adding more hedging will just make it read as less confident.
- **Don't pad out the memory collection with made-up examples** to make it
  look bigger. A small, real, honestly-labeled collection is a strength.
  A bigger collection full of fake entries would be a real weakness if
  anyone looked closely.

---

## Quick summary

| Phase | What it is | Cost |
|---|---|---|
| 1 | Fix how things are described out loud | Free — just words |
| 2 | Small visible app changes | A few hours each |
| 3 | Real new engineering | Bigger time investment |
| 4 | Things to actively avoid doing | N/A |

Do Phase 1 no matter what. Do as much of Phase 2 as time allows. Only touch
Phase 3 if Phases 1 and 2 are fully done with time to spare.
