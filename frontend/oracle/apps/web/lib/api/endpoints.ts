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
  workspace_id?: string
  run_kind?: string
  /** Server-side run status filter, e.g. "awaiting_approval" (decision queue). */
  status?: RunStatusFilter
  /** Comma-separated statuses, e.g. "pending,predicting,awaiting_approval,running". */
  status_in?: string
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
  if (params?.workspace_id) q.set("workspace_id", params.workspace_id)
  if (params?.run_kind) q.set("run_kind", params.run_kind)
  if (params?.status) q.set("status", params.status)
  if (params?.status_in) q.set("status_in", params.status_in)
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
export function listApprovers(params?: {
  owner_identity?: string
  workspace_id?: string
}) {
  const q = new URLSearchParams()
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  if (params?.workspace_id) q.set("workspace_id", params.workspace_id)
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
  workspace_id?: string
}) {
  const q = new URLSearchParams()
  if (params?.days != null) q.set("days", String(params.days))
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  if (params?.workspace_id) q.set("workspace_id", params.workspace_id)
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
  workspace_id?: string
}) {
  const q = new URLSearchParams()
  if (params?.limit != null) q.set("limit", String(params.limit))
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  if (params?.workspace_id) q.set("workspace_id", params.workspace_id)
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
  workspace_id?: string | null
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
export function createDemoWithDb(ownerIdentity: string, workspaceId?: string | null) {
  const q = new URLSearchParams({ owner_identity: ownerIdentity })
  if (workspaceId) q.set("workspace_id", workspaceId)
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

/** Run the grading pipeline for a finished shadow run. */
export function runGrade(runId: string) {
  return api<MigrationRun>(`/runs/${runId}/grade`, { method: "POST" })
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

export function getAccuracyMetrics(params?: {
  owner_identity?: string
  workspace_id?: string
}) {
  const q = new URLSearchParams()
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  if (params?.workspace_id) q.set("workspace_id", params.workspace_id)
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

export type SlackInstallAuthorizeResponse =
  components["schemas"]["SlackInstallAuthorizeResponse"]
export type SlackStatusResponse = components["schemas"]["SlackStatusResponse"]
export type SlackDisconnectResponse =
  components["schemas"]["SlackDisconnectResponse"]

/**
 * Whether Slack is connected for the current user, and (when connected)
 * which workspace. Routes are under `/api/slack/...`, not `/slack/...` —
 * see `backend/app/api/routes/slack.py`'s router prefix.
 */
export function getSlackStatus() {
  return api<SlackStatusResponse>("/api/slack/status")
}

/**
 * Fetch the signed, TTL-bounded Slack OAuth authorize URL for the current
 * user. The caller navigates the browser to `authorize_url` — Slack's own
 * consent screen, not something this app renders.
 */
export function getSlackInstallUrl() {
  return api<SlackInstallAuthorizeResponse>("/api/slack/install")
}

export function disconnectSlack() {
  return api<SlackDisconnectResponse>("/api/slack/disconnect", {
    method: "POST",
  })
}

/**
 * GitHub account connection — "who is this GitHub identity" for
 * collaboration (e.g. matching invited teammates to a verified account
 * instead of a typed handle). Distinct from the GitHub App used for
 * PR/webhook automation (docs/FUTURE_GITHUB_INTEGRATION_PLAN.md) — that's a
 * separate credential and a separate feature. Real backend, same
 * install-url-redirect / status-poll / disconnect shape as the Slack panel.
 */
export type GithubStatusResponse = components["schemas"]["GithubIdentityStatusResponse"]
export type GithubInstallAuthorizeResponse =
  components["schemas"]["GithubIdentityInstallAuthorizeResponse"]
export type GithubDisconnectResponse =
  components["schemas"]["GithubIdentityDisconnectResponse"]

export function getGithubStatus() {
  return api<GithubStatusResponse>("/api/github/status")
}

export function getGithubInstallUrl() {
  return api<GithubInstallAuthorizeResponse>("/api/github/install")
}

export function disconnectGithub() {
  return api<GithubDisconnectResponse>("/api/github/disconnect", {
    method: "POST",
  })
}

export type MemorySharingStatusResponse =
  components["schemas"]["MemorySharingStatusResponse"]
export type MemorySharingPreviewResponse =
  components["schemas"]["MemorySharingPreviewResponse"]
export type MemorySharingSetRequest =
  components["schemas"]["MemorySharingSetRequest"]

/**
 * Current cross-customer memory sharing opt-in state for this account —
 * see docs/cross_customer.md. Default is off; a missing preference row
 * means "not enabled", never implicit consent.
 *
 * `ownerIdentity` is ignored server-side once auth is enforced (the token
 * owner always wins) — pass `getOwnerIdentity()` so local/anon dev (no
 * Clerk configured) still resolves against the right identity, same
 * pattern as `searchMemories`/`browseMemories`.
 */
export function getMemorySharingStatus(ownerIdentity?: string) {
  const q = new URLSearchParams()
  if (ownerIdentity) q.set("owner_identity", ownerIdentity)
  const qs = q.toString()
  return api<MemorySharingStatusResponse>(
    `/api/memory-sharing/status${qs ? `?${qs}` : ""}`
  )
}

/**
 * A live, real example of what would be shared, built from this account's
 * own most recently graded run — never written to the database. Meant to
 * be shown before the user confirms opting in (docs/cross_customer.md §6).
 */
export function getMemorySharingPreview(ownerIdentity?: string) {
  const q = new URLSearchParams()
  if (ownerIdentity) q.set("owner_identity", ownerIdentity)
  const qs = q.toString()
  return api<MemorySharingPreviewResponse>(
    `/api/memory-sharing/preview${qs ? `?${qs}` : ""}`
  )
}

export function setMemorySharing(enabled: boolean, ownerIdentity?: string) {
  return api<MemorySharingStatusResponse>("/api/memory-sharing/set", {
    method: "POST",
    body: {
      enabled,
      owner_identity: ownerIdentity || null,
    } satisfies MemorySharingSetRequest,
  })
}

/**
 * Workspaces — docs/FUTURE_WORKSPACES_PLAN.md. A workspace scopes runs to
 * one target database (a name + a stored connection). Owner-scoped
 * everywhere, same tenancy pattern as the run endpoints above.
 */
export type Workspace = components["schemas"]["WorkspaceResponse"]
export type WorkspaceList = components["schemas"]["WorkspaceListResponse"]
export type WorkspaceCreateRequest = components["schemas"]["WorkspaceCreateRequest"]
export type WorkspaceUpdateRequest = components["schemas"]["WorkspaceUpdateRequest"]

export function listWorkspaces(ownerIdentity?: string) {
  const q = new URLSearchParams()
  if (ownerIdentity) q.set("owner_identity", ownerIdentity)
  const qs = q.toString()
  return api<WorkspaceList>(`/workspaces${qs ? `?${qs}` : ""}`)
}

export function getWorkspace(workspaceId: string, ownerIdentity?: string) {
  const q = new URLSearchParams()
  if (ownerIdentity) q.set("owner_identity", ownerIdentity)
  const qs = q.toString()
  return api<Workspace>(`/workspaces/${workspaceId}${qs ? `?${qs}` : ""}`)
}

export function createWorkspace(body: {
  name: string
  owner_identity?: string | null
  connection_secret_arn?: string | null
  database_url?: string | null
  github_repo_full_name?: string | null
  github_migration_glob?: string | null
}) {
  return api<Workspace>("/workspaces", {
    method: "POST",
    body: body satisfies WorkspaceCreateRequest,
  })
}

export function updateWorkspace(
  workspaceId: string,
  body: {
    name?: string | null
    connection_secret_arn?: string | null
    database_url?: string | null
    clear_connection?: boolean
    github_repo_full_name?: string | null
    clear_github_repo?: boolean
    github_migration_glob?: string | null
  }
) {
  return api<Workspace>(`/workspaces/${workspaceId}`, {
    method: "PATCH",
    body: {
      ...body,
      clear_connection: body.clear_connection ?? false,
      clear_github_repo: body.clear_github_repo ?? false,
    } satisfies WorkspaceUpdateRequest,
  })
}

export function deleteWorkspace(workspaceId: string) {
  return api<void>(`/workspaces/${workspaceId}`, { method: "DELETE" })
}

/**
 * GitHub **PR integration** status — docs/GITHUB_APP_SETUP.md. Distinct from
 * the GitHub *identity* connection above: this one is live and backed by a
 * real route (`GET /webhooks/github/status`), and drives the repo-linking
 * form in the workspace settings panel. It reports whether this server has
 * a GitHub App configured and where the user should install it.
 */
export type GithubIntegrationStatus =
  components["schemas"]["GithubIntegrationStatus"]

export function getGithubIntegrationStatus() {
  return api<GithubIntegrationStatus>("/webhooks/github/status")
}

/**
 * Workspace invites + members — real backend, docs/backendfix.md 2026-08-07.
 * Roster-only: membership grants visibility of the workspace, not access to
 * its migration runs (unchanged, still strictly owner_identity-scoped).
 */
export type WorkspaceInviteMethod = "email" | "github" | "link"

export type WorkspaceInvite = components["schemas"]["WorkspaceInviteResponse"]
export type WorkspaceInviteList =
  components["schemas"]["WorkspaceInviteListResponse"]
export type WorkspaceMember = components["schemas"]["WorkspaceMemberResponse"]
export type WorkspaceMemberList =
  components["schemas"]["WorkspaceMemberListResponse"]
/** Public, token-keyed invite preview — the token is the credential. */
export type InvitePreview = components["schemas"]["InvitePreviewResponse"]
export type InviteAcceptResponse =
  components["schemas"]["InviteAcceptResponse"]

export function createWorkspaceInvite(
  workspaceId: string,
  body: {
    method: WorkspaceInviteMethod
    email?: string | null
    github_username?: string | null
  }
) {
  return api<WorkspaceInvite>(`/workspaces/${workspaceId}/invites`, {
    method: "POST",
    body: body satisfies components["schemas"]["WorkspaceInviteCreateRequest"],
  })
}

export function listWorkspaceInvites(workspaceId: string) {
  return api<WorkspaceInviteList>(`/workspaces/${workspaceId}/invites`)
}

export function revokeWorkspaceInvite(
  workspaceId: string,
  inviteId: string
) {
  return api<WorkspaceInvite>(
    `/workspaces/${workspaceId}/invites/${inviteId}`,
    { method: "DELETE" }
  )
}

export function listWorkspaceMembers(workspaceId: string) {
  return api<WorkspaceMemberList>(`/workspaces/${workspaceId}/members`)
}

export function removeWorkspaceMember(workspaceId: string, memberId: string) {
  return api<void>(`/workspaces/${workspaceId}/members/${memberId}`, {
    method: "DELETE",
  })
}

/**
 * Public invite preview — no auth required, the token in the URL is the
 * credential. Skips the auth bridge entirely so the acceptance page renders
 * for signed-out visitors without waiting on token resolution (which can
 * stall in throttled tabs if the bridge hasn't initialized).
 */
export function getInvitePreview(token: string) {
  return api<InvitePreview>(`/invites/${token}`, { skipAuth: true })
}

/** Accept a pending invite and join the workspace. Requires auth. */
export function acceptInvite(token: string) {
  return api<InviteAcceptResponse>(`/invites/${token}/accept`, {
    method: "POST",
  })
}
