"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"

import { ApiError } from "@/lib/api/client"
import {
  type ExecutionResult,
  type Grade,
  type Memory,
  type ModelTracesResponse,
  type MigrationRun,
  type ShadowCluster,
  getExecutionResult,
  getGrade,
  getMemory,
  getModelTraces,
  getRun,
  getShadowCluster,
} from "@/lib/api/endpoints"
import {
  formatDuration,
  formatRelativeTime,
  mapLifecycle,
  primaryTableName,
  statusLabel,
  type LifecycleStage,
} from "@/lib/api/map-run"
import { setCurrentRunId } from "@/lib/api/owner"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@workspace/ui/components/collapsible"
import { buttonVariants } from "@workspace/ui/components/button"
import {
  Label,
  Panel,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

import { SqlCodePanel } from "../current/sql-panel"
import { ShadowLiveView } from "@/components/shadow-live-view"
import { GradeRunAction } from "@/components/grade-run-action"
import {
  hasRealSfnArn,
  mapComparisons,
  syncWorkflow,
  usePolling,
  formatStageTiming,
} from "@/lib/api"

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return null
}

async function fetchOrNull<T>(fn: () => Promise<T>): Promise<T | null> {
  try {
    return await fn()
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null
    throw err
  }
}

function Section({
  title,
  children,
  className,
  action,
}: {
  title: string
  children: React.ReactNode
  className?: string
  action?: React.ReactNode
}) {
  return (
    <Panel
      aria-label={title}
      className={cn("flex w-full flex-col gap-4 px-6 py-5", className)}
    >
      <div className="flex items-center justify-between gap-3">
        <Label>{title}</Label>
        {action}
      </div>
      {children}
    </Panel>
  )
}

/**
 * A Section that starts closed. Used for the reference material at the bottom
 * of a run — grade detail, memory, model traces — which is worth keeping but
 * should not be the first thing competing for attention on the page.
 */
function CollapsedSection({
  title,
  summary,
  children,
}: {
  title: string
  summary?: React.ReactNode
  children: React.ReactNode
}) {
  const [open, setOpen] = React.useState(false)
  return (
    <Panel aria-label={title} className="flex w-full flex-col px-6 py-5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 text-left"
      >
        <span
          aria-hidden
          className={cn(
            "text-muted-foreground text-[10px] transition-transform duration-150",
            open ? "rotate-90" : "rotate-0"
          )}
        >
          ▶
        </span>
        <Label>{title}</Label>
        {summary ? (
          <span className="text-muted-foreground ml-auto text-[12px]">
            {summary}
          </span>
        ) : null}
      </button>
      {open ? <div className="mt-4">{children}</div> : null}
    </Panel>
  )
}

function Field({
  label,
  value,
  mono = true,
  tone,
}: {
  label: string
  value: React.ReactNode
  mono?: boolean
  tone?: "risk" | "verified" | "muted"
}) {
  return (
    <div className="space-y-0.5">
      <p className="section-label">{label}</p>
      <p
        className={cn(
          "text-[13px] tracking-tight",
          mono && "font-mono",
          tone === "risk" && "text-[var(--tone-fail-fg)]",
          tone === "verified" && "text-[var(--tone-pass-fg)]",
          tone === "muted" && "text-muted-foreground",
          !tone && "text-foreground font-medium"
        )}
      >
        {value}
      </p>
    </div>
  )
}

function stageDotClass(state: LifecycleStage["state"]): string {
  if (state === "complete") return "bg-[var(--tone-pass-dot)]"
  if (state === "current") return "bg-[var(--tone-info-dot)]"
  if (state === "failed") return "bg-[var(--tone-fail-dot)]"
  return "bg-border"
}

function stageTextClass(state: LifecycleStage["state"]): string {
  if (state === "complete") return "text-foreground"
  if (state === "current") return "text-[var(--tone-info-fg)]"
  if (state === "failed") return "text-[var(--tone-fail-fg)]"
  return "text-muted-foreground/45"
}

function LifecycleTimeline({ stages }: { stages: LifecycleStage[] }) {
  return (
    <ol className="space-y-0">
      {stages.map((stage, idx) => (
        <li key={stage.id} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span
              aria-hidden
              className={cn(
                "size-2.5 shrink-0 rounded-full border border-transparent",
                stageDotClass(stage.state)
              )}
            />
            {idx < stages.length - 1 ? (
              <span aria-hidden className="bg-border w-px flex-1" />
            ) : null}
          </div>
          <div className="min-w-0 flex-1 pb-4">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <span
                className={cn(
                  "font-mono text-xs tracking-[0.08em] uppercase",
                  stageTextClass(stage.state)
                )}
              >
                {stage.label}
              </span>
              <span className="text-muted-foreground/55 font-mono text-[10px] tracking-tight">
                {stage.at ? formatRelativeTime(stage.at) : null}
                {stage.durationLabel ? (
                  <>
                    {stage.at ? <span className="mx-1">·</span> : null}
                    {stage.durationLabel}
                  </>
                ) : null}
              </span>
            </div>
            {stage.error ? (
              <p className="text-[var(--oracle-risk)] mt-0.5 text-xs leading-relaxed">
                {stage.error}
              </p>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  )
}

function PreBlock({ text }: { text: string }) {
  return (
    <pre className="border-border/60 bg-muted/20 max-h-96 overflow-auto rounded-md border p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
      {text}
    </pre>
  )
}

function ExpandableText({
  label,
  text,
}: {
  label: string
  text: string
}) {
  const [open, setOpen] = React.useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger
        render={
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground font-mono text-[10px] tracking-[0.1em] uppercase transition-colors"
          />
        }
      >
        {open ? "Hide" : "Show"} {label} ({text.length} chars)
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-2">
          <PreBlock text={text} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

type TraceToolCall = {
  name?: unknown
  arguments?: unknown
  result_text?: unknown
  is_error?: unknown
}

type TraceAttempt = {
  raw_response?: unknown
  parsed?: unknown
  validation_error?: unknown
  latency_ms?: unknown
  input_tokens?: unknown
  output_tokens?: unknown
  repair?: unknown
  // Only present on tool-use traces (kind="blast_radius_investigation") —
  // the real MCP tool calls made during this turn, so a claim in the trace
  // can be checked against what the tool actually returned.
  tool_calls?: TraceToolCall[] | null
}

function ModelTraceBlock({
  kind,
  trace,
}: {
  kind: string
  trace: Record<string, unknown>
}) {
  const modelId = typeof trace.model_id === "string" ? trace.model_id : "—"
  const promptVersion =
    typeof trace.prompt_template_version === "string"
      ? trace.prompt_template_version
      : "—"
  const latencyTotal =
    trace.latency_ms_total == null ? null : Number(trace.latency_ms_total)
  const repairRetried = Boolean(trace.repair_retried)
  const systemPrompt =
    typeof trace.system_prompt === "string" ? trace.system_prompt : ""
  const userPrompt = typeof trace.user_prompt === "string" ? trace.user_prompt : ""
  const attempts = Array.isArray(trace.attempts)
    ? (trace.attempts as TraceAttempt[])
    : []
  const totalInputTokens = attempts.reduce(
    (sum, a) => sum + (typeof a.input_tokens === "number" ? a.input_tokens : 0),
    0
  )
  const totalOutputTokens = attempts.reduce(
    (sum, a) => sum + (typeof a.output_tokens === "number" ? a.output_tokens : 0),
    0
  )

  return (
    <div className="border-border/60 space-y-3 border-t pt-4 first:border-t-0 first:pt-0">
      <p className="text-foreground/85 font-mono text-xs tracking-[0.08em] uppercase">
        {kind}
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label="Model" value={modelId} />
        <Field label="Prompt version" value={promptVersion} />
        <Field
          label="Latency"
          value={
            latencyTotal != null ? `${latencyTotal.toFixed(0)} ms` : "—"
          }
        />
        <Field
          label="Tokens (in/out)"
          value={`${totalInputTokens} / ${totalOutputTokens}`}
        />
      </div>
      <Field
        label="Repair retried"
        value={repairRetried ? "yes" : "no"}
        tone={repairRetried ? "risk" : "muted"}
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {systemPrompt ? (
          <ExpandableText label="system prompt" text={systemPrompt} />
        ) : null}
        {userPrompt ? (
          <ExpandableText label="user prompt" text={userPrompt} />
        ) : null}
      </div>

      {attempts.length > 0 ? (
        <div className="space-y-2">
          <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
            Attempts ({attempts.length})
          </p>
          {attempts.map((attempt, idx) => (
            <div
              key={idx}
              className="border-border/50 space-y-2 rounded-md border p-3"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground/70 font-mono text-[10px] tracking-[0.1em] uppercase">
                  Attempt {idx + 1}
                  {attempt.repair ? " (repair)" : ""}
                </span>
                <span className="text-muted-foreground/55 font-mono text-[10px] tracking-tight">
                  {typeof attempt.latency_ms === "number"
                    ? `${attempt.latency_ms.toFixed(0)} ms`
                    : null}
                </span>
              </div>
              {attempt.validation_error ? (
                <p className="text-[var(--oracle-risk)] text-xs leading-relaxed">
                  {String(attempt.validation_error)}
                </p>
              ) : null}
              {typeof attempt.raw_response === "string" ? (
                <ExpandableText label="raw response" text={attempt.raw_response} />
              ) : null}
              {attempt.parsed != null ? (
                <ExpandableText
                  label="parsed"
                  text={JSON.stringify(attempt.parsed, null, 2)}
                />
              ) : null}
              {Array.isArray(attempt.tool_calls) && attempt.tool_calls.length > 0 ? (
                <div className="space-y-1.5">
                  <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.1em] uppercase">
                    Live tool calls ({attempt.tool_calls.length})
                  </p>
                  {attempt.tool_calls.map((call, callIdx) => (
                    <div
                      key={callIdx}
                      className="border-border/40 bg-muted/10 rounded border p-2"
                    >
                      <p className="font-mono text-[11px]">
                        <span
                          className={
                            call.is_error
                              ? "text-[var(--oracle-risk)]"
                              : "text-[var(--oracle-verified)]"
                          }
                        >
                          {String(call.name ?? "?")}
                        </span>
                        <span className="text-muted-foreground/60">
                          ({JSON.stringify(call.arguments ?? {})})
                        </span>
                      </p>
                      <p className="text-muted-foreground/70 mt-1 font-mono text-[10px] leading-relaxed break-all">
                        {String(call.result_text ?? "")}
                      </p>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export default function MigrationRunDetailPage() {
  const params = useParams<{ id: string }>()
  const runId = params.id

  const [run, setRun] = React.useState<MigrationRun | null>(null)
  const [grade, setGrade] = React.useState<Grade | null>(null)
  const [memory, setMemory] = React.useState<Memory | null>(null)
  const [shadow, setShadow] = React.useState<ShadowCluster | null>(null)
  const [execution, setExecution] = React.useState<ExecutionResult | null>(null)
  const [traces, setTraces] = React.useState<ModelTracesResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    if (!runId) return
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const runRes = await getRun(runId)
        if (cancelled) return
        setRun(runRes)
        const [gradeRes, memoryRes, shadowRes, execRes, tracesRes] =
          await Promise.all([
            fetchOrNull(() => getGrade(runId)),
            fetchOrNull(() => getMemory(runId)),
            fetchOrNull(() => getShadowCluster(runId)),
            fetchOrNull(() => getExecutionResult(runId)),
            fetchOrNull(() => getModelTraces(runId)),
          ])
        if (cancelled) return
        setGrade(gradeRes)
        setMemory(memoryRes)
        setShadow(shadowRes)
        setExecution(execRes)
        setTraces(tracesRes)
        setError(null)
      } catch (err) {
        if (cancelled) return
        setError(
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Failed to load migration run."
        )
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [runId])

  const isLiveShadow = Boolean(
    run &&
      hasRealSfnArn(run) &&
      (run.workflow_status === "running" || run.status === "running")
  )

  usePolling(
    async () => {
      if (!runId || !run) return
      const updated = await syncWorkflow(runId)
      setRun(updated)
      const [shadowRes, execRes, gradeRes] = await Promise.all([
        fetchOrNull(() => getShadowCluster(runId)),
        fetchOrNull(() => getExecutionResult(runId)),
        fetchOrNull(() => getGrade(runId)),
      ])
      if (shadowRes) setShadow(shadowRes)
      if (execRes) setExecution(execRes)
      if (gradeRes) setGrade(gradeRes)
    },
    {
      enabled: isLiveShadow,
      shouldStop: () =>
        run?.status === "completed" ||
        run?.status === "failed" ||
        run?.workflow_status === "succeeded" ||
        run?.workflow_status === "failed" ||
        run?.workflow_status === "timed_out" ||
        run?.workflow_status === "aborted",
    }
  )

  const stages = run
    ? mapLifecycle(run, { grade, memory, shadow, execution })
    : []
  const comparisons = run
    ? mapComparisons(run, { grade, memory, shadow, execution })
    : []
  const stageTimings = shadow ? asRecord(shadow.stage_timings) : null
  const jobWatchRows = Array.isArray(stageTimings?.job_watch)
    ? (stageTimings.job_watch as unknown[]).filter(
        (row): row is Record<string, unknown> =>
          Boolean(row) && typeof row === "object" && !Array.isArray(row)
      )
    : []
  // CockroachDB Changefeed events (docs/cockroach_hookup.md §Changefeeds) —
  // augments job_watch above with real row-level change events for
  // backfill-heavy migrations; empty for migration types (e.g. CREATE INDEX)
  // that don't rewrite the base table, which is expected, not an error.
  const changefeedEventRows = Array.isArray(stageTimings?.changefeed_events)
    ? (stageTimings.changefeed_events as unknown[]).filter(
        (row): row is Record<string, unknown> =>
          Boolean(row) && typeof row === "object" && !Array.isArray(row)
      )
    : []
  const changefeedTables = Array.isArray(stageTimings?.changefeed_tables)
    ? (stageTimings.changefeed_tables as unknown[]).map(String)
    : []
  const timingEntries = stageTimings
    ? Object.entries(stageTimings).filter(
        ([key]) =>
          key !== "job_watch" &&
          key !== "cockroachdb_tools" &&
          key !== "changefeed_events" &&
          key !== "changefeed_tables"
      )
    : []
  const predictionTrace = traces ? asRecord(traces.traces)?.prediction : null
  const recommendationTrace = traces
    ? asRecord(traces.traces)?.recommendation
    : null
  const investigationTrace = traces
    ? asRecord(traces.traces)?.blast_radius_investigation
    : null

  if (loading && !run) {
    return (
      <div className="flex flex-1 flex-col gap-5 px-4 pb-8 md:px-6 lg:px-10">
        <p className="text-muted-foreground text-sm">Loading migration run…</p>
      </div>
    )
  }

  if (error && !run) {
    return (
      <div className="flex flex-1 flex-col gap-5 px-4 pb-8 md:px-6 lg:px-10">
        <Link
          href="/dashboard/migrations/history"
          className="text-muted-foreground hover:text-foreground font-mono text-[11px] tracking-tight transition-colors"
        >
          ← Past Migrations
        </Link>
        <p className="text-[var(--oracle-risk)] text-sm leading-relaxed">
          {error}
        </p>
      </div>
    )
  }

  if (!run) return null

  const isFailed = run.status === "failed"

  return (
    <div className="flex flex-1 flex-col gap-5 px-4 pb-8 md:px-6 lg:px-10">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          href="/dashboard/migrations/history"
          className="text-muted-foreground hover:text-foreground -ml-2 font-mono text-[11px] tracking-tight transition-colors"
        >
          ← Past Migrations
        </Link>
        <Link
          href="/dashboard/migrations/current"
          onClick={() => setCurrentRunId(run.id)}
          className={cn(buttonVariants({ size: "sm" }))}
        >
          Set as current migration
        </Link>
      </div>

      <header className="space-y-2">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <h1 className="text-foreground text-2xl font-medium tracking-tight">
              Migration Run
            </h1>
          </div>
          <div className="flex flex-col items-start gap-1 sm:items-end">
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className={cn(
                  "size-1.5 shrink-0 rounded-full",
                  isFailed
                    ? "bg-[var(--oracle-risk)]"
                    : run.status === "completed"
                      ? "bg-[var(--oracle-verified)]"
                      : "bg-muted-foreground/60"
                )}
              />
              <span
                className={cn(
                  "font-mono text-[11px] tracking-[0.14em] uppercase",
                  isFailed
                    ? "text-[var(--oracle-risk)]"
                    : run.status === "completed"
                      ? "text-[var(--oracle-verified)]"
                      : "text-muted-foreground"
                )}
              >
                {statusLabel(run.status)}
              </span>
            </div>
            {run.status === "awaiting_approval" ? (
              <p className="text-muted-foreground/70 text-[11px]">
                Needs approval — open it as your current migration to continue.
              </p>
            ) : null}
          </div>
        </div>
      </header>

      <Section title="Migration SQL">
        <SqlCodePanel
          // The affected table, not `migration_<uuid8>.sql` — the run's UUID
          // told the reader nothing and was the same noise removed from the
          // header above.
          filename={primaryTableName(run.migration_sql) ?? "migration.sql"}
          sql={run.migration_sql}
        />
      </Section>

      <Section title="Lifecycle">
        <LifecycleTimeline stages={stages} />
      </Section>

      <Section title="Shadow Cluster">
        <ShadowLiveView
          run={run}
          extras={{ grade, memory, shadow, execution }}
          comparisons={comparisons}
          isLive={isLiveShadow}
        />
      </Section>



      {shadow && shadow.ccloud_audit_trail.length > 0 ? (
        <Section title="CockroachDB Cloud Audit Trail">
          <p className="text-muted-foreground mb-3 max-w-2xl text-sm leading-relaxed">
            Independent corroboration from the CockroachDB Cloud control
            plane's own audit log, fetched via the ccloud CLI — a separate
            source from the MCP investigation above, since it reflects what
            the Cloud API recorded happening to the cluster itself rather
            than what SQL observed inside it.
          </p>
          <ul className="divide-border/60 divide-y rounded-md border border-border/60">
            {shadow.ccloud_audit_trail.map((event, idx) => (
              <li
                key={idx}
                className="grid gap-1 px-3 py-2 font-mono text-[11px] tracking-tight sm:grid-cols-[10rem_1fr_8rem]"
              >
                <span className="text-muted-foreground/70">
                  {event.event_type}
                </span>
                <span className="text-foreground/85 truncate">
                  {event.actor || "—"}
                </span>
                <span className="text-muted-foreground/70 sm:text-right">
                  {event.occurred_at ? formatRelativeTime(event.occurred_at) : "—"}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {execution ? (
        <Section title="Execution Result">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Field
              label="Success"
              value={execution.success ? "yes" : "no"}
              tone={execution.success ? "verified" : "risk"}
            />
            <Field
              label="Duration"
              value={formatDuration(execution.actual_duration_seconds)}
            />
            <Field
              label="Storage"
              value={`${execution.actual_storage_mb.toFixed(1)} MB`}
            />
            <Field
              label="Rollback required"
              value={execution.rollback_required ? "yes" : "no"}
              tone={execution.rollback_required ? "risk" : "muted"}
            />
          </div>
          {execution.timed_out ? (
            <Field label="Timed out" value="yes" tone="risk" />
          ) : null}
          {execution.error_message ? (
            <p className="text-[var(--oracle-risk)] border-t border-border/60 pt-3 text-xs leading-relaxed">
              {execution.error_message}
            </p>
          ) : null}
        </Section>
      ) : null}

      {!grade ? (
        <Section title="Result">
          <GradeRunAction
            run={run}
            grade={grade}
            onGraded={(updated) => {
              setRun(updated)
              void fetchOrNull(() => getGrade(updated.id)).then((g) => {
                if (g) setGrade(g)
              })
            }}
          />
        </Section>
      ) : null}

      <CollapsedSection
        title="Grade"
        summary={grade ? grade.outcome_class : "not graded yet"}
      >
        {!grade ? (
          <p className="text-muted-foreground text-sm">
            No grade recorded for this run yet.
          </p>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Field label="Outcome" value={grade.outcome_class} />
              <Field
                label="Scalar accuracy"
                value={grade.scalar_accuracy_score.toFixed(3)}
              />
              <Field
                label="Adjusted confidence"
                value={grade.adjusted_confidence.toFixed(3)}
              />
              <Field
                label="High risk flags"
                value={grade.high_risk_flags_present ? "present" : "none"}
                tone={grade.high_risk_flags_present ? "risk" : "muted"}
              />
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Field
                label="Duration error"
                value={
                  grade.duration_unverifiable
                    ? "unverifiable"
                    : grade.duration_abs_error_seconds != null
                      ? `±${grade.duration_abs_error_seconds.toFixed(1)}s`
                      : "—"
                }
              />
              <Field
                label="Storage error"
                value={`±${grade.storage_abs_error_mb.toFixed(1)} MB`}
              />
              <Field
                label="Rollback predicted / actual"
                value={`${grade.rollback_predicted} / ${grade.rollback_actual_class}`}
              />
              <Field
                label="Rollback consistent"
                value={grade.rollback_consistent ? "yes" : "no"}
                tone={grade.rollback_consistent ? "verified" : "risk"}
              />
            </div>
            {grade.lessons_learned ? (
              <p className="text-foreground/80 border-t border-border/60 pt-3 text-sm leading-relaxed">
                {grade.lessons_learned}
              </p>
            ) : null}
          </div>
        )}
      </CollapsedSection>

      <CollapsedSection
        title="Memory"
        summary={memory ? "stored" : "none yet"}
      >
        {!memory ? (
          <p className="text-muted-foreground text-sm">
            No memory was written for this run yet.
          </p>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Field label="Owner" value={memory.owner_identity} />
              <Field label="Scale tier" value={memory.scale_tier} />
              <Field label="Migration type" value={memory.migration_type} />
              <Field
                label="Embedding"
                value={memory.embedding_status}
                tone={
                  memory.embedding_status === "ready"
                    ? "verified"
                    : memory.embedding_status === "failed"
                      ? "risk"
                      : "muted"
                }
              />
            </div>
            {memory.embedding_error ? (
              <p className="text-[var(--oracle-risk)] text-xs leading-relaxed">
                {memory.embedding_error}
              </p>
            ) : null}
            <p className="text-foreground/80 text-sm leading-relaxed">
              {memory.migration_summary}
            </p>
            {memory.not_a_graded_run ? (
              <span className="border-border text-muted-foreground inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] uppercase">
                Open-source corpus (not a graded run)
              </span>
            ) : null}
            <div className="border-border/60 space-y-1.5 border-t pt-3">
              <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
                Embed text (verbatim)
              </p>
              <PreBlock text={memory.embed_text} />
            </div>
          </div>
        )}
      </CollapsedSection>

      <CollapsedSection title="Model Traces">
        {!predictionTrace && !recommendationTrace && !investigationTrace ? (
          <p className="text-muted-foreground text-sm">
            No Bedrock model traces recorded for this run.
          </p>
        ) : (
          <div className="space-y-4">
            {predictionTrace ? (
              <ModelTraceBlock
                kind="Prediction"
                trace={asRecord(predictionTrace) ?? {}}
              />
            ) : null}
            {recommendationTrace ? (
              <ModelTraceBlock
                kind="Recommendation"
                trace={asRecord(recommendationTrace) ?? {}}
              />
            ) : null}
            {investigationTrace ? (
              <ModelTraceBlock
                kind="Blast-radius investigation (live CockroachDB MCP)"
                trace={asRecord(investigationTrace) ?? {}}
              />
            ) : null}
          </div>
        )}
      </CollapsedSection>
    </div>
  )
}
