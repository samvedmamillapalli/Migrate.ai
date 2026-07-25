"use client"

import * as React from "react"
import Link from "next/link"

import { Button, buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

import { ShadowLivePanel } from "@/components/shadow-live-panel"
import {
  ApiError,
  abortWorkflow,
  formatDuration,
  formatRelativeTime,
  formatStorage,
  getConnectionSecretArn,
  getCurrentRunId,
  getExecutionResult,
  getGrade,
  getHealth,
  getMemory,
  getRun,
  getShadowCluster,
  hasRealSfnArn,
  isSfnReady,
  mapComparisons,
  startWorkflow,
  statusLabel,
  syncWorkflow,
  usePolling,
  workflowLabel,
  type ExecutionResult,
  type Grade,
  type HealthResponse,
  type Memory,
  type MigrationRun,
  type RunExtras,
  type ShadowCluster,
} from "@/lib/api"

const EMPTY_EXTRAS: RunExtras = {
  grade: null,
  memory: null,
  shadow: null,
  execution: null,
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

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section
      aria-label={title}
      className="border-border flex w-full flex-col gap-4 rounded-lg border p-4"
    >
      <h2 className="text-muted-foreground text-[11px] font-medium tracking-[0.16em] uppercase">
        {title}
      </h2>
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
  if (status === "completed" || status === "succeeded") return "ok"
  if (status === "failed" || status === "timed_out" || status === "aborted") return "bad"
  if (status === "running") return "warn"
  return "muted"
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return "Something went wrong."
}

export default function ShadowExecutionPage() {
  const [initializing, setInitializing] = React.useState(true)
  const [run, setRun] = React.useState<MigrationRun | null>(null)
  const [extras, setExtras] = React.useState<RunExtras>(EMPTY_EXTRAS)
  const [health, setHealth] = React.useState<HealthResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [statusMessage, setStatusMessage] = React.useState<string | null>(null)
  const [starting, setStarting] = React.useState(false)
  const [aborting, setAborting] = React.useState(false)

  const refreshExtras = React.useCallback(async (target: MigrationRun) => {
    if (!extrasReady(target.status)) {
      setExtras(EMPTY_EXTRAS)
      return
    }
    const [grade, memory, execution, shadow] = await Promise.all([
      safeGet<Grade>(() => getGrade(target.id)),
      safeGet<Memory>(() => getMemory(target.id)),
      safeGet<ExecutionResult>(() => getExecutionResult(target.id)),
      safeGet<ShadowCluster>(() => getShadowCluster(target.id)),
    ])
    setExtras({ grade, memory, execution, shadow })
  }, [])

  const load = React.useCallback(async () => {
    setError(null)
    const rid = getCurrentRunId()
    if (!rid) {
      setRun(null)
      setExtras(EMPTY_EXTRAS)
      setInitializing(false)
      return
    }
    try {
      const [r, h] = await Promise.all([
        getRun(rid),
        safeGet(() => getHealth()),
      ])
      setRun(r)
      if (h) setHealth(h)
      await refreshExtras(r)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setRun(null)
        setExtras(EMPTY_EXTRAS)
      } else {
        setError(err instanceof Error ? err.message : "Failed to load run.")
      }
    } finally {
      setInitializing(false)
    }
  }, [refreshExtras])

  React.useEffect(() => {
    void load()
  }, [load])

  const canStart =
    Boolean(run) &&
    run!.status === "running" &&
    !hasRealSfnArn(run!) &&
    run!.workflow_status === "not_started"

  const isPolling = Boolean(
    run &&
      hasRealSfnArn(run) &&
      (run.workflow_status === "running" || run.status === "running")
  )

  const awaitingStart = Boolean(canStart)

  usePolling(
    async () => {
      if (!run) return
      const updated = await syncWorkflow(run.id)
      setRun(updated)
      const [shadow, execution, grade] = await Promise.all([
        safeGet(() => getShadowCluster(updated.id)),
        safeGet(() => getExecutionResult(updated.id)),
        safeGet(() => getGrade(updated.id)),
      ])
      setExtras((prev) => ({
        ...prev,
        shadow: shadow ?? prev.shadow,
        execution: execution ?? prev.execution,
        grade: grade ?? prev.grade,
      }))
      if (shadow?.status) {
        setStatusMessage(`Shadow status: ${shadow.status}`)
      }
      if (
        updated.status === "completed" ||
        updated.status === "failed" ||
        updated.workflow_status === "succeeded" ||
        updated.workflow_status === "failed" ||
        updated.workflow_status === "timed_out" ||
        updated.workflow_status === "aborted"
      ) {
        await refreshExtras(updated)
        setStatusMessage(
          updated.status === "completed"
            ? "Shadow finished — see prediction vs actual below."
            : `Run ${statusLabel(updated.status)} / workflow ${workflowLabel(updated.workflow_status)}`
        )
      }
    },
    {
      enabled: isPolling,
      intervalMs: 1500,
      backoffAfterMs: 120_000,
      backoffIntervalMs: 4000,
      shouldStop: () =>
        run?.status === "completed" ||
        run?.status === "failed" ||
        run?.workflow_status === "succeeded" ||
        run?.workflow_status === "failed" ||
        run?.workflow_status === "timed_out" ||
        run?.workflow_status === "aborted",
    }
  )

  async function handleStart() {
    if (!run) return
    setError(null)
    setStarting(true)
    try {
      if (!isSfnReady(health)) {
        const h = await getHealth()
        setHealth(h)
        if (!isSfnReady(h)) {
          throw new Error(
            "Step Functions is not ready. Check MIGRATION_WORKFLOW_ARN on the API."
          )
        }
      }
      const secret =
        getConnectionSecretArn().trim() || run.connection_secret_arn || null
      if (!secret) {
        throw new Error(
          "No database attached to this run. Go to Current Migration → Attach your database → Discover schema (or use Developer mode), then start shadow again."
        )
      }
      setStatusMessage("Starting real CockroachDB Cloud shadow via Step Functions…")
      const updated = await startWorkflow(run.id, {
        connection_secret_arn: secret,
      })
      setRun(updated)
      if (!hasRealSfnArn(updated)) {
        throw new Error(
          "No Step Functions execution ARN returned. Check connection secret ARN on Current Migration."
        )
      }
      setStatusMessage(`Shadow workflow running — watch the steps below.`)
      const shadow = await safeGet(() => getShadowCluster(updated.id))
      if (shadow) setExtras((prev) => ({ ...prev, shadow }))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setStarting(false)
    }
  }

  async function handleAbort() {
    if (!run) return
    setError(null)
    setAborting(true)
    try {
      setStatusMessage("Aborting and tearing down cluster…")
      const updated = await abortWorkflow(run.id)
      setRun(updated)
      await refreshExtras(updated)
      setStatusMessage("Aborted — cluster teardown requested.")
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setAborting(false)
    }
  }

  const comparisons = run ? mapComparisons(run, extras) : []

  return (
    <div className="flex flex-1 flex-col gap-5 px-4 pb-8 md:px-6">
      <header className="space-y-3">
        <nav
          aria-label="Breadcrumb"
          className="text-muted-foreground flex flex-wrap items-center gap-1.5 font-mono text-[11px] tracking-tight"
        >
          <Link
            href="/dashboard/migrations/current"
            className="hover:text-foreground transition-colors"
          >
            Current Migration
          </Link>
          <span className="text-muted-foreground/40">/</span>
          <span className="text-foreground">Shadow Execution</span>
        </nav>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <h1 className="text-foreground text-2xl font-medium tracking-tight">
              Shadow Execution
            </h1>
            {run ? (
              <p className="text-muted-foreground font-mono text-xs tracking-tight">
                run {run.id.slice(0, 8)}
                <span className="text-muted-foreground/50 mx-2">·</span>
                created {formatRelativeTime(run.created_at)}
              </p>
            ) : null}
            {statusMessage ? (
              <p className="text-foreground/75 max-w-2xl text-sm leading-relaxed">
                {statusMessage}
              </p>
            ) : null}
          </div>
          {run ? (
            <div className="flex items-center gap-2 self-start">
              <StatusDot tone={statusTone(run.status)} />
              <span className="font-mono text-[11px] tracking-[0.14em] uppercase text-foreground/80">
                {statusLabel(run.status)}
              </span>
            </div>
          ) : null}
        </div>
      </header>

      {error ? (
        <p className="font-mono text-xs tracking-tight text-[var(--oracle-risk)]">
          {error}
        </p>
      ) : null}

      {initializing ? (
        <section className="border-border rounded-lg border p-4">
          <p className="text-muted-foreground font-mono text-xs tracking-tight">
            Loading shadow execution…
          </p>
        </section>
      ) : !run ? (
        <section className="border-border flex flex-col gap-3 rounded-lg border p-4">
          <p className="text-muted-foreground font-mono text-xs tracking-tight">
            No current run. Create or select a migration first.
          </p>
          <Link
            href="/dashboard/migrations/current"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-fit")}
          >
            ← Back to Current Migration
          </Link>
        </section>
      ) : (
        <>
          <Section title="Controls">
            <dl className="mb-4 max-w-md space-y-1.5">
              <FieldRow label="Run status" value={statusLabel(run.status)} />
              <FieldRow
                label="Workflow status"
                value={workflowLabel(run.workflow_status)}
              />
              <FieldRow
                label="Mode"
                value={
                  hasRealSfnArn(run)
                    ? "AWS Step Functions (real cloud shadow)"
                    : canStart
                      ? "Approved — waiting for you to start"
                      : run.status === "awaiting_approval"
                        ? "Approve on Current Migration first"
                        : "Not started"
                }
              />
            </dl>

            {run.status === "awaiting_approval" ? (
              <p className="text-muted-foreground text-sm leading-relaxed">
                This run still needs approval. Go back to Current Migration →{" "}
                <span className="text-foreground">Proceed to shadow test</span>, then
                return here.
              </p>
            ) : null}

            {canStart ? (
              <div className="flex flex-col gap-3">
                {!run.connection_secret_arn && !getConnectionSecretArn().trim() ? (
                  <p className="text-sm leading-relaxed text-[var(--oracle-risk)]">
                    This run has no database attached (that’s why Start was failing with
                    422). Go to Current Migration, attach a read-only URL / Discover,
                    or click Developer mode → Use demo database on a new run.
                  </p>
                ) : null}
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <Button
                    type="button"
                    disabled={
                      starting ||
                      (!run.connection_secret_arn && !getConnectionSecretArn().trim())
                    }
                    onClick={() => void handleStart()}
                  >
                    {starting ? "Starting…" : "Start shadow test"}
                  </Button>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    Spins up a real disposable CockroachDB Cloud cluster and runs
                    through the steps on this page (~1.5–2 min).
                  </p>
                </div>
              </div>
            ) : null}

            {isPolling ? (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <Button
                  type="button"
                  variant="outline"
                  disabled={aborting}
                  onClick={() => void handleAbort()}
                >
                  {aborting ? "Aborting…" : "Abort + tear down"}
                </Button>
                <p className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
                  Live updates every ~1.5s
                </p>
              </div>
            ) : null}

            {run.status !== "running" &&
            run.status !== "awaiting_approval" &&
            !canStart &&
            !isPolling ? (
              <p className="text-muted-foreground text-sm leading-relaxed">
                {run.status === "completed"
                  ? "This shadow run finished. Steps below show what happened."
                  : run.status === "failed"
                    ? "This run failed or was aborted."
                    : "Finish discover → predict → Proceed on Current Migration first."}
              </p>
            ) : null}
          </Section>

          <Section title="Live shadow steps">
            <ShadowLivePanel
              run={run}
              extras={extras}
              comparisons={comparisons}
              isLive={isPolling}
              awaitingStart={awaitingStart}
            />
          </Section>

          {extras.execution ? (
            <Section title="Execution result">
              <dl className="max-w-md space-y-1.5">
                <FieldRow
                  label="Actual duration"
                  value={formatDuration(extras.execution.actual_duration_seconds)}
                />
                <FieldRow
                  label="Actual storage"
                  value={formatStorage(extras.execution.actual_storage_mb)}
                />
                <FieldRow
                  label="Success"
                  value={extras.execution.success ? "yes" : "no"}
                  valueClassName={
                    extras.execution.success
                      ? "text-[var(--oracle-verified)]"
                      : "text-[var(--oracle-risk)]"
                  }
                />
              </dl>
            </Section>
          ) : null}

          {extras.grade ? (
            <Section title="Grade">
              <dl className="max-w-md space-y-1.5">
                <FieldRow
                  label="Accuracy score"
                  value={extras.grade.scalar_accuracy_score.toFixed(3)}
                />
                <FieldRow label="Outcome class" value={extras.grade.outcome_class} />
              </dl>
            </Section>
          ) : null}

          <div>
            <Link
              href="/dashboard/migrations/current"
              className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2")}
            >
              ← Back to Current Migration
            </Link>
          </div>
        </>
      )}
    </div>
  )
}
