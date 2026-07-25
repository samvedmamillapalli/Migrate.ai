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
export type ShadowCluster = components["schemas"]["ShadowClusterResponse"]
export type ExecutionResult = components["schemas"]["ExecutionResultResponse"]
export type ApprovalCreateRequest =
  components["schemas"]["ApprovalCreateRequest"]
export type ApprovalResponse = components["schemas"]["ApprovalResponse"]
export type DiscoverSchemaRequest =
  components["schemas"]["DiscoverSchemaRequest"]

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

export function listRuns(params?: {
  limit?: number
  offset?: number
  owner_identity?: string
}) {
  const q = new URLSearchParams()
  if (params?.limit != null) q.set("limit", String(params.limit))
  if (params?.offset != null) q.set("offset", String(params.offset))
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  const qs = q.toString()
  return api<MigrationRunList>(`/runs${qs ? `?${qs}` : ""}`)
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

export function predictRun(runId: string) {
  return api<MigrationRun>(`/runs/${runId}/predict`, { method: "POST" })
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

export function getModelTraces(runId: string) {
  return api<ModelTracesResponse>(`/runs/${runId}/model-traces`)
}

export function getAccuracyMetrics() {
  return api<AccuracyMetrics>("/runs/metrics/accuracy")
}

export function listMemories(params?: {
  limit?: number
  offset?: number
  owner_identity?: string
}) {
  const q = new URLSearchParams()
  if (params?.limit != null) q.set("limit", String(params.limit))
  if (params?.offset != null) q.set("offset", String(params.offset))
  if (params?.owner_identity) q.set("owner_identity", params.owner_identity)
  const qs = q.toString()
  return api<MemoryList>(`/memories${qs ? `?${qs}` : ""}`)
}

export function getMemoriesHealth() {
  return api<CorpusHealth>("/memories/health")
}

export function isSfnReady(health: HealthResponse | null | undefined): boolean {
  const i = health?.integrations
  if (!i) return false
  if (typeof i.sfn_ready === "boolean") return i.sfn_ready
  return Boolean(i.migration_workflow_arn_set && i.run_artifacts_bucket_set)
}

export function hasRealSfnArn(run: MigrationRun | null | undefined): boolean {
  const arn = run?.sfn_execution_arn || ""
  return Boolean(arn) && !String(arn).startsWith("local://")
}
