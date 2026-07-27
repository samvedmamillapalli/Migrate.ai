# E2E walkthrough — real SFN + Cockroach Cloud shadow

Prerequisites: filled repo-root `.env`, `python scripts/dev.py restart`,
`cd frontend/oracle && npm run dev`, and `GET /health` → `sfn_ready: true`.

1. Open http://localhost:3000/dashboard — set **owner identity** in the sidebar.
2. **New Migration** → paste SQL → Run Migration Analysis.
3. On Current Migration → attach read-only DB URL (or secret ARN) → **Discover schema**.
4. **Run prediction** — wait for assessment (policy + Bedrock + memories).
5. **Proceed to shadow test** (override rationale if policy blocked).
6. **Start shadow test** — watch provision → seed → migrate → teardown.
7. Confirm grade + memory on the run; open Agent Memory and Past Migrations
   (scoped to your owner identity).
8. Run a second similar migration and confirm retrieved memories appear in prediction.

If Start is disabled: fix `MIGRATION_WORKFLOW_ARN` / `RUN_ARTIFACTS_BUCKET`,
restart API, re-check `/health`. Local mock verify is not in the product UI.

Pending embeddings: `POST /runs/memories/repair-embeddings` (see OpenAPI docs).
