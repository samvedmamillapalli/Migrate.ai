/**
 * Single mapping layer: backend shapes → UI view models.
 * Backend is source of truth. Do not invent statuses or fields here.
 */

import type {
  ExecutionResult,
  Grade,
  Memory,
  MigrationRun,
  MigrationRunSummary,
  ShadowCluster,
} from "./endpoints"

export type RunStatus =
  | "pending"
  | "predicting"
  | "awaiting_approval"
  | "running"
  | "completed"
  | "failed"

export type WorkflowStatus =
  | "not_started"
  | "running"
  | "succeeded"
  | "failed"
  | "timed_out"
  | "aborted"

export type ProcessStageState = "complete" | "current" | "pending" | "failed"

export type LifecycleStageId =
  | "created"
  | "discovered"
  | "predicted"
  | "approved"
  | "provisioned"
  | "seeded"
  | "executed"
  | "verified"
  | "torn_down"
  | "graded"
  | "remembered"

export type LifecycleStage = {
  id: LifecycleStageId
  label: string
  state: ProcessStageState
  at?: string | null
  durationLabel?: string | null
  outcome?: string | null
  error?: string | null
}

export type RiskFlagView = {
  ruleId: string
  severity: string
  explanation: string
}

export type RetrievedMemoryView = {
  rank: number
  memoryId: string | null
  migrationRunId: string | null
  migrationSummary: string
  similarityScore: number | null
  scaleTier: string | null
  notAGradedRun: boolean
  sourceUrl: string | null
  uiLabel: string | null
  lessonsLearned: string | null
  surpriseNotes: string | null
  actualDurationSeconds: number | null
  actualStorageMb: number | null
}

export type RetrievalView = {
  attempted: boolean
  mode: string | null
  emptyVsNeverAttempted: "never_attempted" | "empty" | "hits" | "unknown"
  weakRetrieval: boolean | null
  weakSimilarityThreshold: number | null
  retrievedCount: number
  memories: RetrievedMemoryView[]
  attributionSignals: Array<{ key: string; value: string }>
  vectorIndexNote: string
}

export type ConfidenceView = {
  raw: number | null
  adjusted: number | null
  percentLabel: string
  adjustments: Array<{ reasonCode: string; reason: string; amount: number }>
  wasReduced: boolean
}

export type PredictionView = {
  estimatedDurationSeconds: number | null
  estimatedStorageMb: number | null
  rollbackRisk: string | null
  riskExplanation: string | null
  keyAssumptions: string[]
  uncertaintyNotes: string[]
  scaleTier: string | null
  framingNote: string | null
}

export type RecommendationView = {
  strategy: string | null
  rationale: string | null
  rolloutSteps: string[]
  monitoringChecklist: string[]
  rollbackGuidance: string | null
  saferAlternativePlan: string | null
  suggestedDeploymentWindow: string | null
}

export type AssessmentView = {
  policyDecision: string | null
  compatibilityRisk: string | null
  requiresManualReview: boolean | null
  requiresExpandContract: boolean | null
  riskFlags: RiskFlagView[]
  prediction: PredictionView | null
  confidence: ConfidenceView | null
  recommendation: RecommendationView | null
  retrieval: RetrievalView
  parsedStatementTypes: string[]
}

export type SchemaTableView = {
  name: string
  estimatedRowCount: number | null
  approximateSize: string | null
  columns: Array<{ name: string; type: string }>
  indexes: string[]
}

export type SchemaView = {
  engine: string | null
  version: string | null
  status: string | null
  discoveredAt: string | null
  durationMs: number | null
  tables: SchemaTableView[]
  debugKind: string | null
  debugNote: string | null
  isSynthetic: boolean
}

export type ComparisonRow = {
  label: string
  predicted: string
  actual: string
  delta?: string
  withinBand?: boolean | null
  /** Human note — e.g. conservative estimate, not a failure. */
  bandNote?: string | null
}

export type RunExtras = {
  grade: Grade | null
  memory: Memory | null
  shadow: ShadowCluster | null
  execution: ExecutionResult | null
}

/** Human labels — never invent backend enum values. */
export function statusLabel(status: string | null | undefined): string {
  switch (status) {
    case "pending":
      return "Pending"
    case "predicting":
      return "Predicting"
    case "awaiting_approval":
      return "Awaiting approval"
    case "running":
      return "Running shadow"
    case "completed":
      return "Completed"
    case "failed":
      return "Failed"
    default:
      return status || "Unknown"
  }
}

export function workflowLabel(status: string | null | undefined): string {
  switch (status) {
    case "not_started":
      return "Not started"
    case "running":
      return "Workflow running"
    case "succeeded":
      return "Workflow succeeded"
    case "failed":
      return "Workflow failed"
    case "timed_out":
      return "Workflow timed out"
    case "aborted":
      return "Workflow aborted"
    default:
      return status || "—"
  }
}

export function policyLabel(decision: string | null | undefined): string {
  switch (decision) {
    case "allow":
      return "Allow"
    case "allow_with_warning":
      return "Allow with warning"
    case "block":
      return "Block (overridable)"
    default:
      return decision || "—"
  }
}

export function riskTone(
  level: string | null | undefined
): "low" | "medium" | "high" | "unknown" {
  const v = (level || "").toLowerCase()
  if (v === "low") return "low"
  if (v === "medium") return "medium"
  if (v === "high") return "high"
  return "unknown"
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(Number(seconds))) return "—"
  const s = Number(seconds)
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`
  const m = Math.floor(s / 60)
  const rem = s - m * 60
  return `${m}m ${rem.toFixed(0)}s`
}

export function formatStorage(mb: number | null | undefined): string {
  if (mb == null || Number.isNaN(Number(mb))) return "—"
  const n = Number(mb)
  if (Math.abs(n) >= 1024) return `${(n / 1024).toFixed(2)} GB`
  return `${n.toFixed(n < 10 ? 1 : 0)} MB`
}

export function formatPercent(score: number | null | undefined): string {
  if (score == null || Number.isNaN(Number(score))) return "—"
  return `${Math.round(Number(score) * 100)}%`
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return "—"
  const delta = Date.now() - t
  const sec = Math.round(delta / 1000)
  if (sec < 60) return `${sec}s ago`
  const min = Math.round(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.round(min / 60)
  if (hr < 48) return `${hr}h ago`
  return new Date(t).toLocaleString()
}

export function sqlFilename(sql: string, runId: string): string {
  const first = (sql || "")
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l && !l.startsWith("--"))
  if (first && first.length <= 48) {
    return first.replace(/[^a-zA-Z0-9_]+/g, "_").slice(0, 40) + ".sql"
  }
  return `migration_${runId.slice(0, 8)}.sql`
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return null
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((v) => String(v)).filter(Boolean)
}

function mapRiskFlags(raw: unknown): RiskFlagView[] {
  if (!Array.isArray(raw)) return []
  return raw.map((item) => {
    const r = asRecord(item) || {}
    return {
      ruleId: String(r.rule_id ?? r.id ?? "flag"),
      severity: String(r.severity ?? r.severity_level ?? ""),
      explanation: String(r.explanation ?? r.message ?? ""),
    }
  })
}

function mapRetrieval(explainability: Record<string, unknown> | null): RetrievalView {
  const memory = asRecord(explainability?.memory)
  const attempted = Boolean(memory?.retrieval_attempted)
  const emptyVs = String(memory?.empty_vs_never_attempted || "")
  let emptyVsNeverAttempted: RetrievalView["emptyVsNeverAttempted"] = "unknown"
  if (
    emptyVs === "never_attempted" ||
    emptyVs === "empty" ||
    emptyVs === "hits"
  ) {
    emptyVsNeverAttempted = emptyVs
  } else if (!attempted) {
    emptyVsNeverAttempted = "never_attempted"
  } else if (Number(memory?.retrieved_count || 0) === 0) {
    emptyVsNeverAttempted = "empty"
  } else {
    emptyVsNeverAttempted = "hits"
  }

  const rawMemories = Array.isArray(memory?.memories) ? memory!.memories : []
  const memories: RetrievedMemoryView[] = rawMemories.map((item, idx) => {
    const m = asRecord(item) || {}
    return {
      rank: idx + 1,
      memoryId: m.memory_id != null ? String(m.memory_id) : null,
      migrationRunId: m.migration_run_id != null ? String(m.migration_run_id) : null,
      migrationSummary: String(m.migration_summary ?? ""),
      similarityScore:
        m.similarity_score == null ? null : Number(m.similarity_score),
      scaleTier: m.scale_tier != null ? String(m.scale_tier) : null,
      notAGradedRun: Boolean(m.not_a_graded_run),
      sourceUrl: m.source_url != null ? String(m.source_url) : null,
      uiLabel: m.ui_label != null ? String(m.ui_label) : null,
      lessonsLearned:
        m.lessons_learned != null ? String(m.lessons_learned) : null,
      surpriseNotes: m.surprise_notes != null ? String(m.surprise_notes) : null,
      actualDurationSeconds:
        m.actual_duration_seconds == null
          ? null
          : Number(m.actual_duration_seconds),
      actualStorageMb:
        m.actual_storage_mb == null ? null : Number(m.actual_storage_mb),
    }
  })

  const attribution = asRecord(memory?.attribution)
  const attributionSignals: Array<{ key: string; value: string }> = []
  if (attribution) {
    if (attribution.migration_type != null) {
      attributionSignals.push({
        key: "migration_type_match",
        value: String(attribution.migration_type),
      })
    }
    if (attribution.scale_tier != null) {
      attributionSignals.push({
        key: "scale_tier",
        value: String(attribution.scale_tier),
      })
    }
    if (attribution.candidate_count != null) {
      attributionSignals.push({
        key: "candidate_count",
        value: String(attribution.candidate_count),
      })
    }
    if (attribution.owner_identity != null) {
      attributionSignals.push({
        key: "owner_scope",
        value: String(attribution.owner_identity),
      })
    }
    if (attribution.corpus_identity != null) {
      attributionSignals.push({
        key: "corpus_scope",
        value: String(attribution.corpus_identity),
      })
    }
  }

  return {
    attempted,
    mode: memory?.retrieval_mode != null ? String(memory.retrieval_mode) : null,
    emptyVsNeverAttempted,
    weakRetrieval:
      memory?.weak_retrieval === null || memory?.weak_retrieval === undefined
        ? null
        : Boolean(memory.weak_retrieval),
    weakSimilarityThreshold:
      memory?.weak_similarity_threshold == null
        ? null
        : Number(memory.weak_similarity_threshold),
    retrievedCount: Number(memory?.retrieved_count || memories.length || 0),
    memories,
    attributionSignals,
    vectorIndexNote:
      "Retrieval is served by a CockroachDB vector index using Distributed Vector Indexing.",
  }
}

function mapConfidence(
  explainability: Record<string, unknown> | null
): ConfidenceView | null {
  const conf = asRecord(explainability?.confidence)
  if (!conf) return null
  const raw =
    conf.raw_confidence_score == null ? null : Number(conf.raw_confidence_score)
  const adjusted =
    conf.confidence_score == null ? null : Number(conf.confidence_score)
  const adjustmentsRaw = Array.isArray(conf.adjustments) ? conf.adjustments : []
  const adjustments = adjustmentsRaw.map((item) => {
    const a = asRecord(item) || {}
    return {
      reasonCode: String(a.reason_code ?? ""),
      reason: String(a.reason ?? ""),
      amount: Number(a.amount ?? 0),
    }
  })
  return {
    raw,
    adjusted,
    percentLabel: formatPercent(adjusted),
    adjustments,
    wasReduced: adjustments.length > 0,
  }
}

function mapPrediction(
  explainability: Record<string, unknown> | null,
  run: MigrationRun
): PredictionView | null {
  const pred = asRecord(explainability?.prediction)
  if (!pred && !run.prediction_scale_tier) return null
  return {
    estimatedDurationSeconds:
      pred?.estimated_duration_seconds == null
        ? null
        : Number(pred.estimated_duration_seconds),
    estimatedStorageMb:
      pred?.estimated_storage_mb == null
        ? null
        : Number(pred.estimated_storage_mb),
    rollbackRisk:
      pred?.rollback_risk != null ? String(pred.rollback_risk) : null,
    riskExplanation:
      pred?.risk_explanation != null ? String(pred.risk_explanation) : null,
    keyAssumptions: asStringArray(pred?.key_assumptions),
    uncertaintyNotes: asStringArray(pred?.uncertainty_notes),
    scaleTier:
      (pred?.shadow_scale_tier != null
        ? String(pred.shadow_scale_tier)
        : null) || run.prediction_scale_tier || null,
    framingNote:
      explainability?.framing_note != null
        ? String(explainability.framing_note)
        : null,
  }
}

function mapRecommendation(
  run: MigrationRun,
  explainability: Record<string, unknown> | null
): RecommendationView | null {
  const rec =
    asRecord(run.recommendation) || asRecord(explainability?.recommendation)
  if (!rec) return null
  const stepsRaw = Array.isArray(rec.rollout_steps) ? rec.rollout_steps : []
  const steps = stepsRaw.map((s) => {
    if (typeof s === "string") return s
    const r = asRecord(s)
    if (!r) return String(s)
    const title = r.title || r.step || r.name
    const detail = r.detail || r.description || r.sql_snippet || r.rationale
    return [title, detail].filter(Boolean).map(String).join(" — ")
  })
  return {
    strategy:
      rec.recommended_strategy != null
        ? String(rec.recommended_strategy)
        : null,
    rationale: rec.rationale != null ? String(rec.rationale) : null,
    rolloutSteps: steps,
    monitoringChecklist: asStringArray(rec.monitoring_checklist),
    rollbackGuidance:
      rec.rollback_guidance != null ? String(rec.rollback_guidance) : null,
    saferAlternativePlan:
      rec.safer_alternative_plan != null
        ? String(rec.safer_alternative_plan)
        : null,
    suggestedDeploymentWindow:
      rec.suggested_deployment_window != null
        ? String(rec.suggested_deployment_window)
        : null,
  }
}

export function mapAssessment(run: MigrationRun): AssessmentView {
  const explainability = asRecord(run.explainability)
  return {
    policyDecision: run.policy_decision ?? null,
    compatibilityRisk: run.compatibility_risk ?? null,
    requiresManualReview: run.requires_manual_review ?? null,
    requiresExpandContract: run.requires_expand_contract ?? null,
    riskFlags: mapRiskFlags(run.risk_flags),
    prediction: mapPrediction(explainability, run),
    confidence: mapConfidence(explainability),
    recommendation: mapRecommendation(run, explainability),
    retrieval: mapRetrieval(explainability),
    parsedStatementTypes: run.parsed_statement_types ?? [],
  }
}

export function mapSchema(run: MigrationRun): SchemaView | null {
  const snap = asRecord(run.schema_snapshot)
  if (!snap && !run.schema_discovery_status) return null

  // Live discovery nests tables under schemas[]; fake/debug snapshots may also
  // expose a flat tables array. Prefer nested, fall back to flat.
  const tablesRaw: unknown[] = []
  if (Array.isArray(snap?.schemas)) {
    for (const schema of snap.schemas) {
      const s = asRecord(schema)
      if (s && Array.isArray(s.tables)) tablesRaw.push(...s.tables)
    }
  }
  if (tablesRaw.length === 0 && Array.isArray(snap?.tables)) {
    tablesRaw.push(...snap.tables)
  }
  const tables: SchemaTableView[] = tablesRaw.map((item) => {
    const t = asRecord(item) || {}
    const name = String(t.name ?? t.table_name ?? "table")
    const colsRaw = Array.isArray(t.columns) ? t.columns : []
    const columns = colsRaw.map((c) => {
      const col = asRecord(c) || {}
      return {
        name: String(col.name ?? col.column_name ?? "?"),
        type: String(col.type ?? col.data_type ?? col.udt_name ?? "?"),
      }
    })
    const idxRaw = Array.isArray(t.indexes) ? t.indexes : []
    const indexes = idxRaw.map((idx) => {
      if (typeof idx === "string") return idx
      const i = asRecord(idx) || {}
      return String(i.name ?? i.index_name ?? JSON.stringify(idx))
    })
    const size =
      t.approximate_size_bytes != null
        ? formatStorage(Number(t.approximate_size_bytes) / (1024 * 1024))
        : t.approximate_size != null
          ? String(t.approximate_size)
          : t.estimated_size_mb != null
            ? formatStorage(Number(t.estimated_size_mb))
            : null
    return {
      name,
      estimatedRowCount:
        t.estimated_row_count == null ? null : Number(t.estimated_row_count),
      approximateSize: size,
      columns,
      indexes,
    }
  })

  return {
    engine: run.schema_database_engine ?? null,
    version: run.schema_database_version ?? null,
    status: run.schema_discovery_status ?? null,
    discoveredAt: run.schema_discovered_at ?? null,
    durationMs: run.schema_discovery_duration_ms ?? null,
    tables,
    debugKind: snap?.debug_kind != null ? String(snap.debug_kind) : null,
    debugNote: snap?.debug_note != null ? String(snap.debug_note) : null,
    isSynthetic: Boolean(snap?.debug_synthetic),
  }
}

export function mapProcessStages(run: MigrationRun): Array<{
  id: string
  label: string
  state: ProcessStageState
}> {
  const status = run.status
  const wf = run.workflow_status
  const order = [
    "create",
    "predict",
    "approve",
    "shadow",
    "grade",
    "remember",
  ] as const

  let active: (typeof order)[number] = "create"
  if (status === "pending") active = "create"
  else if (status === "predicting") active = "predict"
  else if (status === "awaiting_approval") active = "approve"
  else if (status === "running") active = "shadow"
  else if (status === "completed") {
    active = "remember"
  } else if (status === "failed") {
    if (wf === "failed" || wf === "timed_out" || wf === "aborted") {
      active = "shadow"
    } else if (run.policy_decision) {
      active = "approve"
    } else {
      active = "predict"
    }
  }

  const activeIdx = order.indexOf(active)
  return order.map((id, idx) => {
    let state: ProcessStageState = "pending"
    if (status === "failed" && idx === activeIdx) state = "failed"
    else if (status === "completed") state = "complete"
    else if (idx < activeIdx) state = "complete"
    else if (idx === activeIdx) state = "current"
    const labels: Record<(typeof order)[number], string> = {
      create: "Create",
      predict: "Predict",
      approve: "Approve",
      shadow: "Shadow",
      grade: "Grade",
      remember: "Remember",
    }
    return { id, label: labels[id], state }
  })
}

/** Format a stage timing value. Backend writes `*_ms` keys in milliseconds. */
export function formatStageTiming(value: unknown, keyHint = ""): string | null {
  if (value == null) return null
  if (typeof value === "number") {
    const looksMs =
      keyHint.endsWith("_ms") || keyHint.includes("_ms") || value > 50
    if (looksMs) {
      if (value >= 1000) return `${(value / 1000).toFixed(1)}s`
      return `${Math.round(value)} ms`
    }
    return formatDuration(value)
  }
  if (typeof value === "string") return value
  const rec = asRecord(value)
  if (rec?.duration_seconds != null) {
    return formatDuration(Number(rec.duration_seconds))
  }
  if (rec?.duration_ms != null) {
    return formatStageTiming(Number(rec.duration_ms), "duration_ms")
  }
  if (rec?.finished_at != null) return String(rec.finished_at)
  if (rec?.at != null) return String(rec.at)
  return null
}

function timingValue(
  timings: Record<string, unknown> | null,
  keys: string[]
): string | null {
  if (!timings) return null
  for (const key of keys) {
    if (!(key in timings)) continue
    const formatted = formatStageTiming(timings[key], key)
    if (formatted) return formatted
  }
  return null
}

export type ShadowLiveStage = {
  id: string
  label: string
  state: ProcessStageState
  durationLabel: string | null
  detail: string | null
  /** Short plain-English description of what this step does. */
  hint: string
}

/**
 * Live shadow lifecycle from `shadow_clusters.status` + `stage_timings`.
 * Backend order: provisioning → ready → seeding → migrating → destroying → destroyed.
 * Always returns the full step list so the UI can show the playbook before/during/after.
 */
export function mapShadowLiveStages(
  shadow: ShadowCluster | null,
  opts?: {
    workflowRunning?: boolean
    hasExecution?: boolean
    /** Approved but SFN not started yet — show steps idle, first as next. */
    awaitingStart?: boolean
  }
): ShadowLiveStage[] {
  const status = (shadow?.status || "").toLowerCase()
  const timings = asRecord(shadow?.stage_timings)
  const order = [
    "provisioning",
    "ready",
    "seeding",
    "migrating",
    "destroying",
    "destroyed",
  ] as const
  const labels: Record<(typeof order)[number], string> = {
    provisioning: "1. Provision cluster",
    ready: "2. Cluster ready",
    seeding: "3. Seed schema + data",
    migrating: "4. Execute your migration",
    destroying: "5. Tear down cluster",
    destroyed: "6. Torn down",
  }
  const hints: Record<(typeof order)[number], string> = {
    provisioning: "Create a disposable CockroachDB Cloud cluster tagged for this run.",
    ready: "Wait until the cluster is online and accepting connections.",
    seeding: "Load schema (and sample data) so the shadow looks like your DB.",
    migrating: "Run your exact migration SQL and measure duration + storage.",
    destroying: "Delete the disposable cluster so nothing is left running.",
    destroyed: "Cleanup finished. Prediction vs actual is ready to grade.",
  }
  const timingKeys: Record<(typeof order)[number], string[]> = {
    provisioning: ["provision_ms", "provision", "provisioning"],
    ready: ["ready_ms", "ready"],
    seeding: ["seed_ms", "load_ms", "seed", "load", "seeding"],
    migrating: ["migrate_ms", "execute_ms", "migrate", "execute", "execution"],
    destroying: ["teardown_ms", "cleanup_ms", "teardown", "cleanup"],
    destroyed: ["teardown_ms", "cleanup_ms", "teardown", "cleanup"],
  }

  const idlePreview = Boolean(opts?.awaitingStart) && !shadow && !opts?.workflowRunning

  if (!shadow && (opts?.workflowRunning || idlePreview)) {
    return order.map((id, idx) => ({
      id,
      label: labels[id],
      state: idlePreview
        ? idx === 0
          ? "current"
          : "pending"
        : idx === 0
          ? "current"
          : "pending",
      durationLabel: null,
      detail: idlePreview
        ? idx === 0
          ? "Click Start shadow test to begin"
          : null
        : idx === 0
          ? "Waiting for shadow_cluster row…"
          : null,
      hint: hints[id],
    }))
  }

  if (!shadow) {
    return order.map((id) => ({
      id,
      label: labels[id],
      state: "pending" as const,
      durationLabel: null,
      detail: null,
      hint: hints[id],
    }))
  }

  const statusIdx = order.indexOf(status as (typeof order)[number])
  let lastTimedIdx = -1
  for (let i = 0; i < order.length; i++) {
    const stageId = order[i]
    if (stageId && timingValue(timings, timingKeys[stageId])) lastTimedIdx = i
  }
  const cursor =
    status === "destroyed"
      ? order.length - 1
      : status === "failed"
        ? Math.max(statusIdx, lastTimedIdx, 0)
        : statusIdx >= 0
          ? statusIdx
          : Math.min(lastTimedIdx + 1, order.length - 1)

  return order.map((id, idx) => {
    const durationLabel = timingValue(timings, timingKeys[id])
    let state: ProcessStageState
    if (status === "destroyed") {
      state = "complete"
    } else if (status === "failed") {
      state = idx < cursor ? "complete" : idx === cursor ? "failed" : "pending"
    } else if (idx < cursor) {
      state = "complete"
    } else if (idx === cursor) {
      state = "current"
    } else {
      state = "pending"
    }

    let detail: string | null = null
    if (id === "provisioning") {
      detail = shadow.cluster_name || shadow.cluster_id || null
    } else if (id === "migrating" && opts?.hasExecution) {
      detail = "Measured"
    } else if (shadow.error_message && state === "failed") {
      detail = shadow.error_message
    }

    return {
      id,
      label: labels[id],
      state,
      durationLabel,
      detail,
      hint: hints[id],
    }
  })
}

export function mapLifecycle(
  run: MigrationRun,
  extras: RunExtras
): LifecycleStage[] {
  const shadow = extras.shadow
  const timings = asRecord(shadow?.stage_timings)
  const hasPrediction = Boolean(run.explainability || run.recommendation)
  const approved =
    run.status === "running" ||
    run.status === "completed" ||
    (run.status === "failed" && run.workflow_status !== "not_started")

  const stages: LifecycleStage[] = [
    {
      id: "created",
      label: "Created",
      state: "complete",
      at: run.created_at,
      outcome: statusLabel(run.status),
    },
    {
      id: "discovered",
      label: "Discovered",
      state:
        run.schema_discovery_status === "succeeded"
          ? "complete"
          : run.schema_discovery_status === "failed" ||
              run.schema_discovery_status === "rejected"
            ? "failed"
            : run.schema_discovery_status === "pending"
              ? "current"
              : "pending",
      at: run.schema_discovered_at,
      durationLabel:
        run.schema_discovery_duration_ms != null
          ? `${Math.round(run.schema_discovery_duration_ms)} ms`
          : null,
      outcome: run.schema_discovery_status,
      error:
        run.schema_discovery_status === "failed" ||
        run.schema_discovery_status === "rejected"
          ? "Schema discovery did not succeed — see run error / API detail."
          : null,
    },
    {
      id: "predicted",
      label: "Predicted",
      state: hasPrediction
        ? "complete"
        : run.status === "predicting"
          ? "current"
          : "pending",
      outcome: hasPrediction
        ? `policy=${run.policy_decision || "—"}`
        : null,
    },
    {
      id: "approved",
      label: "Approved",
      state: approved
        ? "complete"
        : run.status === "awaiting_approval"
          ? "current"
          : run.status === "failed" && !hasPrediction
            ? "pending"
            : run.status === "failed"
              ? "failed"
              : "pending",
      outcome: approved ? statusLabel(run.status) : null,
    },
    {
      id: "provisioned",
      label: "Provisioned",
      state: shadow?.cluster_id
        ? "complete"
        : run.status === "running"
          ? "current"
          : shadow?.error_message
            ? "failed"
            : "pending",
      durationLabel: timingValue(timings, ["provision_ms", "provision", "provisioning"]),
      outcome: shadow?.cluster_id || shadow?.status || null,
      error: shadow?.error_message ?? null,
    },
    {
      id: "seeded",
      label: "Seeded",
      state: timingValue(timings, ["seed_ms", "load_ms", "seed", "load", "seeding"])
        ? "complete"
        : shadow?.cluster_id && run.status === "running"
          ? "current"
          : "pending",
      durationLabel: timingValue(timings, ["seed_ms", "load_ms", "seed", "load", "seeding"]),
    },
    {
      id: "executed",
      label: "Executed",
      state: extras.execution
        ? extras.execution.success
          ? "complete"
          : "failed"
        : run.status === "running"
          ? "current"
          : "pending",
      durationLabel: extras.execution
        ? formatDuration(extras.execution.actual_duration_seconds)
        : timingValue(timings, ["migrate_ms", "execute_ms", "migrate", "execute", "execution"]),
      outcome: extras.execution
        ? extras.execution.success
          ? "success"
          : "failed"
        : null,
      error: extras.execution?.error_message ?? null,
    },
    {
      id: "verified",
      label: "Verified",
      state:
        run.workflow_status === "succeeded" || extras.grade
          ? "complete"
          : run.workflow_status === "failed" ||
              run.workflow_status === "timed_out" ||
              run.workflow_status === "aborted"
            ? "failed"
            : run.workflow_status === "running"
              ? "current"
              : "pending",
      at: run.workflow_finished_at,
      outcome: workflowLabel(run.workflow_status),
    },
    {
      id: "torn_down",
      label: "Torn down",
      state: shadow?.destroyed_at
        ? "complete"
        : shadow?.error_message && shadow?.cluster_id
          ? "failed"
          : "pending",
      at: shadow?.destroyed_at ?? null,
      outcome: shadow?.destroyed_at ? "destroyed" : null,
      error:
        !shadow?.destroyed_at && shadow?.error_message
          ? shadow.error_message
          : null,
    },
    {
      id: "graded",
      label: "Graded",
      state: extras.grade
        ? "complete"
        : run.status === "completed"
          ? "current"
          : "pending",
      at: extras.grade?.created_at ?? null,
      outcome: extras.grade
        ? `${extras.grade.outcome_class} · score=${extras.grade.scalar_accuracy_score}`
        : null,
      error: extras.grade?.prose_error ?? null,
    },
    {
      id: "remembered",
      label: "Remembered",
      state: extras.memory ? "complete" : "pending",
      at: extras.memory?.created_at ?? null,
      outcome: extras.memory
        ? `${extras.memory.embedding_status} · ${extras.memory.migration_type}`
        : null,
      error: extras.memory?.embedding_error ?? null,
    },
  ]

  return stages
}

export function mapComparisons(
  run: MigrationRun,
  extras: RunExtras
): ComparisonRow[] {
  const assessment = mapAssessment(run)
  const pred = assessment.prediction
  const exec = extras.execution
  const grade = extras.grade
  if (!pred && !exec && !grade) return []

  const measuring =
    run.status === "running" || run.workflow_status === "running"
  const pendingActual = measuring ? "measuring…" : "—"

  const rows: ComparisonRow[] = []
  if (pred?.estimatedDurationSeconds != null || exec || grade) {
    const predicted = formatDuration(pred?.estimatedDurationSeconds)
    const actual = exec
      ? formatDuration(exec.actual_duration_seconds)
      : pendingActual
    const delta =
      grade?.duration_abs_error_seconds != null
        ? `±${formatDuration(grade.duration_abs_error_seconds)}`
        : undefined
    const withinBand = grade?.duration_within_band ?? null
    rows.push({
      label: "Duration",
      predicted,
      actual,
      delta,
      withinBand,
      bandNote:
        withinBand === true
          ? pred &&
            exec &&
            Number(pred.estimatedDurationSeconds) >
              Number(exec.actual_duration_seconds)
            ? "OK — model was conservative (over-estimated)"
            : "OK — within the accepted accuracy band"
          : withinBand === false
            ? "Outside band — worth reviewing why"
            : measuring
              ? "Waiting for shadow measurement"
              : null,
    })
  }
  if (pred?.estimatedStorageMb != null || exec || grade) {
    const withinBand = grade?.storage_within_band ?? null
    const actualMb = exec ? Number(exec.actual_storage_mb) : null
    rows.push({
      label: "Storage",
      predicted: formatStorage(pred?.estimatedStorageMb),
      actual: exec ? formatStorage(exec.actual_storage_mb) : pendingActual,
      delta:
        grade?.storage_abs_error_mb != null
          ? `±${formatStorage(grade.storage_abs_error_mb)}`
          : undefined,
      withinBand,
      bandNote:
        withinBand === true
          ? actualMb === 0
            ? "OK — small DDL often shows ~0 MB on approximate disk stats"
            : "OK — within the accepted accuracy band"
          : withinBand === false
            ? "Outside band — worth reviewing why"
            : measuring
              ? "Waiting for shadow measurement"
              : null,
    })
  }
  if (pred?.rollbackRisk || grade) {
    const withinBand = grade?.rollback_within_band ?? null
    rows.push({
      label: "Rollback",
      predicted: pred?.rollbackRisk || grade?.rollback_predicted || "—",
      actual: grade?.rollback_actual_class || pendingActual,
      withinBand,
      bandNote:
        withinBand === true
          ? "OK — risk class matched the band (often slightly cautious)"
          : withinBand === false
            ? "Outside band — worth reviewing why"
            : measuring
              ? "Waiting for grade"
              : null,
    })
  }
  return rows
}

export function mapRunListItem(item: MigrationRunSummary) {
  return {
    id: item.id,
    status: item.status,
    statusLabel: statusLabel(item.status),
    workflowStatus: item.workflow_status,
    workflowLabel: workflowLabel(item.workflow_status),
    createdAt: item.created_at,
    createdAgo: formatRelativeTime(item.created_at),
    ownerIdentity: item.owner_identity,
    sqlSnippet: item.sql_snippet,
    policyDecision: item.policy_decision,
    scaleTier: item.prediction_scale_tier,
    isTerminal: item.is_terminal,
    isFailed: item.status === "failed",
    isCancelledLook: item.status === "failed" && item.workflow_status === "aborted",
  }
}

export function decisionHeadline(run: MigrationRun): string {
  const policy = run.policy_decision
  if (run.status === "completed") return "Shadow verified"
  if (run.status === "failed") return "Run failed"
  if (run.status === "awaiting_approval") {
    if (policy === "block") return "Blocked by policy — overridable"
    if (policy === "allow_with_warning") return "Proceed with caution"
    return "Ready for approval"
  }
  if (run.status === "running") return "Shadow execution in progress"
  if (run.status === "predicting") return "Prediction in progress"
  return statusLabel(run.status)
}

export function discoverErrorHint(status: number, message: string): string {
  if (status === 401) {
    return `Authentication failed against the database. ${message}`
  }
  if (status === 403) {
    return `Permissions rejected (credentials must be read-only for discovery). ${message}`
  }
  if (status === 404) {
    return `Database not found. ${message}`
  }
  if (status === 408) {
    return `Discovery timed out. ${message}`
  }
  if (status === 422) {
    return `Bad connection secret ARN or invalid request. ${message}`
  }
  if (status === 503) {
    return `Database unreachable. ${message}`
  }
  if (status === 400) {
    return `Connection / SSL problem. ${message}`
  }
  return message
}
