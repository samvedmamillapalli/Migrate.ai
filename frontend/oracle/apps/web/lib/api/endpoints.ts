import { api } from "./client"
import type { components } from "./schema"

export type MigrationRun = components["schemas"]["MigrationRunResponse"]
export type MigrationRunSummary =
  components["schemas"]["MigrationRunSummaryResponse"]
export type MigrationRunList = components["schemas"]["MigrationRunListResponse"]
export type ApprovalDecision =
  components["schemas"]["ApprovalDecision"]
export type Grade = components["schemas"]["GradeResponse"]
export type Memory = components["schemas"]["MemoryResponse"]
export type MemoryListItem = components["schemas"]["MemoryListItem"]
export type MemoryList = components["schemas"]["MemoryListResponse"]
export type MemorySearchRequest = components["schemas"]["MemorySearchRequest"]
export type MemorySearchResponse = components["schemas"]["MemorySearchResponse"]
export type MemorySearchHit = components["schemas"]["MemorySearchHit"]
export type ShadowCluster = components["schemas"]["ShadowClusterResponse"]
export type ExecutionResult = components["schemas"]["ExecutionResultResponse"]
export type ApprovalCreateRequest =
  components["schemas"]["ApprovalCreateRequest"]
export type ApprovalResponse = components["schemas"]["ApprovalResponse"]
export type DiscoverSchemaRequest =
  components["schemas"]["DiscoverSchemaRequest"]

/** Server-side `status` filter values accepted by GET /runs. */
export type RunStatusFilter =
  | "pending"
  | "predicting"
  | "awaiting_approval"
  | "running"
  | "completed"
  | "failed"

/** One real lifecycle event from GET /runs/activity. Never synthesized. */
export type ActivityEvent = {
  migration_run_id: string
  /** ISO timestamp of the persisted event. */
  at: string | null
  /** Queued | Predicted | Learned | Approved | Accepted Plan | Cancelled |
   *  Shadow | Completed | Failed | Graded | Remembered */
  kind: string
  /** emerald | blue | violet | amber | red — semantic palette key. */
  tone: string
  text: string
  sql_snippet: string
}

export type ActivityFeed = {
  items: ActivityEvent[]
  total: number
}

export type HealthResponse = {
  status: string
  database: string
  cockroachdb_version?: string | null
  aws?: Record<string, unknown>
  integrations?: {
    sfn_ready?: boolean
    bedrock_configured?: boolean
    migration_workflow_arn_set?: boolean
    run_artifacts_bucket_set?: boolean
    shadow_provider?: string
    local_verify_available?: boolean
    environment?: string
    bedrock_prediction_model_id?: string | null
    bedrock_embedding_model_id?: string | null
  }
}

export type PipelineProgress = {
  run_id: string
  stage: string
  message: string
  percent: number
  detail?: string | null
  updated_at?: number
  history?: Array<{
    stage: string
    message: string
    percent: number
    at?: number
  }>
}

export type ModelTracesResponse = {
  migration_run_id: string
  traces: Record<string, unknown> | null
}

export type AccuracyMetrics = Record<string, unknown>

export type CorpusHealth = {
  healthy?: boolean
  empty?: boolean
  total_memories?: number
  problems?: string[]
  corpus_identity?: string
  corpus_ready_count?: number
  missing_embeddings?: number
  missing_scale_tier?: number
  missing_migration_type?: number
  by_embedding_status?: Record<string, number>
  by_owner_identity?: Array<{ owner_identity: string; count: number }>
  [key: string]: unknown
}

export function getHealth() {
  return api<HealthResponse>("/health")
}

export type RunSortKey =
  | "created_at"
  | "updated_at"
  | "status"
  | "compatibility_risk"

export type ApprovalDecisionFilter =
  | "proceed"
  | "accept_recommended"
  | "cancel"
  /** Runs with no decision recorded yet. */
  | "none"

export function listRuns(params?: {
  limit?: number
  offset?: number
  owner_identity?: string
  run_kind?: string
  /** Server-side run status filter, e.g. "awaiting_approval" (decision queue). */
  status?: RunStatusFilter
  /** Comma-separated run_kind values to exclude, e.g. "chaos,debug". */
  exclude_kinds?: string
  /** Case-insensitive substring match on the migration SQL (server-side). */
  q?: string
  risk?: "low" | "medium" | "high"
  decision?: ApprovalDecisionFilter
  approver?: string
  order_by?: RunSortKey
  order_dir?: "asc" | "desc"
}) {
  const q = new URLSearchParams()
  if (params?.limit != null) q.set("limit", String(params.limit))
  if (params?.offset != null) q.set("offset", String(params.offset))
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  if (params?.run_kind) q.set("run_kind", params.run_kind)
  if (params?.status) q.set("status", params.status)
  if (params?.exclude_kinds) q.set("exclude_kinds", params.exclude_kinds)
  if (params?.q) q.set("q", params.q)
  if (params?.risk) q.set("risk", params.risk)
  if (params?.decision) q.set("decision", params.decision)
  if (params?.approver) q.set("approver", params.approver)
  if (params?.order_by) q.set("order_by", params.order_by)
  if (params?.order_dir) q.set("order_dir", params.order_dir)
  const qs = q.toString()
  return api<MigrationRunList>(`/runs${qs ? `?${qs}` : ""}`)
}

/** Distinct approver identities, for the history filter dropdown. */
export function listApprovers(params?: { owner_identity?: string }) {
  const q = new URLSearchParams()
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  const qs = q.toString()
  return api<{ approvers: string[] }>(`/runs/approvers${qs ? `?${qs}` : ""}`)
}

export type RunVolume = {
  days: Array<{ day: string; ok: number; bad: number; total: number }>
  window_days: number
}

/** Daily run volume across the whole history (not just the loaded page). */
export function getRunVolume(params?: {
  days?: number
  owner_identity?: string
}) {
  const q = new URLSearchParams()
  if (params?.days != null) q.set("days", String(params.days))
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  const qs = q.toString()
  return api<RunVolume>(`/runs/volume${qs ? `?${qs}` : ""}`)
}

/**
 * Discard a run abandoned during setup. Server-side this only succeeds for a
 * `pending` run with no approval, grade, execution result, shadow cluster or
 * memory — anything further along is audit record and returns 409.
 */
export function discardRun(runId: string) {
  return api<void>(`/runs/${runId}`, { method: "DELETE" })
}

/** Merged, reverse-chronological stream of real persisted lifecycle events. */
export function getActivityFeed(params?: {
  limit?: number
  owner_identity?: string
}) {
  const q = new URLSearchParams()
  if (params?.limit != null) q.set("limit", String(params.limit))
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  const qs = q.toString()
  return api<ActivityFeed>(`/runs/activity${qs ? `?${qs}` : ""}`)
}

export function getRun(runId: string) {
  return api<MigrationRun>(`/runs/${runId}`)
}

export function createRun(body: {
  migration_sql: string
  owner_identity: string
  revises_run_id?: string | null
}) {
  return api<MigrationRun>("/runs", { method: "POST", body })
}

export function createFakeMigration(ownerIdentity: string) {
  const q = new URLSearchParams({ owner_identity: ownerIdentity })
  return api<MigrationRun>(`/runs/debug/fake-migration?${q}`, {
    method: "POST",
  })
}

/** Developer mode: real RO demo DB + sample SQL + discover. Easy to remove. */
export function createDemoWithDb(ownerIdentity: string) {
  const q = new URLSearchParams({ owner_identity: ownerIdentity })
  return api<MigrationRun>(`/runs/debug/demo-with-db?${q}`, {
    method: "POST",
  })
}

export function discoverSchema(runId: string, body: DiscoverSchemaRequest) {
  return api<MigrationRun>(`/runs/${runId}/discover`, {
    method: "POST",
    body,
  })
}

export function predictRun(runId: string, opts?: { signal?: AbortSignal }) {
  return api<MigrationRun>(`/runs/${runId}/predict`, {
    method: "POST",
    signal: opts?.signal,
  })
}

export function getPipelineProgress(runId: string) {
  return api<PipelineProgress>(`/runs/${runId}/pipeline-progress`)
}

export function approveRun(runId: string, body: ApprovalCreateRequest) {
  return api<MigrationRun>(`/runs/${runId}/approve`, {
    method: "POST",
    body,
  })
}

export function getApproval(runId: string) {
  return api<ApprovalResponse>(`/runs/${runId}/approval`)
}

export function startWorkflow(
  runId: string,
  body?: {
    connection_secret_arn?: string | null
    database_url?: string | null
  }
) {
  return api<MigrationRun>(`/runs/${runId}/start-workflow`, {
    method: "POST",
    body: body ?? {},
  })
}

export function syncWorkflow(runId: string) {
  return api<MigrationRun>(`/runs/${runId}/sync-workflow`, {
    method: "POST",
  })
}

export function abortWorkflow(runId: string) {
  return api<MigrationRun>(`/runs/${runId}/abort-workflow`, {
    method: "POST",
  })
}

/** Engineer-only local mock verify. Not used by the product UI (SFN required). */
export function verifyLocal(runId: string) {
  return api<MigrationRun>(`/runs/${runId}/verify-local`, {
    method: "POST",
  })
}

export function getGrade(runId: string) {
  return api<Grade>(`/runs/${runId}/grade`)
}

export function getMemory(runId: string) {
  return api<Memory>(`/runs/${runId}/memory`)
}

export function getExecutionResult(runId: string) {
  return api<ExecutionResult>(`/runs/${runId}/execution-result`)
}

export function getShadowCluster(runId: string) {
  return api<ShadowCluster>(`/runs/${runId}/shadow-cluster`)
}

/** Ends a HOLDING cluster's inspection window immediately instead of
 * waiting out the hold or the sweeper. Idempotent. */
export function teardownShadowClusterNow(runId: string) {
  return api<ShadowCluster>(`/runs/${runId}/shadow-cluster/teardown-now`, {
    method: "POST",
  })
}

export function getModelTraces(runId: string) {
  return api<ModelTracesResponse>(`/runs/${runId}/model-traces`)
}

export function getAccuracyMetrics(params?: { owner_identity?: string }) {
  const q = new URLSearchParams()
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  const qs = q.toString()
  return api<AccuracyMetrics>(`/runs/metrics/accuracy${qs ? `?${qs}` : ""}`)
}

/**
 * Reserved owner for the shared open-source corpus. The backend's owner
 * filter is `IN (your_id, CORPUS_OWNER_IDENTITY)` — your own memories plus
 * the shared corpus that informs your predictions.
 */
export const CORPUS_OWNER_IDENTITY = "__migration_oracle_corpus__"

export function listMemories(params?: {
  limit?: number
  offset?: number
  owner_identity?: string
  /** "ready" | "pending" | "failed" */
  embedding_status?: string
}) {
  const q = new URLSearchParams()
  if (params?.limit != null) q.set("limit", String(params.limit))
  if (params?.offset != null) q.set("offset", String(params.offset))
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  if (params?.embedding_status)
    q.set("embedding_status", params.embedding_status)
  const qs = q.toString()
  return api<MemoryList>(`/memories${qs ? `?${qs}` : ""}`)
}

export function getMemoriesHealth() {
  return api<CorpusHealth>("/memories/health")
}

/**
 * Semantic search over graded memories, on CockroachDB's distributed vector
 * index — `scope` picks which query shape runs server-side (see
 * MigrationMemoryRepository.semantic_search): "corpus" and "all" (when an
 * owner is known) ride the owner-scoped partial index; "all" with no owner
 * and "corpus" both still exclude your own memories unless owner is set.
 * `owner_identity` scopes "mine"/"all"; ignored by the backend once auth is
 * enforced (the token's owner wins there).
 */
export function searchMemories(
  body: MemorySearchRequest,
  params?: { owner_identity?: string }
) {
  const q = new URLSearchParams()
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  const qs = q.toString()
  return api<MemorySearchResponse>(`/memories/search${qs ? `?${qs}` : ""}`, {
    method: "POST",
    body,
  })
}

export function isSfnReady(health: HealthResponse | null | undefined): boolean {
  const i = health?.integrations
  if (!i) return false
  if (typeof i.sfn_ready === "boolean") return i.sfn_ready
  return Boolean(i.migration_workflow_arn_set && i.run_artifacts_bucket_set)
}

/** Actionable setup message when real shadow (SFN + Cockroach Cloud) is not ready. */
export function sfnNotReadyMessage(
  health: HealthResponse | null | undefined
): string {
  const i = health?.integrations
  const missing: string[] = []
  if (!i?.migration_workflow_arn_set) missing.push("MIGRATION_WORKFLOW_ARN")
  if (!i?.run_artifacts_bucket_set) missing.push("RUN_ARTIFACTS_BUCKET")
  const need =
    missing.length > 0
      ? missing.join(" and ")
      : "MIGRATION_WORKFLOW_ARN and RUN_ARTIFACTS_BUCKET"
  return (
    `Real shadow verify requires a deployed AWS Step Functions workflow. ` +
    `Missing or unset: ${need}. ` +
    `Set them in the repo-root .env (see docs/DEMO_OPS.md / infra/sam), restart the API, ` +
    `then confirm GET /health → integrations.sfn_ready is true. ` +
    `Local mock verify is not available in the product UI.`
  )
}

export type AuthStatus = {
  auth_enabled: boolean
  register_enabled?: boolean
}

export type AuthTokenResponse = {
  access_token: string
  token_type: string
  owner_identity: string
  expires_in_seconds: number
}

export function getAuthStatus() {
  return api<AuthStatus>("/auth/status")
}

export function registerUser(body: {
  owner_identity: string
  password: string
  display_name?: string | null
}) {
  return api<AuthTokenResponse>("/auth/register", { method: "POST", body })
}

export function loginUser(body: { owner_identity: string; password: string }) {
  return api<AuthTokenResponse>("/auth/login", { method: "POST", body })
}

export function hasRealSfnArn(run: MigrationRun | null | undefined): boolean {
  const arn = run?.sfn_execution_arn || ""
  return Boolean(arn) && !String(arn).startsWith("local://")
}
