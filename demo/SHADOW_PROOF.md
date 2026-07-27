# Shadow + closed-loop proof (2026-07-25)

## Successful SFN shadows (recent / this session)

| Run | Status | Notes |
| --- | --- | --- |
| `99560180…` | completed / succeeded | PATH1 live — grade 1.0, memory ready, cluster torn down |
| `06c4b008…` | completed / succeeded | Prior demo_flag shadow |
| `92810c13…` | completed / succeeded | Prior users.status shadow |

Report: [`docs/judge_walkthrough_artifacts/path1_report.json`](../docs/judge_walkthrough_artifacts/path1_report.json)

Timings (PATH1): discover 6s · predict 68s · shadow ~574s wall · cluster visible ~512s.

## Closed loop (VECTOR retrieval)

Second predict run `105c5f0a…` retrieved first memory from `99560180…`:

```text
CLOSED LOOP HIT — first run memory retrieved on second predict
```

`closed_loop.retrieved_run_ids[0] == 99560180-e4e5-4e1d-9730-db47535ff64f`

## Abort / teardown

Fresh abort (this session):

```text
run=fc409451-08d7-4fcb-ae39-04abaf49fb2d
aborted status=failed workflow=aborted
ABORT_OK
```

Script: `backend/scripts/judge_abort_shadow.py`

Prior aborted runs also exist (`4f2239ad`, `12058662`, `46d4d386`).

## Job watch UI

ExecuteMigration now merges `job_watch` into `shadow_clusters.stage_timings`. **Redeploy SAM** so production Lambdas emit it (`demo/DEPLOY_CHECKLIST.md`). Run detail shows **Jobs observed**.
