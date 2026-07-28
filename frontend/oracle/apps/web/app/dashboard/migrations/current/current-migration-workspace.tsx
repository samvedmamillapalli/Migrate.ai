"use client"

import * as React from "react"
import Link from "next/link"

import { Button, buttonVariants } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { cn } from "@workspace/ui/lib/utils"

import { OwnerIdentityField } from "@/components/owner-identity-field"
import { ShadowLiveView } from "@/components/shadow-live-view"
import { useShadowWatch } from "@/components/shadow-watch-context"
import {
  ApiError,
  abortWorkflow,
  approveRun,
  clampProse,
  createFakeMigration,
  createDemoWithDb,
  createRun,
  discoverErrorHint,
  discoverSchema,
  formatDuration,
  formatPercent,
  formatRelativeTime,
  formatStorage,
  getApproval,
  getConnectionSecretArn,
  getCurrentRunId,
  getExecutionResult,
  getGrade,
  getHealth,
  getMemory,
  getOwnerIdentity,
  getPipelineProgress,
  getRun,
  getShadowCluster,
  hasRealSfnArn,
  isSfnReady,
  sfnNotReadyMessage,
  mapAssessment,
  mapComparisons,
  mapProcessStages,
  mapSchema,
  policyLabel,
  predictRun,
  requireOwnerIdentity,
  riskTone,
  setConnectionSecretArn,
  setCurrentRunId,
  sqlFilename,
  startWorkflow,
  statusLabel,
  syncWorkflow,
  usePolling,
  type ApprovalDecision,
  type ApprovalResponse,
  type AssessmentView,
  type ComparisonRow,
  type ExecutionResult,
  type Grade,
  type HealthResponse,
  type Memory,
  type MigrationRun,
  type PipelineProgress,
  type RetrievedMemoryView,
  type RunExtras,
  type SchemaView,
  type ShadowCluster,
} from "@/lib/api"

import { SqlCodePanel } from "./sql-panel"

const EMPTY_EXTRAS: RunExtras = {
  grade: null,
  memory: null,
  shadow: null,
  execution: null,
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return "Something went wrong."
}

async function safeGet<T>(fn: () => Promise<T>): Promise<T | null> {
  try {
    return await fn()
  } catch {
    return null
  }
}

function extrasReady(status: MigrationRun["status"]): boolean {
  return status === "running" || status === "completed" || status === "failed"
}

/**
 * Heuristic, client-side only: pull table-like identifiers out of the
 * migration SQL text following TABLE/FROM/JOIN/INTO/UPDATE, and flag any that
 * don't match a discovered table name. Not a real SQL parser — the backend's
 * `missing_referenced_table` policy flag is the authoritative check, this is
 * just an earlier, cheaper warning next to the editor before a full run.
 */
function findUnknownTableReferences(
  sql: string,
  knownTables: string[]
): string[] {
  if (!sql.trim() || knownTables.length === 0) return []
  const known = new Set(knownTables.map((t) => t.toLowerCase()))
  const pattern =
    /\b(?:TABLE|FROM|JOIN|INTO|UPDATE)\s+(?:IF\s+EXISTS\s+|IF\s+NOT\s+EXISTS\s+)?"?([a-zA-Z_][a-zA-Z0-9_]*)"?(?:\."?([a-zA-Z_][a-zA-Z0-9_]*)"?)?/gi
  const found = new Set<string>()
  let match: RegExpExecArray | null
  while ((match = pattern.exec(sql)) !== null) {
    const name = (match[2] || match[1] || "").toLowerCase()
    if (name) found.add(name)
  }
  return Array.from(found).filter((name) => !known.has(name))
}

function Section({
  title,
  children,
  className,
  right,
}: {
  title: string
  children: React.ReactNode
  className?: string
  right?: React.ReactNode
}) {
  return (
    <section
      aria-label={title}
      className={cn(
        "border-border flex w-full flex-col gap-4 rounded-lg border p-4",
        className
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-muted-foreground text-[11px] font-medium tracking-[0.16em] uppercase">
          {title}
        </h2>
        {right}
      </div>
      {children}
    </section>
  )
}

function FieldRow({
  label,
  value,
  valueClassName,
}: {
  label: string
  value: React.ReactNode
  valueClassName?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-muted-foreground/65 font-mono text-[10px] tracking-[0.08em]">
        {label}
      </dt>
      <dd
        className={cn(
          "text-foreground/85 font-mono text-xs tracking-tight tabular-nums",
          valueClassName
        )}
      >
        {value}
      </dd>
    </div>
  )
}

function riskClass(tone: "low" | "medium" | "high" | "unknown"): string {
  if (tone === "low") return "text-[var(--oracle-verified)]"
  if (tone === "medium") return "text-amber-400/90"
  if (tone === "high") return "text-[var(--oracle-risk)]"
  return "text-muted-foreground"
}

function StatusDot({ tone }: { tone: "ok" | "warn" | "bad" | "muted" }) {
  return (
    <span
      aria-hidden
      className={cn(
        "size-1.5 shrink-0 rounded-full",
        tone === "ok" && "bg-[var(--oracle-verified)]",
        tone === "warn" && "bg-amber-400/90",
        tone === "bad" && "bg-[var(--oracle-risk)]",
        tone === "muted" && "bg-muted-foreground/60"
      )}
    />
  )
}

function statusTone(status: string | null | undefined): "ok" | "warn" | "bad" | "muted" {
  if (status === "completed") return "ok"
  if (status === "failed") return "bad"
  if (status === "awaiting_approval" || status === "predicting") return "warn"
  return "muted"
}

/** Process stage tracker — mirrors the create → predict → approve → shadow → grade → remember order. */
function ProcessStages({ run }: { run: MigrationRun }) {
  const stages = mapProcessStages(run)
  return (
    <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
      {stages.map((stage, index) => (
        <li key={stage.id} className="flex items-center gap-1.5">
          {index > 0 ? (
            <span className="text-muted-foreground/35 font-mono text-[10px]">
              →
            </span>
          ) : null}
          <span
            className={cn(
              "font-mono text-[10px] tracking-[0.08em] uppercase",
              stage.state === "complete" && "text-muted-foreground/65",
              stage.state === "current" && "text-foreground",
              stage.state === "failed" && "text-[var(--oracle-risk)]",
              stage.state === "pending" && "text-muted-foreground/35"
            )}
          >
            {stage.label}
          </span>
        </li>
      ))}
    </ol>
  )
}

function SchemaTables({ schema }: { schema: SchemaView }) {
  if (schema.tables.length === 0) {
    return (
      <p className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
        {schema.status === "succeeded"
          ? "Discovery succeeded but returned no table snapshot."
          : "No tables discovered yet."}
      </p>
    )
  }
  return (
    <div className="space-y-3">
      {schema.tables.map((table) => (
        <div
          key={table.name}
          className="border-border/50 rounded-md border p-3"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-foreground/90 font-mono text-xs tracking-tight">
              {table.name}
            </p>
            <p className="text-muted-foreground/70 font-mono text-[10px] tracking-tight">
              {table.estimatedRowCount != null
                ? `${table.estimatedRowCount.toLocaleString()} rows`
                : "row count unknown"}
              <span className="text-muted-foreground/35 mx-1.5">·</span>
              {table.approximateSize ?? "size unknown"}
            </p>
          </div>
          {table.columns.length > 0 ? (
            <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] tracking-tight text-muted-foreground/80">
              {table.columns.map((col) => (
                <li key={col.name}>
                  {col.name}
                  <span className="text-muted-foreground/40">:{col.type}</span>
                </li>
              ))}
            </ul>
          ) : null}
          {table.indexes.length > 0 ? (
            <p className="mt-1.5 font-mono text-[10px] tracking-tight text-muted-foreground/55">
              indexes: {table.indexes.join(", ")}
            </p>
          ) : null}
        </div>
      ))}
    </div>
  )
}

const GRANT_HELP_SQL = `-- 1. Create a dedicated read-only user
CREATE USER migration_oracle_ro WITH PASSWORD '<choose-a-password>';

-- 2. Grant SELECT only, on the schema your migration references
GRANT SELECT ON TABLE <schema>.<table> TO migration_oracle_ro;
-- or, for every table in a schema:
-- GRANT SELECT ON ALL TABLES IN SCHEMA <schema> TO migration_oracle_ro;

-- 3. Explicitly deny writes and DDL (defense in depth)
REVOKE INSERT, UPDATE, DELETE ON TABLE <schema>.<table> FROM migration_oracle_ro;
REVOKE CREATE ON DATABASE <database> FROM migration_oracle_ro;`

/**
 * Shared connect-a-database UI: one primary input (read-only URL), a secondary
 * stored-secret option behind a toggle (not a second equal-weight field), and
 * a copyable GRANT/REVOKE block so creating the read-only credential is a
 * solved problem instead of an unexplained prerequisite. Used both before a
 * run exists (connect-first empty state) and in the post-create attach step.
 */
function ConnectDatabaseFields({
  databaseUrl,
  onDatabaseUrlChange,
  connectionSecretArn,
  onConnectionSecretArnChange,
  showArnField,
  onToggleArnField,
  showGrantHelp,
  onToggleGrantHelp,
  grantCopied,
  onCopyGrant,
  onSubmit,
  submitting,
  submitLabel,
  hideSubmit,
  showDemoButton,
  onDemo,
  demoDisabled,
}: {
  databaseUrl: string
  onDatabaseUrlChange: (value: string) => void
  connectionSecretArn: string
  onConnectionSecretArnChange: (value: string) => void
  showArnField: boolean
  onToggleArnField: () => void
  showGrantHelp: boolean
  onToggleGrantHelp: () => void
  grantCopied: boolean
  onCopyGrant: () => void
  onSubmit: () => void
  submitting: boolean
  submitLabel: string
  /** No run exists yet to discover against — connect fields just capture
   * state for "Create run" below to use, there's nothing to submit here. */
  hideSubmit?: boolean
  showDemoButton: boolean
  onDemo?: () => void
  demoDisabled?: boolean
}) {
  return (
    <div className="space-y-4">
      {showDemoButton ? (
        <div className="border-border/60 bg-muted/20 flex flex-wrap items-center justify-between gap-3 rounded-md border p-3">
          <div className="space-y-0.5">
            <p className="font-mono text-[10px] tracking-[0.12em] text-foreground/85 uppercase">
              No database of your own?
            </p>
            <p className="text-muted-foreground/80 text-xs leading-relaxed">
              Connect a prepared demo database instead —{" "}
              <span className="text-amber-400/90">not your data</span>, always
              available, real read-only discovery.
            </p>
          </div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={demoDisabled}
            onClick={onDemo}
          >
            {demoDisabled ? "Connecting…" : "Try the demo database"}
          </Button>
        </div>
      ) : null}

      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          onSubmit()
        }}
      >
        <div className="space-y-1.5">
          <label
            htmlFor="database-url"
            className="text-muted-foreground font-mono text-[10px] tracking-[0.12em] uppercase"
          >
            Read-only database URL
          </label>
          <Input
            id="database-url"
            type="text"
            value={databaseUrl}
            onChange={(e) => onDatabaseUrlChange(e.target.value)}
            placeholder="postgresql://readonly@host:26257/mydb?sslmode=verify-full"
            className="text-muted-foreground/60 font-mono text-xs italic placeholder:not-italic placeholder:opacity-60"
            autoComplete="off"
            spellCheck={false}
          />
          <p className="text-muted-foreground/55 text-[10px] leading-snug">
            Example format — paste your own read-only connection string, not
            this one.
          </p>
        </div>

        <button
          type="button"
          className="text-muted-foreground hover:text-foreground w-fit font-mono text-[10px] tracking-[0.1em] uppercase underline-offset-2 hover:underline"
          onClick={onToggleArnField}
        >
          {showArnField
            ? "Hide stored-secret option"
            : "Have a credential already in AWS Secrets Manager? →"}
        </button>
        {showArnField ? (
          <div className="space-y-1.5">
            <label
              htmlFor="connection-secret-arn"
              className="text-muted-foreground font-mono text-[10px] tracking-[0.12em] uppercase"
            >
              Secrets Manager ARN
            </label>
            <Input
              id="connection-secret-arn"
              value={connectionSecretArn}
              onChange={(e) => onConnectionSecretArnChange(e.target.value)}
              placeholder="arn:aws:secretsmanager:… (JSON with database_url)"
              className="text-muted-foreground/60 font-mono text-xs italic placeholder:not-italic placeholder:opacity-60"
            />
          </div>
        ) : null}

        {hideSubmit ? (
          <p className="text-muted-foreground/60 font-mono text-[10px] tracking-tight">
            {submitLabel}
          </p>
        ) : (
          <Button type="submit" disabled={submitting} className="w-fit">
            {submitLabel}
          </Button>
        )}
      </form>

      <div className="border-border/40 rounded-md border border-dashed p-3">
        <button
          type="button"
          className="text-muted-foreground hover:text-foreground w-full text-left font-mono text-[10px] tracking-[0.12em] uppercase"
          onClick={onToggleGrantHelp}
        >
          {showGrantHelp ? "▾" : "▸"} How do I create a read-only user?
        </button>
        {showGrantHelp ? (
          <div className="mt-2 space-y-2">
            <pre className="border-border/50 bg-muted/30 max-h-56 overflow-auto rounded-md border p-2.5 font-mono text-[10px] leading-relaxed whitespace-pre-wrap">
              {GRANT_HELP_SQL}
            </pre>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onCopyGrant}
            >
              {grantCopied ? "Copied" : "Copy GRANT statements"}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function Disclosure({
  label,
  openLabel,
  defaultOpen = false,
  children,
}: {
  label: string
  openLabel?: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = React.useState(defaultOpen)
  return (
    <div>
      <button
        type="button"
        className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 font-mono text-[10px] tracking-[0.12em] uppercase transition-colors"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span
          className={cn(
            "inline-block transition-transform",
            open && "rotate-90"
          )}
          aria-hidden
        >
          ▸
        </span>
        {open ? openLabel || label : label}
      </button>
      {open ? <div className="mt-2.5">{children}</div> : null}
    </div>
  )
}

function RiskFlags({ flags }: { flags: AssessmentView["riskFlags"] }) {
  if (flags.length === 0) {
    return (
      <p className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
        No risk flags raised.
      </p>
    )
  }
  return (
    <ul className="space-y-1.5">
      {flags.map((flag, idx) => (
        <li
          key={`${flag.ruleId}-${idx}`}
          className="flex gap-2 text-sm leading-relaxed text-foreground/80"
        >
          <span
            className={cn(
              "shrink-0 font-mono text-[10px] uppercase",
              riskClass(riskTone(flag.severity))
            )}
          >
            {flag.severity || "—"}
          </span>
          <span>
            <span className="font-mono text-[11px] text-muted-foreground/70">
              {flag.ruleId}
            </span>{" "}
            {flag.explanation}
          </span>
        </li>
      ))}
    </ul>
  )
}

function MemoryCard({ memory }: { memory: RetrievedMemoryView }) {
  const weak = memory.similarityScore == null
  return (
    <div className="border-border/50 space-y-1.5 rounded-md border p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-foreground/85 font-mono text-xs tracking-tight">
          #{memory.rank}{" "}
          {memory.migrationRunId
            ? `run ${memory.migrationRunId.slice(0, 8)}`
            : "—"}
          {memory.memoryId ? (
            <span className="text-muted-foreground/55">
              {" "}
              · mem {memory.memoryId.slice(0, 8)}
            </span>
          ) : null}
        </p>
        <p className="text-muted-foreground/70 font-mono text-[10px] tracking-tight">
          {weak ? "similarity unavailable" : `similarity ${formatPercent(memory.similarityScore)}`}
          {memory.scaleTier ? (
            <>
              <span className="text-muted-foreground/35 mx-1.5">·</span>
              {memory.scaleTier}
            </>
          ) : null}
          {memory.notAGradedRun ? (
            <>
              <span className="text-muted-foreground/35 mx-1.5">·</span>
              <span className="text-amber-400/80">corpus (not graded)</span>
            </>
          ) : (
            <>
              <span className="text-muted-foreground/35 mx-1.5">·</span>
              <span className="text-emerald-400/75">graded outcome</span>
            </>
          )}
        </p>
      </div>
      {memory.migrationSummary ? (
        <p className="text-foreground/80 text-sm leading-relaxed">
          {memory.migrationSummary}
        </p>
      ) : null}
      {memory.lessonsLearned ? (
        <p className="text-muted-foreground text-xs leading-relaxed">
          <span className="text-muted-foreground/60 font-mono text-[10px] uppercase">
            Lessons:{" "}
          </span>
          {memory.lessonsLearned}
        </p>
      ) : null}
      {memory.surpriseNotes ? (
        <p className="text-muted-foreground text-xs leading-relaxed">
          <span className="text-muted-foreground/60 font-mono text-[10px] uppercase">
            Surprises:{" "}
          </span>
          {memory.surpriseNotes}
        </p>
      ) : null}
      {memory.sourceUrl ? (
        <a
          href={memory.sourceUrl}
          target="_blank"
          rel="noreferrer"
          className="text-muted-foreground hover:text-foreground block font-mono text-[10px] tracking-tight underline-offset-2 hover:underline"
        >
          {memory.uiLabel || memory.sourceUrl}
        </a>
      ) : null}
    </div>
  )
}

function RetrievalPanel({
  assessment,
}: {
  assessment: AssessmentView
}) {
  const { retrieval } = assessment
  const [open, setOpen] = React.useState(false)
  const summary =
    retrieval.emptyVsNeverAttempted === "never_attempted"
      ? "Learning not run yet"
      : retrieval.emptyVsNeverAttempted === "empty"
        ? "No similar past runs yet"
        : retrieval.emptyVsNeverAttempted === "hits"
          ? `Learning from ${retrieval.retrievedCount} similar run${retrieval.retrievedCount === 1 ? "" : "s"}`
          : "Learning status unknown"

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <StatusDot
          tone={
            retrieval.emptyVsNeverAttempted === "hits"
              ? retrieval.weakRetrieval
                ? "warn"
                : "ok"
              : retrieval.emptyVsNeverAttempted === "empty"
                ? "warn"
                : "muted"
          }
        />
        <p className="text-sm text-foreground/85">{summary}</p>
        {retrieval.memories.length > 0 ? (
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground font-mono text-[10px] tracking-[0.1em] uppercase transition-colors"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide" : "View"}
          </button>
        ) : null}
      </div>
      {open && retrieval.memories.length > 0 ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {retrieval.memories.map((mem) => (
            <MemoryCard key={mem.rank} memory={mem} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function AssessmentPanel({ assessment }: { assessment: AssessmentView }) {
  const { prediction, confidence, recommendation } = assessment
  const [detailsOpen, setDetailsOpen] = React.useState(false)
  // Defensive: the model is asked for 3-4 plain sentences with no markdown,
  // but doesn't always comply — clamp what's always visible regardless, and
  // surface anything past that under "Show details" instead of an essay.
  const riskClamp = clampProse(prediction?.riskExplanation)
  const rationaleClamp = clampProse(recommendation?.rationale)
  const hasDetails =
    Boolean(prediction?.keyAssumptions.length) ||
    Boolean(prediction?.uncertaintyNotes.length) ||
    Boolean(prediction?.framingNote) ||
    Boolean(recommendation?.rolloutSteps.length) ||
    Boolean(recommendation?.monitoringChecklist.length) ||
    Boolean(recommendation?.rollbackGuidance) ||
    Boolean(recommendation?.saferAlternativePlan) ||
    Boolean(confidence?.wasReduced) ||
    Boolean(riskClamp.overflow) ||
    Boolean(rationaleClamp.overflow) ||
    assessment.riskFlags.length > 0

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-0.5">
          <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
            Policy
          </p>
          <p className="font-mono text-xs tracking-[0.08em] text-amber-400/90 uppercase">
            {policyLabel(assessment.policyDecision)}
          </p>
        </div>
        <div className="space-y-0.5">
          <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
            Risk
          </p>
          <p
            className={cn(
              "font-mono text-xs tracking-[0.08em] uppercase",
              riskClass(riskTone(assessment.compatibilityRisk))
            )}
          >
            {assessment.compatibilityRisk || "—"}
          </p>
        </div>
        {confidence ? (
          <div className="space-y-0.5">
            <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
              Confidence
            </p>
            <p className="font-mono text-lg leading-none tracking-tight text-[var(--oracle-reasoning-soft)]">
              {confidence.percentLabel}
            </p>
            {confidence.wasReduced ? (
              <p className="text-muted-foreground/60 font-mono text-[10px] tracking-tight">
                model proposed {confidence.rawPercentLabel}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      {confidence?.wasReduced ? (
        <div className="max-w-md space-y-1">
          <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
            Why confidence was clamped
          </p>
          <ul className="space-y-1">
            {confidence.adjustments.map((adj, idx) => (
              <li
                key={`${adj.reasonCode}-${idx}`}
                className="flex gap-2 text-xs text-foreground/75"
              >
                <span className="text-amber-400/80 shrink-0 font-mono tabular-nums">
                  {adj.amount > 0 ? "+" : ""}
                  {adj.amount}
                </span>
                <span>{adj.reason || adj.reasonCode}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {prediction ? (
        <dl className="max-w-md space-y-1.5">
          <FieldRow
            label="Duration"
            value={formatDuration(prediction.estimatedDurationSeconds)}
          />
          <FieldRow
            label="Storage"
            value={formatStorage(prediction.estimatedStorageMb)}
          />
          <FieldRow
            label="Rollback"
            value={prediction.rollbackRisk || "—"}
            valueClassName={riskClass(riskTone(prediction.rollbackRisk))}
          />
        </dl>
      ) : null}

      {riskClamp.visible ? (
        <p className="text-foreground/80 max-w-2xl text-sm leading-relaxed">
          {riskClamp.visible}
        </p>
      ) : null}

      {recommendation?.strategy ? (
        <div className="space-y-1">
          <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
            Recommendation
          </p>
          <p className="text-sm font-medium tracking-tight text-foreground/90">
            {recommendation.strategy}
          </p>
          {rationaleClamp.visible ? (
            <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
              {rationaleClamp.visible}
            </p>
          ) : null}
        </div>
      ) : null}

      {hasDetails ? (
        <div>
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground font-mono text-[10px] tracking-[0.1em] uppercase transition-colors"
            onClick={() => setDetailsOpen((v) => !v)}
          >
            {detailsOpen ? "Hide details" : "Show details"}
          </button>
          {detailsOpen ? (
            <div className="border-border/50 mt-3 space-y-4 border-t pt-3">
              {riskClamp.overflow ? (
                <div>
                  <p className="text-muted-foreground/55 mb-1 font-mono text-[10px] tracking-[0.1em] uppercase">
                    More on the risk assessment
                  </p>
                  <p className="text-foreground/75 max-w-2xl text-sm leading-relaxed">
                    {riskClamp.overflow}
                  </p>
                </div>
              ) : null}
              {rationaleClamp.overflow ? (
                <div>
                  <p className="text-muted-foreground/55 mb-1 font-mono text-[10px] tracking-[0.1em] uppercase">
                    More on the recommendation
                  </p>
                  <p className="text-foreground/75 max-w-2xl text-sm leading-relaxed">
                    {rationaleClamp.overflow}
                  </p>
                </div>
              ) : null}
              {assessment.riskFlags.length > 0 ? (
                <div>
                  <p className="text-muted-foreground/55 mb-1 font-mono text-[10px] tracking-[0.1em] uppercase">
                    Risk flags
                  </p>
                  <RiskFlags flags={assessment.riskFlags} />
                </div>
              ) : null}
              {prediction?.keyAssumptions.length ? (
                <div>
                  <p className="text-muted-foreground/55 mb-1 font-mono text-[10px] tracking-[0.1em] uppercase">
                    Assumptions
                  </p>
                  <ul className="space-y-1">
                    {prediction.keyAssumptions.map((item) => (
                      <li
                        key={item}
                        className="flex gap-2 text-xs text-foreground/75"
                      >
                        <span className="text-muted-foreground/50 shrink-0">·</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {prediction?.uncertaintyNotes.length ? (
                <div>
                  <p className="text-muted-foreground/55 mb-1 font-mono text-[10px] tracking-[0.1em] uppercase">
                    Uncertainty
                  </p>
                  <ul className="space-y-1">
                    {prediction.uncertaintyNotes.map((item) => (
                      <li
                        key={item}
                        className="flex gap-2 text-xs text-foreground/75"
                      >
                        <span className="text-muted-foreground/50 shrink-0">·</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {recommendation?.rolloutSteps.length ? (
                <ol className="space-y-1.5">
                  {recommendation.rolloutSteps.map((step, idx) => (
                    <li
                      key={idx}
                      className="flex gap-2 text-sm leading-relaxed text-foreground/80"
                    >
                      <span className="text-muted-foreground/50 shrink-0 font-mono tabular-nums">
                        {idx + 1}.
                      </span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
              ) : null}
              {recommendation?.monitoringChecklist.length ? (
                <ul className="space-y-1">
                  {recommendation.monitoringChecklist.map((item) => (
                    <li
                      key={item}
                      className="flex gap-2 text-xs text-foreground/75"
                    >
                      <span className="text-muted-foreground/50 shrink-0">·</span>
                      {item}
                    </li>
                  ))}
                </ul>
              ) : null}
              {prediction?.framingNote ? (
                <p className="text-muted-foreground text-xs leading-relaxed">
                  {prediction.framingNote}
                </p>
              ) : null}
              {recommendation?.rollbackGuidance ? (
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {recommendation.rollbackGuidance}
                </p>
              ) : null}
              {recommendation?.saferAlternativePlan ? (
                <p className="text-muted-foreground text-sm leading-relaxed">
                  {recommendation.saferAlternativePlan}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function ComparisonsPanel({ rows }: { rows: ComparisonRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
        No prediction-vs-actual comparisons yet.
      </p>
    )
  }
  const allWithin =
    rows.every((r) => r.withinBand === true) &&
    rows.some((r) => r.withinBand === true)
  return (
    <div className="space-y-3">
      {allWithin ? (
        <p className="text-xs text-[var(--oracle-verified)]/90">
          All metrics within band.
        </p>
      ) : null}
      <dl className="space-y-2.5">
        {rows.map((row) => (
          <div
            key={row.label}
            className="grid gap-1 border-b border-border/40 pb-2.5 last:border-b-0 last:pb-0 sm:grid-cols-[7rem_1fr_auto] sm:items-baseline sm:gap-4"
          >
            <dt className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
              {row.label}
            </dt>
            <dd className="space-y-0.5">
              <p className="text-foreground/85 font-mono text-xs tracking-tight">
                {row.predicted}
                <span className="text-muted-foreground/40 mx-1.5">→</span>
                {row.actual}
              </p>
              {row.bandNote ? (
                <p className="text-muted-foreground/70 text-[11px] leading-snug">
                  {row.bandNote}
                </p>
              ) : null}
            </dd>
            {row.delta || row.withinBand != null ? (
              <span
                className={cn(
                  "font-mono text-[11px] tracking-tight sm:text-right",
                  row.withinBand === true && "text-[var(--oracle-verified)]",
                  row.withinBand === false && "text-[var(--oracle-risk)]",
                  row.withinBand == null && "text-muted-foreground"
                )}
              >
                {row.delta ? `${row.delta} · ` : ""}
                {row.withinBand === true
                  ? "within band"
                  : row.withinBand === false
                    ? "outside band"
                    : ""}
              </span>
            ) : null}
          </div>
        ))}
      </dl>
    </div>
  )
}

export function CurrentMigrationWorkspace() {
  const { openWatch } = useShadowWatch()
  const [initializing, setInitializing] = React.useState(true)
  const [run, setRun] = React.useState<MigrationRun | null>(null)
  const [extras, setExtras] = React.useState<RunExtras>(EMPTY_EXTRAS)
  const [health, setHealth] = React.useState<HealthResponse | null>(null)

  const [sqlDraft, setSqlDraft] = React.useState("")
  const [connectionSecretArn, setConnectionSecretArnState] = React.useState("")
  const [databaseUrl, setDatabaseUrl] = React.useState("")
  const [overrideRationale, setOverrideRationale] = React.useState("")
  const [recordedApproval, setRecordedApproval] =
    React.useState<ApprovalResponse | null>(null)

  const [creating, setCreating] = React.useState(false)
  const [discovering, setDiscovering] = React.useState(false)
  const [predicting, setPredicting] = React.useState(false)
  const [approving, setApproving] = React.useState<ApprovalDecision | null>(null)
  const [startingShadow, setStartingShadow] = React.useState(false)
  const [abortingShadow, setAbortingShadow] = React.useState(false)

  const [statusMessage, setStatusMessage] = React.useState(
    "Waiting for a migration…"
  )
  const [progress, setProgress] = React.useState<PipelineProgress | null>(null)
  const [discoverProgress, setDiscoverProgress] =
    React.useState<PipelineProgress | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [discoverError, setDiscoverError] = React.useState<string | null>(null)
  const [showArnField, setShowArnField] = React.useState(false)
  const [showGrantHelp, setShowGrantHelp] = React.useState(false)
  const [grantCopied, setGrantCopied] = React.useState(false)

  const refreshHealth = React.useCallback(async () => {
    try {
      const h = await getHealth()
      setHealth(h)
    } catch {
      setHealth(null)
    }
  }, [])

  const refreshExtras = React.useCallback(async (target: MigrationRun) => {
    if (!extrasReady(target.status)) {
      setExtras(EMPTY_EXTRAS)
      return
    }
    const [grade, memory, execution, shadow] = await Promise.all([
      safeGet(() => getGrade(target.id)),
      safeGet(() => getMemory(target.id)),
      safeGet(() => getExecutionResult(target.id)),
      safeGet(() => getShadowCluster(target.id)),
    ])
    setExtras({ grade, memory, execution, shadow })
  }, [])

  const loadRunAndExtras = React.useCallback(
    async (runId: string) => {
      setInitializing(true)
      try {
        const r = await getRun(runId)
        setRun(r)
        await refreshExtras(r)
        const approval = await safeGet(() => getApproval(r.id))
        setRecordedApproval(approval)
        if (approval?.override_rationale) {
          setOverrideRationale(approval.override_rationale)
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          setCurrentRunId(null)
          setRun(null)
          setExtras(EMPTY_EXTRAS)
          setRecordedApproval(null)
        } else {
          setError(errorMessage(err))
        }
      } finally {
        setInitializing(false)
      }
    },
    [refreshExtras]
  )

  React.useEffect(() => {
    setConnectionSecretArnState(getConnectionSecretArn())
    void refreshHealth()
    const rid = getCurrentRunId()
    if (rid) {
      void loadRunAndExtras(rid)
    } else {
      setInitializing(false)
    }
    // Runs once on mount — localStorage is only readable client-side.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const isSfnWorkflowPolling = Boolean(
    run &&
      hasRealSfnArn(run) &&
      (run.status === "running" || run.workflow_status === "running")
  )

  usePolling(
    async () => {
      if (!run) return
      try {
        const updated = await syncWorkflow(run.id)
        setRun(updated)
        setStatusMessage(
          `Shadow: ${statusLabel(updated.status)}`
        )
        // Keep shadow lifecycle + measured actuals visible while the workflow runs.
        const [shadow, execution] = await Promise.all([
          safeGet(() => getShadowCluster(updated.id)),
          safeGet(() => getExecutionResult(updated.id)),
        ])
        setExtras((prev) => ({
          ...prev,
          shadow: shadow ?? prev.shadow,
          execution: execution ?? prev.execution,
        }))
        if (
          updated.status === "completed" ||
          updated.status === "failed" ||
          updated.workflow_status === "succeeded" ||
          updated.workflow_status === "failed" ||
          updated.workflow_status === "timed_out" ||
          updated.workflow_status === "aborted"
        ) {
          await refreshExtras(updated)
        }
      } catch (err) {
        setStatusMessage(`Sync failed: ${errorMessage(err)}`)
      }
    },
    {
      enabled: isSfnWorkflowPolling,
      shouldStop: () =>
        run?.status === "completed" ||
        run?.status === "failed" ||
        run?.workflow_status === "succeeded" ||
        run?.workflow_status === "failed" ||
        run?.workflow_status === "timed_out" ||
        run?.workflow_status === "aborted",
    }
  )

  function updateConnectionSecretArn(value: string) {
    setConnectionSecretArnState(value)
    setConnectionSecretArn(value)
  }

  async function handleCopyGrant() {
    try {
      await navigator.clipboard.writeText(GRANT_HELP_SQL)
      setGrantCopied(true)
      setTimeout(() => setGrantCopied(false), 2000)
    } catch {
      /* clipboard access denied — the block is still selectable/copyable by hand */
    }
  }

  async function handleCreateFromSql() {
    setError(null)
    const sql = sqlDraft.trim()
    if (!sql) return
    const hasConnection = Boolean(
      databaseUrl.trim() || connectionSecretArn.trim()
    )
    try {
      const ownerIdentity = requireOwnerIdentity()
      setCreating(true)
      setStatusMessage(
        hasConnection
          ? "Creating run and connecting to your database…"
          : "Creating run from pasted SQL…"
      )
      const created = await createRun({
        migration_sql: sql,
        owner_identity: ownerIdentity,
      })
      setCurrentRunId(created.id)
      setRun(created)
      setExtras(EMPTY_EXTRAS)
      setSqlDraft("")
      if (hasConnection) {
        // Connect step was already filled in before creating the run — chain
        // straight into discovery instead of making them click twice.
        await handleDiscover(created)
      } else {
        setStatusMessage(
          "Run created. Connect a database, then run prediction."
        )
      }
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setCreating(false)
    }
  }

  async function handleFakeMigration() {
    setError(null)
    try {
      const ownerIdentity = getOwnerIdentity() || "debug"
      setCreating(true)
      setStatusMessage("Creating a fake debug migration…")
      const created = await createFakeMigration(ownerIdentity)
      setCurrentRunId(created.id)
      setRun(created)
      setExtras(EMPTY_EXTRAS)
      setStatusMessage(
        "Fake migration ready — synthetic schema, safe to predict without a real database."
      )
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setCreating(false)
    }
  }

  async function handleDemoWithDb() {
    setError(null)
    try {
      const ownerIdentity = getOwnerIdentity() || "demo"
      setCreating(true)
      setStatusMessage("Connecting the demo database and discovering schema…")
      const created = await createDemoWithDb(ownerIdentity)
      setCurrentRunId(created.id)
      setRun(created)
      setExtras(EMPTY_EXTRAS)
      if (created.connection_secret_arn) {
        updateConnectionSecretArn(created.connection_secret_arn)
      }
      setStatusMessage(
        created.schema_discovery_status === "succeeded"
          ? "Demo database attached — schema discovered. Run prediction next."
          : "Demo run created but discovery did not succeed — check API logs."
      )
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setCreating(false)
    }
  }

  async function handleDiscover(targetRun?: MigrationRun) {
    const activeRun = targetRun || run
    if (!activeRun) return
    setError(null)
    setDiscoverError(null)
    const arn = connectionSecretArn.trim()
    const url = databaseUrl.trim()
    if (!arn && !url) {
      setDiscoverError(
        "Provide a connection secret ARN or a one-shot read-only database URL."
      )
      return
    }
    let timer: ReturnType<typeof setInterval> | null = null
    try {
      setDiscovering(true)
      setDiscoverProgress(null)
      setStatusMessage("Discovering schema (read-only)…")
      const tick = async () => {
        try {
          const p = await getPipelineProgress(activeRun.id)
          setDiscoverProgress(p)
        } catch {
          /* ignore transient poll errors while discovering */
        }
      }
      await tick()
      timer = setInterval(() => void tick(), 400)
      const updated = await discoverSchema(activeRun.id, {
        connection_secret_arn: arn || null,
        database_url: url || null,
      })
      await tick()
      setRun(updated)
      if (updated.connection_secret_arn) {
        updateConnectionSecretArn(updated.connection_secret_arn)
      }
      if (url) setDatabaseUrl("")
      setStatusMessage(
        updated.schema_discovery_status === "succeeded"
          ? "Schema discovered. Ready to predict."
          : `Discovery status: ${updated.schema_discovery_status || "unknown"}`
      )
    } catch (err) {
      if (err instanceof ApiError) {
        setDiscoverError(discoverErrorHint(err.status, err.message))
      } else {
        setDiscoverError(errorMessage(err))
      }
      setStatusMessage("Discovery failed.")
    } finally {
      if (timer) clearInterval(timer)
      setDiscovering(false)
    }
  }

  async function handlePredict() {
    if (!run) return
    setError(null)
    setPredicting(true)
    setProgress(null)
    setStatusMessage("Running prediction pipeline…")
    let timer: ReturnType<typeof setInterval> | null = null
    try {
      const tick = async () => {
        try {
          const p = await getPipelineProgress(run.id)
          setProgress(p)
          if (p.message) setStatusMessage(p.message)
        } catch {
          /* ignore transient poll errors while predicting */
        }
      }
      await tick()
      timer = setInterval(() => void tick(), 400)
      const updated = await predictRun(run.id)
      await tick()
      setRun(updated)
      await refreshExtras(updated)
      setStatusMessage("Prediction ready — review the assessment, then approve.")
    } catch (err) {
      const msg = errorMessage(err)
      setError(msg)
      setStatusMessage(msg)
    } finally {
      if (timer) clearInterval(timer)
      setPredicting(false)
    }
  }

  async function handleApprove(decision: ApprovalDecision) {
    if (!run) return
    setError(null)
    const assessment = mapAssessment(run)
    if (
      assessment.policyDecision === "block" &&
      decision === "proceed" &&
      !overrideRationale.trim()
    ) {
      setError(
        "Override rationale is required — policy blocked this migration."
      )
      return
    }
    try {
      const approverIdentity = requireOwnerIdentity()
      setApproving(decision)
      setStatusMessage(
        decision === "proceed"
          ? "Approving — then start the shadow test…"
          : decision === "accept_recommended"
            ? "Skipping shadow — ending run with recommendation only…"
            : "Cancelling run…"
      )
      const updated = await approveRun(run.id, {
        decision,
        approver_identity: approverIdentity,
        override_rationale: overrideRationale.trim() || null,
        start_workflow: false,
        connection_secret_arn:
          connectionSecretArn.trim() || run.connection_secret_arn || null,
      })
      setRun(updated)
      // Don't block the UI on extras for non-shadow decisions.
      void refreshExtras(updated)
      const approval = await safeGet(() => getApproval(updated.id))
      setRecordedApproval(approval)
      setStatusMessage(
        decision === "cancel"
          ? "Run cancelled."
          : decision === "accept_recommended"
            ? "Done — skipped shadow. This run is complete (no cluster)."
            : "Approved. Click Start shadow test below."
      )
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setApproving(null)
    }
  }

  async function handleStartShadow() {
    if (!run) return
    setError(null)
    setStartingShadow(true)
    try {
      if (!isSfnReady(health)) {
        throw new Error(sfnNotReadyMessage(health))
      }
      const secret =
        connectionSecretArn.trim() || run.connection_secret_arn || null
      const url = databaseUrl.trim() || null
      if (!secret && !url) {
        throw new Error(
          "No database attached. Go to Attach database, paste a read-only URL (or secret ARN), click Discover schema, then start the shadow."
        )
      }
      setStatusMessage("Starting shadow…")
      let current = run
      if (!hasRealSfnArn(current)) {
        current = await startWorkflow(current.id, {
          connection_secret_arn: secret,
          database_url: secret ? null : url,
        })
        setRun(current)
        if (current.connection_secret_arn) {
          updateConnectionSecretArn(current.connection_secret_arn)
        }
      }
      if (!hasRealSfnArn(current)) {
        throw new Error(
          "Shadow did not start. Check database attachment."
        )
      }
      openWatch(current.id)
      setStatusMessage("Shadow running — live watch opened.")
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setStartingShadow(false)
    }
  }

  async function handleAbortShadow() {
    if (!run) return
    setError(null)
    setAbortingShadow(true)
    try {
      setStatusMessage("Aborting shadow workflow and tearing down cluster…")
      const updated = await abortWorkflow(run.id)
      setRun(updated)
      await refreshExtras(updated)
      setStatusMessage(
        `Shadow aborted — ${statusLabel(updated.status)}`
      )
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setAbortingShadow(false)
    }
  }

  const assessment = run ? mapAssessment(run) : null
  const schema = run ? mapSchema(run) : null
  const comparisons = run ? mapComparisons(run, extras) : []
  const hasPrediction = Boolean(
    assessment && (assessment.policyDecision != null || assessment.prediction)
  )
  const canPredict =
    run?.status === "pending" &&
    (run.schema_discovery_status === "succeeded" ||
      Boolean(run.schema_snapshot) ||
      Boolean(schema?.isSynthetic))
  const dbAttached =
    Boolean(run?.connection_secret_arn) ||
    run?.schema_discovery_status === "succeeded"
  const unknownTables = React.useMemo(
    () =>
      findUnknownTableReferences(
        run?.migration_sql || "",
        schema?.tables.map((t) => t.name) || []
      ),
    [run?.migration_sql, schema]
  )
  const canApprove = run?.status === "awaiting_approval"
  const canStartShadow =
    run?.status === "running" &&
    !hasRealSfnArn(run) &&
    run.workflow_status === "not_started"
  const shadowLive =
    Boolean(run) &&
    (run!.status === "running" ||
      Boolean(extras.shadow) ||
      (hasRealSfnArn(run!) && run!.workflow_status === "running"))
  const hasOutcome = Boolean(
    run &&
      (extras.grade ||
        extras.memory ||
        extras.execution ||
        extras.shadow ||
        run.status === "completed" ||
        run.status === "failed")
  )

  return (
    <div className="flex flex-1 flex-col gap-5 px-4 pb-8 md:px-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          href="/dashboard"
          className={cn(
            buttonVariants({ variant: "ghost", size: "sm" }),
            "text-muted-foreground hover:text-foreground -ml-2 font-mono text-[11px] tracking-tight"
          )}
        >
          ← Back to Overview
        </Link>
        <Link
          href="/dashboard/migrations/history"
          className="text-muted-foreground hover:text-foreground font-mono text-[11px] tracking-tight transition-colors"
        >
          Past Migrations →
        </Link>
      </div>

      <header className="space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <h1 className="text-foreground text-2xl font-medium tracking-tight">
              Current Migration
            </h1>
            <p className="text-muted-foreground font-mono text-xs tracking-tight">
              {statusMessage}
            </p>
            {error ? (
              <p className="font-mono text-xs tracking-tight text-[var(--oracle-risk)]">
                {error}
              </p>
            ) : null}
          </div>
          {run ? (
            <div className="flex flex-col items-start gap-1 sm:items-end">
              <div className="flex items-center gap-2">
                <StatusDot tone={statusTone(run.status)} />
                <span className="text-muted-foreground font-mono text-[11px] tracking-[0.14em] uppercase">
                  {statusLabel(run.status)}
                </span>
              </div>
              <p className="text-muted-foreground/55 font-mono text-[10px] tracking-tight">
                {formatRelativeTime(run.created_at)}
              </p>
            </div>
          ) : null}
        </div>

        {run ? (
          <div className="border-border/70 flex flex-col gap-3 border-t pt-3 sm:flex-row sm:items-center sm:justify-between">
            <ProcessStages run={run} />
            <div className="flex flex-wrap gap-2">
              <Link
                href={`/dashboard/migrations/${run.id}`}
                className={cn(
                  buttonVariants({ variant: "outline", size: "sm" }),
                  "shrink-0"
                )}
              >
                Full detail &amp; model traces
              </Link>
              <Link
                href="/dashboard/migrations/current/shadow"
                className={cn(
                  buttonVariants({ variant: "outline", size: "sm" }),
                  "shrink-0"
                )}
              >
                Shadow execution
              </Link>
            </div>
          </div>
        ) : null}
      </header>

      {initializing ? (
        <section className="border-border rounded-lg border p-4">
          <p className="text-muted-foreground font-mono text-xs tracking-tight">
            Loading current run…
          </p>
        </section>
      ) : !run ? (
        <>
          <Section title="1. Connect your database">
            <div className="space-y-4">
              <ol className="text-muted-foreground max-w-2xl list-decimal space-y-1 pl-5 text-sm leading-relaxed">
                <li>Connect a read-only database (or use the demo one).</li>
                <li>Write or paste your migration SQL.</li>
                <li>Predict → decide → shadow → outcome.</li>
              </ol>
              <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
                Read-only access to your schema. Production is never written —
                the schema is what makes the migration meaningful, so it comes
                first.
              </p>
              <ConnectDatabaseFields
                databaseUrl={databaseUrl}
                onDatabaseUrlChange={setDatabaseUrl}
                connectionSecretArn={connectionSecretArn}
                onConnectionSecretArnChange={updateConnectionSecretArn}
                showArnField={showArnField}
                onToggleArnField={() => setShowArnField((v) => !v)}
                showGrantHelp={showGrantHelp}
                onToggleGrantHelp={() => setShowGrantHelp((v) => !v)}
                grantCopied={grantCopied}
                onCopyGrant={() => void handleCopyGrant()}
                onSubmit={() => {
                  /* No run yet — connection info is captured here and used
                     the moment "Create run" below fires discovery. */
                }}
                submitting={false}
                submitLabel="Filled in above? Write your SQL below and create the run to connect. ↓"
                hideSubmit
                showDemoButton
                onDemo={() => void handleDemoWithDb()}
                demoDisabled={creating}
              />
            </div>
          </Section>

          <Section title="2. Your migration SQL">
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_16rem]">
              <div className="space-y-3">
                <textarea
                  id="current-migration-sql"
                  value={sqlDraft}
                  onChange={(e) => setSqlDraft(e.target.value)}
                  spellCheck={false}
                  placeholder="ALTER TABLE customers ADD COLUMN …;"
                  className={cn(
                    "border-input bg-background text-foreground placeholder:text-muted-foreground",
                    "focus-visible:border-ring focus-visible:ring-ring/50",
                    "min-h-48 w-full resize-y rounded-md border px-3 py-2 font-mono text-[12px] leading-relaxed outline-none",
                    "focus-visible:ring-3"
                  )}
                />
                <Button
                  type="button"
                  disabled={creating || !sqlDraft.trim()}
                  onClick={() => void handleCreateFromSql()}
                >
                  {creating
                    ? "Creating…"
                    : databaseUrl.trim() || connectionSecretArn.trim()
                      ? "Create run & discover schema"
                      : "Create run"}
                </Button>
                {!databaseUrl.trim() && !connectionSecretArn.trim() ? (
                  <p className="text-muted-foreground/70 max-w-md text-xs leading-relaxed">
                    No connection filled in above — you can still create the
                    run and connect a database after.
                  </p>
                ) : null}
              </div>
              <OwnerIdentityField id="owner-identity-empty" />
            </div>

            {process.env.NEXT_PUBLIC_ENABLE_DEBUG_TOOLS === "true" ? (
              <div className="border-amber-500/30 bg-amber-500/5 mt-4 space-y-3 rounded-lg border p-4">
                <p className="font-mono text-[10px] tracking-[0.14em] text-amber-400/90 uppercase">
                  Developer tools
                </p>
                <Button
                  type="button"
                  variant="outline"
                  disabled={creating}
                  onClick={() => void handleFakeMigration()}
                >
                  {creating ? "Creating…" : "Fake migration (no DB)"}
                </Button>
              </div>
            ) : null}
          </Section>
        </>
      ) : (
        <>
          <Section title="1. Attach your database">
            <div className="space-y-4">
              <div
                className={cn(
                  "rounded-md border px-3 py-2 font-mono text-[11px] tracking-tight",
                  dbAttached
                    ? "border-[var(--oracle-verified)]/40 bg-[var(--oracle-verified)]/5 text-[var(--oracle-verified)]"
                    : "border-amber-500/30 bg-amber-500/5 text-amber-200/90"
                )}
              >
                {dbAttached
                  ? `Connected — schema ${run.schema_discovery_status || "ready"}`
                  : "Not connected — paste a read-only URL or secret, then Discover."}
              </div>

              {!dbAttached ? (
                <ConnectDatabaseFields
                  databaseUrl={databaseUrl}
                  onDatabaseUrlChange={setDatabaseUrl}
                  connectionSecretArn={connectionSecretArn}
                  onConnectionSecretArnChange={updateConnectionSecretArn}
                  showArnField={showArnField}
                  onToggleArnField={() => setShowArnField((v) => !v)}
                  showGrantHelp={showGrantHelp}
                  onToggleGrantHelp={() => setShowGrantHelp((v) => !v)}
                  grantCopied={grantCopied}
                  onCopyGrant={() => void handleCopyGrant()}
                  onSubmit={() => void handleDiscover()}
                  submitting={discovering}
                  submitLabel={discovering ? "Discovering…" : "Discover schema"}
                  showDemoButton
                  onDemo={() => void handleDemoWithDb()}
                  demoDisabled={creating || discovering}
                />
              ) : null}

              {discovering ? (
                <div className="space-y-1.5">
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-[var(--oracle-reasoning-soft)] transition-all"
                      style={{
                        width: `${Math.max(0, Math.min(100, discoverProgress?.percent ?? 5))}%`,
                      }}
                    />
                  </div>
                  <p className="text-muted-foreground font-mono text-[11px] tracking-tight">
                    {discoverProgress?.message || "Connecting…"}
                  </p>
                </div>
              ) : null}

              {discoverError ? (
                <p className="font-mono text-xs leading-relaxed text-[var(--oracle-risk)]">
                  {discoverError}
                </p>
              ) : null}

              {schema ? (
                <div className="border-t border-border/60 pt-3">
                  <Disclosure
                    label={`Schema details (${schema.tables.length} table${schema.tables.length === 1 ? "" : "s"})`}
                    openLabel="Hide schema details"
                  >
                    <div className="space-y-2">
                      <p className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
                        status: {schema.status || "—"}
                        {schema.engine ? (
                          <>
                            <span className="text-muted-foreground/35 mx-1.5">·</span>
                            {schema.engine}
                            {schema.version ? ` ${schema.version}` : ""}
                          </>
                        ) : null}
                        {schema.isSynthetic ? (
                          <>
                            <span className="text-muted-foreground/35 mx-1.5">·</span>
                            <span className="text-amber-400/80">synthetic (debug)</span>
                          </>
                        ) : null}
                      </p>
                      {schema.debugNote ? (
                        <p className="text-muted-foreground/60 font-mono text-[10px] leading-relaxed tracking-tight">
                          {schema.debugNote}
                        </p>
                      ) : null}
                      <SchemaTables schema={schema} />
                    </div>
                  </Disclosure>
                </div>
              ) : (
                <p className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
                  No tables yet — discover first.
                </p>
              )}
            </div>
          </Section>

          <Section title="2. Migration">
            <div className="space-y-3">
              {unknownTables.length > 0 ? (
                <p className="font-mono text-[11px] leading-relaxed text-[var(--oracle-risk)]">
                  SQL references{" "}
                  {unknownTables.length === 1 ? "a table" : "tables"} discovery
                  didn&apos;t find: {unknownTables.join(", ")} — this migration
                  will fail.
                </p>
              ) : null}
              <Disclosure
                label={`View migration SQL (${sqlFilename(run.migration_sql, run.id)})`}
                openLabel="Hide migration SQL"
              >
                <div className="space-y-2">
                  {schema && schema.tables.length > 0 ? (
                    <p className="text-muted-foreground/70 font-mono text-[10px] leading-relaxed tracking-tight">
                      Discovered tables: {schema.tables.map((t) => t.name).join(", ")}
                    </p>
                  ) : null}
                  <SqlCodePanel
                    filename={sqlFilename(run.migration_sql, run.id)}
                    sql={run.migration_sql}
                  />
                </div>
              </Disclosure>
            </div>
          </Section>

          {canPredict || run.status === "predicting" ? (
            <Section title="3. Prediction">
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    disabled={!canPredict || predicting}
                    onClick={() => void handlePredict()}
                  >
                    {run.status === "predicting"
                      ? "Predicting…"
                      : "Run prediction"}
                  </Button>
                  <p className="text-muted-foreground text-sm">
                    Estimates duration, storage, and risk.
                  </p>
                </div>
                {predicting || run.status === "predicting" ? (
                  <div className="space-y-1.5">
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-[var(--oracle-reasoning-soft)] transition-all"
                        style={{
                          width: `${Math.max(0, Math.min(100, progress?.percent ?? 0))}%`,
                        }}
                      />
                    </div>
                    <p className="text-muted-foreground font-mono text-[11px] tracking-tight">
                      {progress?.message || "Working…"}
                      <span className="text-muted-foreground/40 mx-1.5">·</span>
                      {Math.round(progress?.percent ?? 0)}%
                    </p>
                  </div>
                ) : null}
              </div>
            </Section>
          ) : run.status === "pending" && !canPredict ? (
            <Section title="3. Prediction">
              <p className="text-muted-foreground text-sm">
                Attach and discover schema first.
              </p>
            </Section>
          ) : null}

          {hasPrediction && assessment ? (
            <Section title="Assessment">
              <AssessmentPanel assessment={assessment} />
            </Section>
          ) : null}

          {hasPrediction && assessment ? (
            <Section title="Learning">
              <RetrievalPanel assessment={assessment} />
            </Section>
          ) : null}

          {assessment?.policyDecision != null ? (
            <Section title="Approval">
              {canApprove ? (
                <div className="space-y-4">
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    Proceed runs a disposable shadow test. Skip keeps the plan
                    only.
                  </p>

                  {assessment.policyDecision === "block" ? (
                    <div className="flex flex-col gap-2">
                      <p className="font-mono text-xs leading-relaxed text-amber-400/90">
                        Policy blocked this migration — type a short reason to
                        proceed anyway.
                      </p>
                      <label
                        htmlFor="override-rationale"
                        className="text-muted-foreground font-mono text-[10px] tracking-[0.12em] uppercase"
                      >
                        Override rationale (required to proceed)
                      </label>
                      <textarea
                        id="override-rationale"
                        value={overrideRationale}
                        onChange={(e) => setOverrideRationale(e.target.value)}
                        placeholder="Why this should still run on a shadow cluster…"
                        className={cn(
                          "border-input bg-background text-foreground placeholder:text-muted-foreground",
                          "focus-visible:border-ring focus-visible:ring-ring/50",
                          "min-h-20 w-full resize-y rounded-md border px-3 py-2 font-mono text-[12px] leading-relaxed outline-none",
                          "focus-visible:ring-3"
                        )}
                      />
                    </div>
                  ) : null}

                  <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
                    <Button
                      disabled={approving != null}
                      onClick={() => void handleApprove("proceed")}
                      className="sm:min-w-44"
                    >
                      {approving === "proceed"
                        ? "Saving…"
                        : "Proceed to shadow test"}
                    </Button>
                    {assessment.recommendation ? (
                      <Button
                        variant="secondary"
                        disabled={approving != null}
                        onClick={() => void handleApprove("accept_recommended")}
                        className="sm:min-w-40"
                      >
                        {approving === "accept_recommended"
                          ? "Saving…"
                          : "Skip shadow (keep plan)"}
                      </Button>
                    ) : null}
                    <Button
                      variant="outline"
                      disabled={approving != null}
                      onClick={() => void handleApprove("cancel")}
                      className="sm:min-w-28"
                    >
                      {approving === "cancel" ? "Saving…" : "Cancel run"}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-foreground/85 text-sm leading-relaxed">
                    {run.status === "pending" || run.status === "predicting"
                      ? "Run prediction first, then approve here."
                      : run.status === "completed" &&
                          recordedApproval?.decision === "accept_recommended"
                        ? "You skipped the shadow — this run is complete. No cluster was started. Create a new migration (or click Proceed on a fresh run) if you want a real shadow test."
                        : run.status === "running"
                          ? "Approved — use Shadow cluster below to start or watch the real verify."
                          : run.status === "failed"
                            ? "This run was cancelled or failed. Approval is closed."
                            : "Decision already recorded for this run."}
                  </p>
                  {recordedApproval ? (
                    <div className="border-border/50 space-y-1.5 rounded-md border p-3">
                      <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
                        Recorded decision
                      </p>
                      <p className="text-foreground/85 font-mono text-xs tracking-tight">
                        {recordedApproval.decision}
                        <span className="text-muted-foreground/40 mx-1.5">·</span>
                        {recordedApproval.approver_identity}
                      </p>
                      {recordedApproval.override_rationale ? (
                        <p className="text-foreground/80 text-sm leading-relaxed">
                          <span className="text-muted-foreground/60 font-mono text-[10px] uppercase">
                            Override rationale:{" "}
                          </span>
                          {recordedApproval.override_rationale}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              )}
            </Section>
          ) : null}

          {run.status === "running" || shadowLive ? (
            <Section title="Shadow">
              {canStartShadow ? (
                <div className="space-y-3">
                  {comparisons.length > 0 ? (
                    <ComparisonsPanel rows={comparisons} />
                  ) : null}
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      disabled={startingShadow || !isSfnReady(health)}
                      onClick={() => void handleStartShadow()}
                    >
                      {startingShadow ? "Starting…" : "Start shadow test"}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => openWatch(run.id)}
                    >
                      Watch live
                    </Button>
                    <Link
                      href="/dashboard/migrations/current/shadow"
                      className={cn(
                        buttonVariants({ variant: "ghost", size: "sm" })
                      )}
                    >
                      Open full page
                    </Link>
                  </div>
                  {!isSfnReady(health) ? (
                    <p className="text-sm text-[var(--oracle-risk)]">
                      Shadow not ready — check Settings / health.
                    </p>
                  ) : null}
                </div>
              ) : (
                <ShadowLiveView
                  run={run}
                  extras={extras}
                  comparisons={comparisons}
                  isLive={isSfnWorkflowPolling}
                  awaitingStart={canStartShadow}
                >
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => openWatch(run.id)}
                    >
                      Watch live
                    </Button>
                    <Link
                      href="/dashboard/migrations/current/shadow"
                      className={cn(
                        buttonVariants({ variant: "outline", size: "sm" })
                      )}
                    >
                      Open full page
                    </Link>
                    {hasRealSfnArn(run) &&
                    (run.workflow_status === "running" ||
                      run.status === "running") ? (
                      <Button
                        type="button"
                        variant="outline"
                        disabled={abortingShadow}
                        onClick={() => void handleAbortShadow()}
                      >
                        {abortingShadow ? "Aborting…" : "Abort"}
                      </Button>
                    ) : null}
                  </div>
                </ShadowLiveView>
              )}
            </Section>
          ) : null}

          {hasOutcome ? (
            <Section title="Outcome">
              <div className="space-y-4">
                <ComparisonsPanel rows={comparisons} />

                {extras.grade ? (
                  <dl className="max-w-md space-y-1.5">
                    <FieldRow
                      label="Grade"
                      value={extras.grade.scalar_accuracy_score.toFixed(3)}
                    />
                    <FieldRow
                      label="Class"
                      value={extras.grade.outcome_class}
                    />
                  </dl>
                ) : null}

                {extras.memory &&
                extras.memory.embedding_status !== "ready" ? (
                  <p className="text-muted-foreground text-sm">
                    Memory saved — indexing for next predictions…
                  </p>
                ) : extras.memory ? (
                  <p className="text-muted-foreground text-sm">
                    Saved to Agent Memory for future runs.
                  </p>
                ) : null}

                {extras.execution?.error_message ||
                extras.shadow?.error_message ? (
                  <p className="font-mono text-xs leading-relaxed text-[var(--oracle-risk)]">
                    {extras.execution?.error_message ||
                      extras.shadow?.error_message}
                  </p>
                ) : null}

                {run.status === "completed" &&
                !extras.execution &&
                !extras.shadow ? (
                  <p className="text-muted-foreground text-sm">
                    Completed without a shadow test.
                  </p>
                ) : null}
              </div>
            </Section>
          ) : null}
        </>
      )}
    </div>
  )
}
