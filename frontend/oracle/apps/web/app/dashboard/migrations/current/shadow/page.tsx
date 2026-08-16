"use client"

import * as React from "react"
import Link from "next/link"

import { Button, buttonVariants } from "@workspace/ui/components/button"
import {
  EmptyNote,
  ErrorNote,
  Label,
  PageHeader,
  Panel,
  SkeletonLines,
  StatusPill,
  toneText,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

import { ShadowClusterComparison } from "@/components/shadow-cluster-comparison"
import { ShadowLiveView } from "@/components/shadow-live-view"
import { ShadowTeardownControl } from "@/components/shadow-teardown-control"
import { GradeRunAction } from "@/components/grade-run-action"
import { useShadowWatch } from "@/components/shadow-watch-context"
import {
  ApiError,
  abortWorkflow,
  formatRelativeTime,
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
  sfnNotReadyMessage,
  mapComparisons,
  startWorkflow,
  statusLabel,
  syncWorkflow,
  usePolling,
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
    <Panel
      aria-label={title}
      className="flex w-full flex-col gap-4 px-6 py-5"
    >
      <Label>{title}</Label>
      {children}
    </Panel>
  )
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return "Something went wrong."
}

export default function ShadowExecutionPage() {
  const { openWatch } = useShadowWatch()
  const [initializing, setInitializing] = React.useState(true)
  const [run, setRun] = React.useState<MigrationRun | null>(null)
  const [extras, setExtras] = React.useState<RunExtras>(EMPTY_EXTRAS)
  const [health, setHealth] = React.useState<HealthResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [statusMessage, setStatusMessage] = React.useState<string | null>(null)
  const [starting, setStarting] = React.useState(false)
  const [aborting, setAborting] = React.useState(false)
  // The shadow row ShadowLiveView resolved to — SSE frame while live, polled
  // extras otherwise. Lifted so the comparison and teardown control render off
  // the same live value without opening a second EventSource.
  const [liveShadow, setLiveShadow] = React.useState<ShadowCluster | null>(null)

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
            : `Run ${statusLabel(updated.status)}`
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

  // The cluster outlives the workflow: after execute + measure, it is held
  // alive for `shadow_hold_minutes` so this page has something real to show.
  // The poll above stops at run completion, so keep a slower one running
  // while the cluster itself is still alive — otherwise the hold never
  // visibly ends and "Delete now" never reflects the teardown it triggered.
  const shadowStatus = (liveShadow ?? extras.shadow)?.status?.toLowerCase() ?? null
  const shadowStillAlive = Boolean(
    shadowStatus &&
      !["destroyed", "failed"].includes(shadowStatus) &&
      !isPolling
  )

  usePolling(
    async () => {
      if (!run) return
      const latest = await safeGet(() => getShadowCluster(run.id))
      if (latest) {
        setExtras((prev) => ({ ...prev, shadow: latest }))
        setLiveShadow(latest)
      }
    },
    { enabled: shadowStillAlive, intervalMs: 5000, backoffAfterMs: 600_000 }
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
          throw new Error(sfnNotReadyMessage(h))
        }
      }
      const secret =
        getConnectionSecretArn().trim() || run.connection_secret_arn || null
      if (!secret) {
        throw new Error(
          "No database attached to this run. Go to Current Migration → Attach your database → Discover schema, then start shadow again."
        )
      }
      setStatusMessage("Starting shadow…")
      const updated = await startWorkflow(run.id, {
        connection_secret_arn: secret,
      })
      setRun(updated)
      if (!hasRealSfnArn(updated)) {
        throw new Error(
          "Shadow did not start. Check database attachment on Current Migration."
        )
      }
      openWatch(updated.id)
      setStatusMessage("Shadow running — live watch opened.")
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
  const shadow = liveShadow ?? extras.shadow

  return (
    <div className="mx-auto w-full max-w-[1500px] px-6 pb-10 lg:px-10">
      <nav
        aria-label="Breadcrumb"
        className="text-muted-foreground mb-4 flex flex-wrap items-center gap-1.5 font-mono text-[11px] tracking-tight"
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

      <PageHeader
        title="Shadow Execution"
        subtitle={
          <>
            {statusMessage ? (
              <span className="mt-1 block max-w-2xl text-sm leading-relaxed">
                {statusMessage}
              </span>
            ) : null}
          </>
        }
        action={run ? <StatusPill status={run.status} /> : null}
      />

      {error ? (
        <div className="mb-5">
          <ErrorNote>{error}</ErrorNote>
        </div>
      ) : null}

      {initializing ? (
        <Panel className="px-6 py-5">
          <SkeletonLines lines={5} />
        </Panel>
      ) : !run ? (
        <Panel className="flex flex-col gap-3 px-6 py-5">
          <EmptyNote>No current run. Create or select a migration first.</EmptyNote>
          <Link
            href="/dashboard/migrations/current"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-fit")}
          >
            ← Back to Current Migration
          </Link>
        </Panel>
      ) : (
        <div className="space-y-5">
          {/* Headline of this page: the customer's schema vs. what the
              migration turns it into. Rendered first and unconditionally —
              the source side is real as soon as discovery has run, so this
              never sits empty waiting on a shadow cluster. */}
          <Section title="Data columns">
            <ShadowClusterComparison
              run={run}
              shadow={shadow}
              extras={extras}
              comparisons={comparisons}
            />
          </Section>

          <Section title="Live">
            <ShadowLiveView
              run={run}
              extras={extras}
              comparisons={comparisons}
              isLive={isPolling}
              awaitingStart={awaitingStart}
              showHoldDeleteButton={false}
              showCostStrip={false}
              showComparisons={false}
              showEventLog={false}
              onShadowResolved={setLiveShadow}
            />
          </Section>

          <Section title="Controls">
            <GradeRunAction
              run={run}
              grade={extras.grade}
              onGraded={(updated) => {
                setRun(updated)
                void refreshExtras(updated)
              }}
              className="mb-4"
            />
            {run.status === "awaiting_approval" ? (
              <p className="text-muted-foreground text-sm">
                Approve on Current Migration first, then return here.
              </p>
            ) : null}

            {canStart ? (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  disabled={
                    starting ||
                    !isSfnReady(health) ||
                    (!run.connection_secret_arn &&
                      !getConnectionSecretArn().trim())
                  }
                  onClick={() => void handleStart()}
                >
                  {starting ? "Starting…" : "Start shadow test"}
                </Button>
                {!isSfnReady(health) ? (
                  <p className={cn("basis-full text-sm", toneText("fail"))}>
                    Shadow not ready — check Settings / health.
                  </p>
                ) : null}
                {!run.connection_secret_arn &&
                !getConnectionSecretArn().trim() ? (
                  <p className={cn("basis-full text-sm", toneText("fail"))}>
                    Attach a database on Current Migration first.
                  </p>
                ) : null}
              </div>
            ) : null}

            {isPolling ? (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={aborting}
                  onClick={() => void handleAbort()}
                >
                  {aborting ? "Aborting…" : "Abort"}
                </Button>
              </div>
            ) : null}

            {run.status !== "running" &&
            run.status !== "awaiting_approval" &&
            !canStart &&
            !isPolling ? (
              <p className="text-muted-foreground text-sm">
                {run.status === "completed"
                  ? "Finished."
                  : run.status === "failed"
                    ? "Failed or aborted."
                    : "Finish predict → Proceed on Current Migration first."}
              </p>
            ) : null}

            <ShadowTeardownControl shadow={shadow} />
          </Section>

          <div>
            <Link
              href="/dashboard/migrations/current"
              className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2")}
            >
              ← Current Migration
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
