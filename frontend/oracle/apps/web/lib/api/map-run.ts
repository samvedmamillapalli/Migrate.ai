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

/**
 * Summary statistics over the retrieved set, computed server-side in
 * MemoryRetrievalResult.retrieval_aggregates(). Rates cover graded shadow
 * runs only — open-source incidents and seed rows land in `ungradedCount`
 * and are excluded, so a corpus full of documented incidents can't be
 * misread as a 100% success record.
 */
export type RetrievalAggregates = {
  retrievedCount: number
  gradedCount: number
  ungradedCount: number
  succeededCount: number
  failedCount: number
  successRate: number | null
  meanActualDurationSeconds: number | null
  durationSampleSize: number
  topSimilarity: number | null
  meanSimilarity: number | null
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
  /** Null for runs predicted before aggregates were emitted. */
  aggregates: RetrievalAggregates | null
}

export type ConfidenceView = {
  raw: number | null
  adjusted: number | null
  percentLabel: string
  /** Raw model-proposed confidence, formatted the same way — shown alongside
   * the adjusted headline so the clamp is visible, not just its result. */
  rawPercentLabel: string
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

/** One CockroachDB Agent Skill (cockroachlabs/cockroachdb-skills) consulted
 * for the recommendation, retrieved via CockroachDB's Distributed Vector
 * Index — see docs/cockroach_hookup.md §5. */
export type ConsultedSkillView = {
  slug: string
  title: string
  category: string
  description: string
  sourceUrl: string
  similarityScore: number | null
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
  consultedSkills: ConsultedSkillView[]
  parsedStatementTypes: string[]
}

export type SchemaColumnView = {
  name: string
  type: string
  /** null when the snapshot didn't record nullability. */
  nullable: boolean | null
  isPrimaryKey: boolean
  isUnique: boolean
  isForeignKey: boolean
  keyLabel: string | null
  defaultValue: string | null
}

export type SchemaTableView = {
  name: string
  estimatedRowCount: number | null
  approximateSize: string | null
  columns: SchemaColumnView[]
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

/**
 * Defensive cleanup for model-written summary prose (risk_explanation,
 * recommendation rationale). The prompt asks for plain text with no
 * markdown, but models don't always comply — this strips stray decoration
 * so a `**bold**` or numbered-list slip never renders literally in the UI.
 */
export function stripMarkdownDecoration(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^[-*]\s+/gm, "")
    .replace(/^\d+\.\s+/gm, "")
    .replace(/\n{2,}/g, " ")
    .replace(/\n/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim()
}

function splitSentences(text: string): string[] {
  const matches = text.match(/[^.!?]+[.!?]+(\s+|$)/g)
  if (!matches) return text ? [text] : []
  return matches.map((s) => s.trim()).filter(Boolean)
}

export type ClampedProse = {
  visible: string
  /** Sentences past the cap, or null if nothing was cut. */
  overflow: string | null
}

/**
 * Caps model-written summary prose to a handful of plain sentences for the
 * always-visible headline, with anything past that available separately
 * (the caller decides where — e.g. under "Show details") instead of ever
 * dumping an unbounded essay into the main assessment card.
 */
export function clampProse(
  raw: string | null | undefined,
  maxSentences = 4
): ClampedProse {
  if (!raw) return { visible: "", overflow: null }
  const cleaned = stripMarkdownDecoration(raw)
  const sentences = splitSentences(cleaned)
  if (sentences.length <= maxSentences) {
    return { visible: cleaned, overflow: null }
  }
  return {
    visible: sentences.slice(0, maxSentences).join(" "),
    overflow: sentences.slice(maxSentences).join(" "),
  }
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

  const rawAgg = asRecord(memory?.aggregates)
  const aggregates: RetrievalAggregates | null = rawAgg
    ? {
        retrievedCount: Number(rawAgg.retrieved_count ?? 0),
        gradedCount: Number(rawAgg.graded_count ?? 0),
        ungradedCount: Number(rawAgg.ungraded_count ?? 0),
        succeededCount: Number(rawAgg.succeeded_count ?? 0),
        failedCount: Number(rawAgg.failed_count ?? 0),
        successRate:
          rawAgg.success_rate == null ? null : Number(rawAgg.success_rate),
        meanActualDurationSeconds:
          rawAgg.mean_actual_duration_seconds == null
            ? null
            : Number(rawAgg.mean_actual_duration_seconds),
        durationSampleSize: Number(rawAgg.duration_sample_size ?? 0),
        topSimilarity:
          rawAgg.top_similarity == null ? null : Number(rawAgg.top_similarity),
        meanSimilarity:
          rawAgg.mean_similarity == null
            ? null
            : Number(rawAgg.mean_similarity),
      }
    : null

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
    aggregates,
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
    rawPercentLabel: formatPercent(raw),
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

function mapConsultedSkills(
  explainability: Record<string, unknown> | null
): ConsultedSkillView[] {
  const skills = asRecord(explainability?.cockroachdb_skills)
  const rawSkills = Array.isArray(skills?.skills) ? skills!.skills : []
  return rawSkills.map((item) => {
    const s = asRecord(item) || {}
    return {
      slug: String(s.skill_slug ?? ""),
      title: String(s.title ?? s.skill_slug ?? ""),
      category: String(s.category ?? ""),
      description: String(s.description ?? ""),
      sourceUrl: String(s.source_url ?? ""),
      similarityScore:
        s.similarity_score == null ? null : Number(s.similarity_score),
    }
  })
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
    consultedSkills: mapConsultedSkills(explainability),
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
    // Foreign keys are declared at table level; index them by constrained
    // column so each column can report its own FK marker.
    const fkColumns = new Set<string>()
    const fkRaw = Array.isArray(t.foreign_keys) ? t.foreign_keys : []
    for (const item of fkRaw) {
      const fk = asRecord(item) || {}
      const cols = Array.isArray(fk.constrained_columns)
        ? fk.constrained_columns
        : []
      for (const c of cols) fkColumns.add(String(c).toLowerCase())
    }
    const pkNames = new Set(
      (Array.isArray(t.primary_key) ? t.primary_key : []).map((c) =>
        String(c).toLowerCase()
      )
    )

    const colsRaw = Array.isArray(t.columns) ? t.columns : []
    const columns = colsRaw.map((c) => {
      const col = asRecord(c) || {}
      const name = String(col.name ?? col.column_name ?? "?")
      const lower = name.toLowerCase()
      const isPrimary = Boolean(col.is_primary_key) || pkNames.has(lower)
      const isForeign = fkColumns.has(lower)
      const isUnique = Boolean(col.is_unique)
      // `is_nullable` is authoritative when present; undefined means the
      // snapshot predates it, which is reported as unknown rather than
      // silently defaulting to nullable.
      const nullable =
        col.is_nullable == null ? null : Boolean(col.is_nullable)
      return {
        name,
        type: String(col.type ?? col.data_type ?? col.udt_name ?? "?"),
        nullable,
        isPrimaryKey: isPrimary,
        isUnique,
        isForeignKey: isForeign,
        /** "PK" | "FK" | "UNIQUE" | null — the design's Key column. */
        keyLabel: isPrimary
          ? "PK"
          : isForeign
            ? "FK"
            : isUnique
              ? "UNIQUE"
              : null,
        defaultValue:
          col.column_default == null ? null : String(col.column_default),
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

// --- Shadow execution live view (3-band: rail / stage panel / event log) ---

export type LifecycleRailStageId =
  | "provision"
  | "seed"
  | "execute"
  | "measure"
  | "teardown"

export type LifecycleRailStage = {
  id: LifecycleRailStageId
  label: string
  state: ProcessStageState
  durationLabel: string | null
}

const RAIL_ORDER: LifecycleRailStageId[] = [
  "provision",
  "seed",
  "execute",
  "measure",
  "teardown",
]
const RAIL_LABELS: Record<LifecycleRailStageId, string> = {
  provision: "Provision",
  seed: "Seed",
  execute: "Execute",
  measure: "Measure",
  teardown: "Teardown",
}

/**
 * Five-stage lifecycle rail from `shadow_clusters.status` + `stage_timings`.
 * "measure" has no backend status of its own (introducing one would touch the
 * locked shadow state machine) — it's a frontend-only pseudo-stage: current
 * once ExecuteMigration has recorded `migrate_ms` but the cluster hasn't
 * started tearing down yet (CollectMetrics/PersistResults are running).
 * Always returns the full 5-item list so the UI can show the whole playbook
 * before/during/after, same as the old 6-step mapper did.
 */
export function mapShadowLifecycleRail(
  shadow: ShadowCluster | null,
  opts?: { workflowRunning?: boolean; awaitingStart?: boolean }
): LifecycleRailStage[] {
  if (!shadow) {
    const showFirstCurrent = Boolean(opts?.workflowRunning || opts?.awaitingStart)
    return RAIL_ORDER.map((id, idx) => ({
      id,
      label: RAIL_LABELS[id],
      state: idx === 0 && showFirstCurrent ? "current" : "pending",
      durationLabel: null,
    }))
  }

  const status = (shadow.status || "").toLowerCase()
  const timings = asRecord(shadow.stage_timings)
  const provisionMs = timingValue(timings, ["provision_ms", "ready_ms"])
  const seedMs = timingValue(timings, ["seed_ms", "load_ms"])
  const migrateMs = timingValue(timings, ["migrate_ms", "execute_ms"])
  const teardownMs = timingValue(timings, ["teardown_ms", "cleanup_ms"])

  let cursor: number
  if (status === "destroyed") {
    cursor = RAIL_ORDER.length - 1
  } else if (status === "failed") {
    if (teardownMs) cursor = 4
    else if (migrateMs) cursor = 3
    else if (seedMs) cursor = 2
    else if (provisionMs) cursor = 1
    else cursor = 0
  } else if (status === "seeding") {
    cursor = 1
  } else if (status === "migrating") {
    cursor = migrateMs ? 3 : 2
  } else if (status === "destroying") {
    cursor = 4
  } else if (status === "holding") {
    // Execution + measurement are done; teardown is deliberately paused
    // (see mapShadowHold) rather than pending — reads naturally as "current"
    // on the teardown stage, which is exactly what's happening.
    cursor = 4
  } else {
    cursor = 0 // provisioning | ready
  }

  const durationLabels: Record<LifecycleRailStageId, string | null> = {
    provision: provisionMs,
    seed: seedMs,
    execute: migrateMs,
    measure: null,
    teardown: teardownMs,
  }

  return RAIL_ORDER.map((id, idx) => {
    let state: ProcessStageState
    if (status === "destroyed") state = "complete"
    else if (status === "failed") {
      state = idx < cursor ? "complete" : idx === cursor ? "failed" : "pending"
    } else if (idx < cursor) state = "complete"
    else if (idx === cursor) state = "current"
    else state = "pending"
    return { id, label: RAIL_LABELS[id], state, durationLabel: durationLabels[id] }
  })
}

export type ShadowHoldView = {
  isHolding: boolean
  expiresAt: string | null
  /** null once expired/unknown — render "any moment now" rather than a negative countdown. */
  secondsRemaining: number | null
}

/** The cluster (and the before/after data already captured) is deliberately
 * kept alive for a bounded window after execute+measure finish — see
 * ShadowClusterStatus.HOLDING. `now` is injectable for testing; callers
 * re-derive this every tick (e.g. on a 1s interval) rather than computing
 * `secondsRemaining` once, since it's a live countdown. */
export function mapShadowHold(
  shadow: ShadowCluster | null,
  now: number = Date.now()
): ShadowHoldView {
  const isHolding = (shadow?.status || "").toLowerCase() === "holding"
  const expiresAt = isHolding ? (shadow?.expires_at ?? null) : null
  if (!expiresAt) {
    return { isHolding, expiresAt: null, secondsRemaining: null }
  }
  const remainingMs = new Date(expiresAt).getTime() - now
  return {
    isHolding,
    expiresAt,
    secondsRemaining: remainingMs > 0 ? Math.round(remainingMs / 1000) : 0,
  }
}

export type ExecutePanelView = {
  jobId: string | null
  description: string | null
  runningStatus: string | null
  fractionCompleted: number | null
  jobStatus: string | null
  /** True once at least one live notice-driven observation was captured —
   * distinguishes a real animated bar from the post-hoc fallback snapshot. */
  observedLive: boolean
  fallbackJobs: Array<{
    jobId: string | null
    jobType: string | null
    status: string | null
    description: string | null
  }>
}

/** The execute stage's job panel — CockroachDB narrating its own work. */
export function mapExecutePanel(shadow: ShadowCluster | null): ExecutePanelView {
  const timings = asRecord(shadow?.stage_timings)
  const observations = Array.isArray(timings?.job_progress)
    ? (timings!.job_progress as unknown[])
    : []
  const latest =
    observations.length > 0 ? asRecord(observations[observations.length - 1]) : null
  const jobWatch = Array.isArray(timings?.job_watch)
    ? (timings!.job_watch as unknown[])
    : []
  return {
    jobId: latest ? String(latest.job_id ?? "") || null : null,
    description: latest ? ((latest.description as string) ?? null) : null,
    runningStatus: latest ? ((latest.running_status as string) ?? null) : null,
    fractionCompleted:
      latest && latest.fraction_completed != null
        ? Number(latest.fraction_completed)
        : null,
    jobStatus: latest ? ((latest.status as string) ?? null) : null,
    observedLive: observations.length > 0,
    fallbackJobs: jobWatch.map((j) => {
      const r = asRecord(j) || {}
      return {
        jobId: (r.job_id as string) ?? null,
        jobType: (r.job_type as string) ?? null,
        status: (r.status as string) ?? null,
        description: (r.description as string) ?? null,
      }
    }),
  }
}

export type SchemaDiffColumnView = {
  name: string
  kind: "added" | "removed" | "changed" | "unchanged"
  beforeType?: string | null
  afterType?: string | null
  type?: string | null
}

export type SchemaDiffTableView = {
  name: string
  kind: "added" | "removed" | "changed" | "unchanged"
  columns: SchemaDiffColumnView[]
  indexesAdded: string[]
  indexesRemoved: string[]
  constraintsAdded: string[]
  constraintsRemoved: string[]
}

/**
 * Structural before/after diff, colored by change type — never by quality
 * (a migration usually doesn't "improve" anything, so nothing here reads as
 * better/worse). None while snapshots haven't been captured yet.
 */
export function mapSchemaDiff(shadow: ShadowCluster | null): SchemaDiffTableView[] {
  const diff = asRecord(shadow?.schema_diff)
  const tables = Array.isArray(diff?.tables) ? (diff!.tables as unknown[]) : []
  return tables.map((t) => {
    const r = asRecord(t) || {}
    const cols = Array.isArray(r.columns) ? (r.columns as unknown[]) : []
    return {
      name: String(r.name ?? ""),
      kind: (r.kind as SchemaDiffTableView["kind"]) || "unchanged",
      columns: cols.map((c) => {
        const cr = asRecord(c) || {}
        return {
          name: String(cr.name ?? ""),
          kind: (cr.kind as SchemaDiffColumnView["kind"]) || "unchanged",
          beforeType: (cr.before_type as string) ?? null,
          afterType: (cr.after_type as string) ?? null,
          type: (cr.type as string) ?? null,
        }
      }),
      indexesAdded: Array.isArray(r.indexes_added)
        ? (r.indexes_added as unknown[]).map(String)
        : [],
      indexesRemoved: Array.isArray(r.indexes_removed)
        ? (r.indexes_removed as unknown[]).map(String)
        : [],
      constraintsAdded: Array.isArray(r.constraints_added)
        ? (r.constraints_added as unknown[]).map(String)
        : [],
      constraintsRemoved: Array.isArray(r.constraints_removed)
        ? (r.constraints_removed as unknown[]).map(String)
        : [],
    }
  })
}

// --- cluster comparison ------------------------------------------------------

export type ClusterTableView = {
  /** "schema.table" — the same key `build_schema_diff` classifies tables under. */
  key: string
  name: string
  schemaName: string
  columnCount: number
  indexCount: number
  /** null when the target never reported an estimate for this table. */
  rowCount: number | null
  diffKind: "added" | "removed" | "changed" | "unchanged"
}

export type ClusterCardView = {
  databaseName: string | null
  /** e.g. "appdb / public" — database plus the non-system schemas present. */
  schemaLabel: string | null
  tables: ClusterTableView[]
  tableCount: number
  indexCount: number
  /** null when no table on this side reported a row estimate. */
  rowCount: number | null
  /**
   * True for the shadow side: its rows are tier-capped synthetic rows written
   * by ShadowSeeder, not the customer's data. The card says so rather than
   * letting the number read as production volume.
   */
  rowsAreSynthetic: boolean
}

export type ClusterChangesView = {
  /** "schema.table" keys. */
  addedTables: string[]
  removedTables: string[]
  /** "schema.table.column" for every column the diff classified as changed. */
  modifiedColumns: string[]
  changedTables: string[]
  unchangedTableCount: number
}

export type ClusterColumnRowView = {
  name: string
  type: string | null
  kind: "added" | "removed" | "changed" | "unchanged"
}

/**
 * One touched table's full column list on EACH side — every column that
 * really exists in the before snapshot, and every column that really exists
 * in the after snapshot, independently. Not a merged/diffed row set: a
 * column added or removed only ever appears on the side it actually exists
 * on, exactly like the Production/Shadow table cards above it (which list
 * "6 tables" and "8 tables" — different counts on each side, not one merged
 * row list).
 */
export type ClusterColumnTableView = {
  tableName: string
  before: ClusterColumnRowView[]
  after: ClusterColumnRowView[]
}

export type ClusterComparisonView = {
  /**
   * `source_only` — the customer's schema has been discovered but no shadow
   * run has produced an after-snapshot yet. The left card is real and fully
   * populated; only the right one is still pending. This is the state the
   * page sits in between "Discover schema" and the end of a shadow run, and
   * it is deliberately not an error.
   */
  status: "waiting" | "unavailable" | "source_only" | "ready"
  message: string | null
  source: ClusterCardView | null
  shadow: ClusterCardView | null
  /** after − before, from the shadow's own two snapshots. */
  deltas: { tables: number; indexes: number } | null
  changes: ClusterChangesView | null
  /** Column-level detail — see `ClusterColumnTableView`. Empty before a schema
   * is known at all; populated from the production schema alone in
   * `source_only`, and from the diff (touched tables only) once `ready`. */
  columnDetails: ClusterColumnTableView[]
}

const SYSTEM_SCHEMAS = new Set([
  "information_schema",
  "pg_catalog",
  "crdb_internal",
  "pg_extension",
])

/**
 * One row per user table in a persisted DatabaseMetadata snapshot.
 *
 * `key` is built from the *parent schema's* name, not the table's own schema
 * field, because that is exactly how `build_schema_diff._index_tables` keys
 * its output — anything else would fail to line up with the diff. (The two
 * snapshot sources also spell the table's own field differently: the run's
 * discovered snapshot serializes it by alias as `schema`, the shadow's own
 * capture stores `schema_name`, since `model_dump(mode="json")` does not
 * apply `ser_json_by_alias`.)
 */
function readSnapshotTables(snapshot: unknown): ClusterTableView[] {
  const snap = asRecord(snapshot)
  const schemas = Array.isArray(snap?.schemas) ? (snap!.schemas as unknown[]) : []
  const out: ClusterTableView[] = []
  for (const rawSchema of schemas) {
    const schema = asRecord(rawSchema) || {}
    const schemaName = String(schema.name ?? "")
    if (SYSTEM_SCHEMAS.has(schemaName)) continue
    const tables = Array.isArray(schema.tables) ? (schema.tables as unknown[]) : []
    for (const rawTable of tables) {
      const table = asRecord(rawTable) || {}
      const name = String(table.name ?? "")
      if (!name) continue
      const columns = Array.isArray(table.columns) ? table.columns.length : 0
      const rows = table.estimated_row_count
      out.push({
        key: `${schemaName}.${name}`,
        name,
        schemaName,
        columnCount:
          typeof table.column_count === "number" ? table.column_count : columns,
        indexCount: Array.isArray(table.indexes) ? table.indexes.length : 0,
        rowCount: typeof rows === "number" ? rows : null,
        diffKind: "unchanged",
      })
    }
  }
  return out.sort((a, b) => a.key.localeCompare(b.key))
}

/**
 * Real `SELECT count(*)` totals from a row-sample capture, keyed by both the
 * name the migration referenced and the resolved "schema.table".
 *
 * Preferred over the snapshot's `estimated_row_count` wherever it exists: that
 * estimate comes from `SHOW TABLES`, which reads CockroachDB table statistics,
 * and statistics lag a bulk insert — a freshly seeded shadow table reports 0
 * rows for a while even though the rows are there. Only covers the tables the
 * migration referenced, since those are the only ones sampled.
 */
function readRowSampleCounts(rowSample: unknown): Map<string, number> {
  const out = new Map<string, number>()
  const parsed = asRecord(rowSample)
  const tables = asRecord(parsed?.tables)
  if (!tables) return out
  for (const [requested, raw] of Object.entries(tables)) {
    const entry = asRecord(raw) || {}
    const total = entry.total_row_count
    if (typeof total !== "number") continue
    out.set(requested.toLowerCase(), total)
    if (typeof entry.table === "string") {
      out.set(entry.table.toLowerCase(), total)
      const bare = entry.table.split(".").pop()
      if (bare) out.set(bare.toLowerCase(), total)
    }
  }
  return out
}

function resolveRowCount(
  table: ClusterTableView,
  counts: Map<string, number>
): number | null {
  return (
    counts.get(table.key.toLowerCase()) ??
    counts.get(table.name.toLowerCase()) ??
    table.rowCount
  )
}

function buildCard(
  snapshot: unknown,
  tables: ClusterTableView[],
  rowsAreSynthetic: boolean
): ClusterCardView | null {
  if (tables.length === 0) return null
  const snap = asRecord(snapshot)
  const databaseName = snap?.database_name ? String(snap.database_name) : null
  const schemaNames = Array.from(new Set(tables.map((t) => t.schemaName))).sort()
  const withRows = tables.filter((t) => t.rowCount != null)
  return {
    databaseName,
    schemaLabel: [databaseName, schemaNames.join(", ")].filter(Boolean).join(" / ") || null,
    tables,
    tableCount: tables.length,
    indexCount: tables.reduce((sum, t) => sum + t.indexCount, 0),
    rowCount:
      withRows.length > 0
        ? withRows.reduce((sum, t) => sum + (t.rowCount ?? 0), 0)
        : null,
    rowsAreSynthetic,
  }
}

/**
 * Every column of one table, straight from a raw DatabaseMetadata snapshot —
 * real names, real types, in the order the backend reports them. Returns []
 * if the table doesn't exist on this side at all (dropped, or not created
 * yet), which is the correct, honest answer for that side of the box, not an
 * error.
 */
function rawColumnsForTable(
  snapshot: unknown,
  schemaName: string,
  tableName: string
): { name: string; type: string | null }[] {
  const snap = asRecord(snapshot)
  const schemas = Array.isArray(snap?.schemas) ? (snap!.schemas as unknown[]) : []
  for (const rawSchema of schemas) {
    const schema = asRecord(rawSchema) || {}
    if (String(schema.name ?? "") !== schemaName) continue
    const tables = Array.isArray(schema.tables) ? (schema.tables as unknown[]) : []
    for (const rawTable of tables) {
      const table = asRecord(rawTable) || {}
      if (String(table.name ?? "") !== tableName) continue
      const rawColumns = Array.isArray(table.columns) ? (table.columns as unknown[]) : []
      return rawColumns.map((c) => {
        const cr = asRecord(c) || {}
        return { name: String(cr.name ?? ""), type: (cr.data_type as string) ?? null }
      })
    }
  }
  return []
}

/**
 * Column detail before any shadow run exists yet — the left box shows every
 * real column of the customer's own table (all "unchanged", since there's
 * nothing yet to compare against); the right box is empty until a shadow run
 * produces an after-snapshot (the component renders its own "awaiting run"
 * placeholder for that side).
 */
function productionColumnDetails(snapshot: unknown): ClusterColumnTableView[] {
  const snap = asRecord(snapshot)
  const schemas = Array.isArray(snap?.schemas) ? (snap!.schemas as unknown[]) : []
  const out: ClusterColumnTableView[] = []
  for (const rawSchema of schemas) {
    const schema = asRecord(rawSchema) || {}
    const schemaName = String(schema.name ?? "")
    if (SYSTEM_SCHEMAS.has(schemaName)) continue
    const tables = Array.isArray(schema.tables) ? (schema.tables as unknown[]) : []
    for (const rawTable of tables) {
      const table = asRecord(rawTable) || {}
      const tableName = String(table.name ?? "")
      if (!tableName) continue
      const before = rawColumnsForTable(snapshot, schemaName, tableName).map((c) => ({
        ...c,
        kind: "unchanged" as const,
      }))
      out.push({ tableName: `${schemaName}.${tableName}`, before, after: [] })
    }
  }
  return out
}

/**
 * Column detail for every table the migration actually touched (added,
 * removed, or changed) — unchanged tables are already fully described by the
 * summary cards and don't need a column-by-column listing. Each side's
 * column list comes straight from that side's own raw snapshot (see
 * `rawColumnsForTable`), so both boxes are always complete; the diff
 * (`t.columns`) is used only to color each row, never to decide which rows
 * exist.
 */
function diffColumnDetails(
  diffTables: SchemaDiffTableView[],
  schemaBefore: unknown,
  schemaAfter: unknown
): ClusterColumnTableView[] {
  return diffTables
    .filter((t) => t.kind !== "unchanged")
    .map((t) => {
      const parts = t.name.split(".")
      const schemaName = parts[0] ?? ""
      const tableName = parts.slice(1).join(".")
      const kindByName = new Map(t.columns.map((c) => [c.name, c.kind]))
      const withKind = (cols: { name: string; type: string | null }[]) =>
        cols.map((c) => ({ ...c, kind: kindByName.get(c.name) ?? "unchanged" }))
      return {
        tableName: t.name,
        before: withKind(rawColumnsForTable(schemaBefore, schemaName, tableName)),
        after: withKind(rawColumnsForTable(schemaAfter, schemaName, tableName)),
      }
    })
}

/**
 * The side-by-side "source vs shadow" view.
 *
 * Both cards and every add/remove/change badge come from the shadow cluster's
 * own before/after snapshots, so the comparison is apples-to-apples: the same
 * database, measured twice around the migration. The run's discovered
 * production snapshot is used only to label the source card and to show the
 * customer's real row estimates where the same table exists — never to
 * compute the diff, since production and shadow are different clusters and
 * differences between them would not be migration effects.
 */
/**
 * Narrows a discovered table list down to the one table this migration's SQL
 * actually names (via `primaryTableName`). Schema discovery and shadow
 * seeding necessarily capture the whole database — the wizard's table
 * browser is reference-only and never submits a structured "target table"
 * field, `createRun` only ever sends `migration_sql` — so without this every
 * table in the database would show up in the comparison, not just the one
 * the migration touches. Falls back to the full list when there's no target
 * (unparseable SQL) or the target isn't present on this side, so an
 * unrecognized statement degrades to today's behavior instead of showing
 * nothing.
 */
function filterToTargetTable(
  tables: ClusterTableView[],
  targetTable: string | null
): ClusterTableView[] {
  if (!targetTable) return tables
  const filtered = tables.filter((t) => t.name.toLowerCase() === targetTable)
  return filtered.length > 0 ? filtered : tables
}

export function mapClusterComparison(
  run: MigrationRun | null,
  shadow: ShadowCluster | null
): ClusterComparisonView {
  const targetTable = primaryTableName(run?.migration_sql)
  const before = shadow
    ? filterToTargetTable(readSnapshotTables(shadow.schema_snapshot_before), targetTable)
    : []
  const after = shadow
    ? filterToTargetTable(readSnapshotTables(shadow.schema_snapshot_after), targetTable)
    : []

  // Nothing captured on the shadow cluster yet. The customer's own schema is
  // already known the moment "Discover schema" succeeds, so show that as the
  // source card rather than an empty panel — the left half of this comparison
  // never has to wait for a shadow run.
  if (before.length === 0 && after.length === 0) {
    const productionTables = filterToTargetTable(
      readSnapshotTables(run?.schema_snapshot),
      targetTable
    )
    const sourceCard = buildCard(run?.schema_snapshot, productionTables, false)
    const status = (shadow?.status || "").toLowerCase()
    const preMigrate = ["provisioning", "ready", "seeding"].includes(status)
    const failedCapture = Boolean(shadow) && !preMigrate

    if (sourceCard) {
      return {
        status: "source_only",
        message: failedCapture
          ? "No before/after snapshot was captured on the shadow cluster for this run (connection issue or timeout). Your discovered schema is shown on the left; the migration result itself is unaffected."
          : shadow
            ? "Shadow cluster is being prepared — the after side is captured immediately before and after your migration executes."
            : "Run a shadow test to see the after side. Your discovered schema is already shown on the left.",
        source: sourceCard,
        shadow: null,
        deltas: null,
        changes: null,
        columnDetails: productionColumnDetails(run?.schema_snapshot),
      }
    }

    return {
      status: failedCapture ? "unavailable" : "waiting",
      message: failedCapture
        ? "No schema snapshot was captured for this run (connection issue or timeout). This doesn't affect the migration result."
        : "Attach your database and run Discover schema to populate this comparison.",
      source: null,
      shadow: null,
      deltas: null,
      changes: null,
      columnDetails: [],
    }
  }

  // Past this point at least one shadow snapshot exists, so `shadow` is set.
  const liveShadow = shadow!

  const diffTables = mapSchemaDiff(liveShadow)
  const diffByKey = new Map(diffTables.map((t) => [t.name, t]))

  // Real production row estimates, keyed by bare table name so they still
  // match when the customer's schema namespace differs from the shadow's.
  const productionRows = new Map<string, number>()
  for (const t of readSnapshotTables(run?.schema_snapshot)) {
    if (t.rowCount != null) productionRows.set(t.name.toLowerCase(), t.rowCount)
  }

  const withDiff = (tables: ClusterTableView[]): ClusterTableView[] =>
    tables.map((t) => ({
      ...t,
      diffKind: diffByKey.get(t.key)?.kind ?? "unchanged",
    }))

  const beforeCounts = readRowSampleCounts(liveShadow.row_sample_before)
  const afterCounts = readRowSampleCounts(liveShadow.row_sample_after)

  // Source card prefers the customer's real production estimate; where the
  // migration didn't touch that table, fall back to the sampled count and
  // only then to the shadow's own (statistics-lagged) estimate.
  const sourceTables = withDiff(before).map((t) => ({
    ...t,
    rowCount:
      productionRows.get(t.name.toLowerCase()) ?? resolveRowCount(t, beforeCounts),
  }))
  const shadowTables = withDiff(after).map((t) => ({
    ...t,
    rowCount: resolveRowCount(t, afterCounts),
  }))

  const sourceCard = buildCard(liveShadow.schema_snapshot_before, sourceTables, false)
  const shadowCard = buildCard(liveShadow.schema_snapshot_after, shadowTables, true)

  const modifiedColumns: string[] = []
  const addedTables: string[] = []
  const removedTables: string[] = []
  const changedTables: string[] = []
  let unchangedTableCount = 0
  for (const table of diffTables) {
    if (table.kind === "added") addedTables.push(table.name)
    else if (table.kind === "removed") removedTables.push(table.name)
    else if (table.kind === "changed") {
      changedTables.push(table.name)
      for (const column of table.columns) {
        if (column.kind !== "unchanged") {
          modifiedColumns.push(`${table.name}.${column.name}`)
        }
      }
    } else unchangedTableCount += 1
  }

  return {
    status: "ready",
    message: null,
    source: sourceCard,
    shadow: shadowCard,
    deltas:
      sourceCard && shadowCard
        ? {
            tables: shadowCard.tableCount - sourceCard.tableCount,
            indexes: shadowCard.indexCount - sourceCard.indexCount,
          }
        : null,
    changes: {
      addedTables,
      removedTables,
      modifiedColumns,
      changedTables,
      unchangedTableCount,
    },
    columnDetails: diffColumnDetails(
      diffTables,
      liveShadow.schema_snapshot_before,
      liveShadow.schema_snapshot_after
    ),
  }
}

export type CostStripView = {
  durationLabel: string
  storageLabel: string
  jobsRun: number
  success: boolean | null
  timedOut: boolean
}

/** The measured cost strip — the blast-radius definition made visible. */
export function mapCostStrip(extras: RunExtras): CostStripView | null {
  const exec = extras.execution
  if (!exec) return null
  const timings = asRecord(extras.shadow?.stage_timings)
  const jobWatch = Array.isArray(timings?.job_watch)
    ? (timings!.job_watch as unknown[])
    : []
  return {
    durationLabel: formatDuration(exec.actual_duration_seconds),
    storageLabel: formatStorage(exec.actual_storage_mb),
    jobsRun: jobWatch.length,
    success: exec.success,
    timedOut: exec.timed_out,
  }
}

export type ShadowEventLogLine = { at: string; text: string }

/**
 * Append-only event log from `shadow_clusters.event_log` — real persisted
 * observations, not a simulated ticker. Never stops producing output as long
 * as new events keep landing, which is what keeps a stage from feeling frozen.
 */
export function mapShadowEventLog(shadow: ShadowCluster | null): ShadowEventLogLine[] {
  const entries = Array.isArray(shadow?.event_log)
    ? (shadow!.event_log as unknown[])
    : []
  return entries.map((e) => {
    const r = asRecord(e) || {}
    const at = String(r.at ?? "")
    const status = String(r.status ?? "")
    const st = asRecord(r.stage_timings) || {}
    const keys = Object.keys(st).filter(
      (k) => k !== "job_progress" && k !== "job_watch"
    )
    const parts = keys.slice(0, 4).map((k) => {
      const v = st[k]
      return `${k}=${typeof v === "object" ? JSON.stringify(v).slice(0, 40) : v}`
    })
    return {
      at,
      text: `status → ${status}${parts.length ? " · " + parts.join(", ") : ""}`,
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
      bandNote: grade?.storage_unverifiable
        ? "Unverifiable — both predicted and actual are below the measurement floor for approximate disk stats"
        : withinBand === true
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

/**
 * Risk level → semantic tone name used by the design system's --tone-*
 * tokens. Kept here (not in packages/ui) because the mapping is a domain
 * decision: low risk reads as "pass", high risk reads as "fail".
 */
export type SemanticTone = "pass" | "warn" | "fail" | "info" | "model" | "neutral"

export function riskSemanticTone(
  risk: string | null | undefined
): SemanticTone {
  const tone = riskTone(risk)
  if (tone === "low") return "pass"
  if (tone === "medium") return "warn"
  if (tone === "high") return "fail"
  return "neutral"
}

/** Shadow pass/warn/fail → semantic tone. */
export function shadowSemanticTone(
  outcome: string | null | undefined
): SemanticTone {
  if (outcome === "pass") return "pass"
  if (outcome === "warn") return "warn"
  if (outcome === "fail") return "fail"
  return "neutral"
}

/** First table-ish identifier in the SQL, for the "SQL / Table" column. */
export function primaryTableName(sql: string | null | undefined): string | null {
  if (!sql) return null
  const match =
    /\b(?:TABLE|FROM|JOIN|INTO|UPDATE|ON)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"?([a-zA-Z_][a-zA-Z0-9_]*)"?(?:\."?([a-zA-Z_][a-zA-Z0-9_]*)"?)?/i.exec(
      sql
    )
  if (!match) return null
  return (match[2] || match[1] || "").toLowerCase() || null
}

export type RunListItem = ReturnType<typeof mapRunListItem>

export type ShadowCheck = {
  id: string
  name: string
  detail: string
  state: "pass" | "warn" | "fail"
}

/**
 * Shadow evidence checks, derived only from what was actually measured.
 *
 * The design listed six named checks — lock escalation, deadlock detection,
 * replica lag, memory usage, replica id and shadow-run count. Four of those
 * have no source anywhere in this system and are not invented here. These are
 * the six that *are* real: execution outcome, rollback, timeout, and the
 * grader's per-dimension band checks for duration and storage, plus the
 * schema diff actually applied on the shadow cluster.
 *
 * Returns an empty list when no shadow execution has happened yet, so callers
 * can hide the panel rather than render six "unknown" rows.
 */
export function mapShadowChecks(extras: RunExtras): ShadowCheck[] {
  const { execution, grade, shadow } = extras
  if (!execution && !grade && !shadow) return []
  const checks: ShadowCheck[] = []

  if (execution) {
    checks.push({
      id: "execution",
      name: "Execution outcome",
      detail: execution.success
        ? "Migration applied cleanly on the shadow cluster."
        : `Migration failed on the shadow cluster${
            execution.error_message ? `: ${execution.error_message}` : "."
          }`,
      state: execution.success ? "pass" : "fail",
    })
    checks.push({
      id: "rollback",
      name: "Rollback safety",
      detail: execution.rollback_required
        ? "A rollback was required after execution."
        : "No rollback was required.",
      state: execution.rollback_required ? "fail" : "pass",
    })
    checks.push({
      id: "timeout",
      name: "Timeout",
      detail: execution.timed_out
        ? "Execution hit the shadow timeout before completing."
        : `Completed in ${formatDuration(execution.actual_duration_seconds)} without hitting the timeout.`,
      state: execution.timed_out ? "fail" : "pass",
    })
  }

  if (grade) {
    if (grade.duration_unverifiable) {
      checks.push({
        id: "duration_band",
        name: "Duration vs prediction",
        detail: "Duration could not be verified for this run.",
        state: "warn",
      })
    } else if (grade.duration_within_band != null) {
      checks.push({
        id: "duration_band",
        name: "Duration vs prediction",
        detail:
          grade.duration_pct_error == null
            ? grade.duration_within_band
              ? "Measured duration fell within the predicted band."
              : "Measured duration fell outside the predicted band."
            : `${Math.abs(Math.round(grade.duration_pct_error * 100))}% off the predicted duration — ${
                grade.duration_within_band ? "within" : "outside"
              } band.`,
        state: grade.duration_within_band ? "pass" : "warn",
      })
    }

    if (grade.storage_unverifiable) {
      checks.push({
        id: "storage_band",
        name: "Storage vs prediction",
        detail: "Storage growth could not be verified for this run.",
        state: "warn",
      })
    } else if (grade.storage_within_band != null) {
      checks.push({
        id: "storage_band",
        name: "Storage vs prediction",
        detail: `Measured ${formatStorage(extras.execution?.actual_storage_mb)} — ${
          grade.storage_within_band ? "within" : "outside"
        } the predicted band.`,
        state: grade.storage_within_band ? "pass" : "warn",
      })
    }
  }

  if (shadow) {
    const diff = asRecord(shadow.schema_diff)
    const changed = diff
      ? Object.values(diff).reduce<number>(
          (n, v) => n + (Array.isArray(v) ? v.length : 0),
          0
        )
      : 0
    checks.push({
      id: "schema_diff",
      name: "Schema change applied",
      detail:
        changed > 0
          ? `${changed} schema change${changed === 1 ? "" : "s"} observed between the before and after snapshots.`
          : "No schema difference was captured between the before and after snapshots.",
      state: changed > 0 ? "pass" : "warn",
    })
    if (shadow.error_message) {
      checks.push({
        id: "cluster",
        name: "Shadow cluster",
        detail: shadow.error_message,
        state: "fail",
      })
    }
  }

  return checks
}

export function mapRunListItem(item: MigrationRunSummary) {
  // Fields below the divider come from the widened summary response — the
  // run's approval / grade / execution-result / shadow-cluster children,
  // flattened server-side. They are null until the corresponding stage has
  // actually happened; nothing here is inferred or defaulted.
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
    migrationSql: item.migration_sql,
    tableName: primaryTableName(item.migration_sql),
    policyDecision: item.policy_decision,
    scaleTier: item.prediction_scale_tier,
    isTerminal: item.is_terminal,
    isFailed: item.status === "failed",
    isCancelledLook: item.status === "failed" && item.workflow_status === "aborted",
    // ---
    risk: item.compatibility_risk ?? null,
    riskTone: riskSemanticTone(item.compatibility_risk),
    confidence: item.confidence_score ?? null,
    confidencePercent:
      item.confidence_score == null
        ? null
        : Math.round(Number(item.confidence_score) * 100),
    approvalDecision: item.approval_decision ?? null,
    approverIdentity: item.approver_identity ?? null,
    approvedAt: item.approved_at ?? null,
    durationSeconds: item.actual_duration_seconds ?? null,
    durationLabel:
      item.actual_duration_seconds == null
        ? null
        : formatDuration(item.actual_duration_seconds),
    storageMb: item.actual_storage_mb ?? null,
    executionSuccess: item.execution_success ?? null,
    outcomeClass: item.outcome_class ?? null,
    scalarAccuracy: item.scalar_accuracy_score ?? null,
    isGraded: Boolean(item.is_graded),
    shadowOutcome: (item.shadow_outcome ?? null) as
      | "pass"
      | "warn"
      | "fail"
      | null,
    shadowStatus: item.shadow_status ?? null,
    shadowProvider: item.shadow_provider ?? null,
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
