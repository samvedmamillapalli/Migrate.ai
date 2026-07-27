# Chaos dress rehearsal — backup lines

Run once before freeze: `python backend/scripts/judge_chaos_checks.py` and/or `judge_path3_failures.py` if available.

## Bedrock slow / timeout

> “Prediction is calling Bedrock live — while it thinks, here’s the memory corpus that will ground the next estimate.”
> Open Agent Memory. Resume when predict returns.

## SFN / shadow queue or slow provision

> “Provisioning a real BASIC Cockroach Cloud cluster usually takes about a minute. We’re watching the same steps the workflow runs — provision, load schema, migrate, tear down.”
> Keep floating watch visible. Have a completed run detail tab ready as fallback.

## Discover rejects credentials (not read-only)

> “We refuse write-capable credentials on purpose — that’s how we prove we never touch production.”
> Switch to judge RO URL from `prepare_judge_demo_db.py`.

## Weak retrieval / no similar runs

> “First graded run seeds memory. The open-source corpus still grounds the model; after this shadow, the next similar SQL will retrieve this run.”
> Or switch to SQL B after A completes; or fresh owner + A→B.

## Shadow start blocked (Needs setup)

> “Shadow needs the Step Functions workflow ARN and artifacts bucket — Overview health shows Needs setup until those are set.”
> Do not paste long ARN walls on the primary screen. Fix `.env`, restart API, re-check `/health`.

## Abort mid-run

> “Abort stops Step Functions and tears the cluster down. A sweeper is the backstop if anything is left after 30 minutes.”

## Network blip while polling

Refresh Current / Shadow page; sync workflow resumes. Do not restart a second shadow (`shadow_max_concurrent`).

## Cost one-liner

> “We spin up a real disposable cluster for about a minute on the BASIC plan, then tear it down.”
