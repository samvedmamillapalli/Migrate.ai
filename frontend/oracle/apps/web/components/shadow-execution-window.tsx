"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { Button, buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

import { ShadowLiveView } from "@/components/shadow-live-view"
import { useShadowWatch } from "@/components/shadow-watch-context"
import {
  ApiError,
  getExecutionResult,
  getGrade,
  getMemory,
  getRun,
  getShadowCluster,
  hasRealSfnArn,
  mapComparisons,
  syncWorkflow,
  usePolling,
  type ExecutionResult,
  type Grade,
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
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null
    return null
  }
}

/**
 * Floating live shadow visualization — stays open while browsing the dashboard.
 * Driven entirely by real API polling (not simulated).
 */
// The dedicated shadow page already renders the full live panel; showing the
// floating window on top of it duplicates the same steps + comparisons twice
// on screen at once. Suppress the floating surface there — it stays available
// (and remembers open/minimized state) everywhere else in the dashboard.
const DEDICATED_SHADOW_PAGE = "/dashboard/migrations/current/shadow"

export function ShadowExecutionWindow() {
  const { runId, open, minimized, closeWatch, toggleMinimized, setMinimized } =
    useShadowWatch()
  const pathname = usePathname()
  const onDedicatedPage = pathname === DEDICATED_SHADOW_PAGE
  const [run, setRun] = React.useState<MigrationRun | null>(null)
  const [extras, setExtras] = React.useState<RunExtras>(EMPTY_EXTRAS)
  const [error, setError] = React.useState<string | null>(null)
  const [showSql, setShowSql] = React.useState(false)

  const refreshExtras = React.useCallback(async (current: MigrationRun) => {
    const [shadow, execution, grade, memory] = await Promise.all([
      safeGet(() => getShadowCluster(current.id)),
      safeGet(() => getExecutionResult(current.id)),
      safeGet(() => getGrade(current.id)),
      safeGet(() => getMemory(current.id)),
    ])
    setExtras({
      shadow: shadow as ShadowCluster | null,
      execution: execution as ExecutionResult | null,
      grade: grade as Grade | null,
      memory: memory as Memory | null,
    })
  }, [])

  React.useEffect(() => {
    if (!open || !runId) {
      setRun(null)
      setExtras(EMPTY_EXTRAS)
      return
    }
    let cancelled = false
    async function load() {
      try {
        const current = await getRun(runId!)
        if (cancelled) return
        setRun(current)
        setError(null)
        await refreshExtras(current)
      } catch (err) {
        if (cancelled) return
        setError(
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Failed to load shadow run"
        )
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [open, runId, refreshExtras])

  const isLive =
    Boolean(run) &&
    (run!.workflow_status === "running" ||
      (run!.status === "running" && hasRealSfnArn(run!)))

  usePolling(
    async () => {
      if (!runId || !run) return
      try {
        let current = run
        if (hasRealSfnArn(run) && run.workflow_status === "running") {
          current = await syncWorkflow(runId)
          setRun(current)
        } else {
          current = await getRun(runId)
          setRun(current)
        }
        await refreshExtras(current)
      } catch {
        /* ignore transient poll errors */
      }
    },
    {
      enabled: open && !minimized && !onDedicatedPage && Boolean(runId) && isLive,
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

  if (!open || !runId || onDedicatedPage) return null

  const comparisons = run ? mapComparisons(run, extras) : []

  if (minimized) {
    return (
      <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex justify-end">
        <button
          type="button"
          onClick={() => setMinimized(false)}
          className={cn(
            "pointer-events-auto flex items-center gap-3 rounded-lg border border-border/80",
            "bg-background/95 px-4 py-3 text-left shadow-lg backdrop-blur-md",
            "hover:border-amber-400/40 transition-colors"
          )}
        >
          <span
            aria-hidden
            className={cn(
              "size-2 shrink-0 rounded-full",
              isLive
                ? "bg-amber-400 animate-pulse"
                : extras.execution
                  ? "bg-[var(--oracle-verified)]"
                  : "bg-muted-foreground/40"
            )}
          />
          <span className="min-w-0">
            <span className="block font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
              Shadow watch
            </span>
            <span className="block truncate font-mono text-xs text-foreground/85">
              {run
                ? isLive
                  ? "Live cluster running…"
                  : extras.execution
                    ? "Finished — expand for results"
                    : `run ${runId.slice(0, 8)}`
                : `run ${runId.slice(0, 8)}`}
            </span>
          </span>
        </button>
      </div>
    )
  }

  return (
    <div
      role="dialog"
      aria-label="Shadow cluster visualization"
      className={cn(
        "fixed right-3 bottom-3 z-50 flex max-h-[min(85vh,720px)] w-[min(100vw-1.5rem,28rem)]",
        "flex-col overflow-hidden rounded-xl border border-border/80",
        "bg-background/95 shadow-2xl backdrop-blur-md sm:right-4 sm:bottom-4 sm:w-[min(100vw-2rem,32rem)]"
      )}
    >
      <header className="flex shrink-0 items-start justify-between gap-2 border-b border-border/60 px-4 py-3">
        <div className="min-w-0 space-y-0.5">
          <p className="font-mono text-[10px] tracking-[0.16em] text-muted-foreground uppercase">
            Shadow visualization
          </p>
          <p className="truncate font-mono text-xs text-foreground/85">
            run {runId.slice(0, 8)}
            {isLive ? (
              <span className="ml-2 text-amber-400/90">· live</span>
            ) : null}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 font-mono text-[10px]"
            onClick={toggleMinimized}
          >
            Min
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 font-mono text-[10px]"
            onClick={closeWatch}
          >
            Close
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {error ? (
          <p className="text-sm text-[var(--oracle-risk)]">{error}</p>
        ) : null}

        {run ? (
          <>
            <section className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-mono text-[10px] tracking-[0.12em] text-muted-foreground uppercase">
                  {isLive ? "Live" : extras.execution ? "Done" : "Shadow"}
                </p>
                <button
                  type="button"
                  className="font-mono text-[10px] tracking-tight text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  onClick={() => setShowSql((v) => !v)}
                >
                  {showSql ? "Hide SQL" : "SQL"}
                </button>
              </div>
              {showSql ? (
                <pre className="max-h-32 overflow-auto rounded-md border border-border/50 bg-muted/20 p-2 font-mono text-[10px] leading-relaxed whitespace-pre-wrap">
                  {run.migration_sql}
                </pre>
              ) : null}
            </section>

            <ShadowLiveView
              run={run}
              extras={extras}
              comparisons={comparisons}
              isLive={isLive}
              awaitingStart={
                run.status === "running" &&
                !hasRealSfnArn(run) &&
                run.workflow_status === "not_started"
              }
            />
          </>
        ) : (
          <p className="font-mono text-xs text-muted-foreground">Loading…</p>
        )}
      </div>

      <footer className="flex shrink-0 flex-wrap items-center gap-2 border-t border-border/60 px-4 py-2.5">
        <Link
          href="/dashboard/migrations/current/shadow"
          className={cn(
            buttonVariants({ variant: "outline", size: "sm" }),
            "font-mono text-[10px]"
          )}
        >
          Full shadow page
        </Link>
        <Link
          href="/dashboard/migrations/current"
          className={cn(
            buttonVariants({ variant: "ghost", size: "sm" }),
            "font-mono text-[10px]"
          )}
        >
          Current migration
        </Link>
      </footer>
    </div>
  )
}
