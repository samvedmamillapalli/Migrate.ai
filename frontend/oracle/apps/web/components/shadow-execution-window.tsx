"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { ChevronUp, X } from "lucide-react"

import { Button, buttonVariants } from "@workspace/ui/components/button"
import { toneText } from "@workspace/ui/components/ui-kit"
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
  formatDuration,
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
// Both of these pages already render their own live shadow view — the
// dedicated shadow page (full SSE-driven panel) and Current Migration's own
// "Shadow" section (fed by that page's own usePolling, current-migration-
// workspace.tsx around line 1381). Showing + independently polling the
// floating window on top of either duplicates the same steps/comparisons on
// screen *and* doubles the live-run request rate (this widget's own 1.5s
// poll of getRun/syncWorkflow + 4 parallel GETs, stacked on that page's
// identical poll of the same run) for no visible benefit — the page's own
// section already shows the same data. Suppress the floating surface on
// both; it stays available (and remembers open/minimized state) everywhere
// else in the dashboard.
const PAGES_WITH_OWN_LIVE_SHADOW_VIEW = new Set([
  "/dashboard/migrations/current/shadow",
  "/dashboard/migrations/current",
])

export function ShadowExecutionWindow() {
  const { runId, open, minimized, closeWatch, toggleMinimized, setMinimized } =
    useShadowWatch()
  const pathname = usePathname()
  const onDedicatedPage = PAGES_WITH_OWN_LIVE_SHADOW_VIEW.has(pathname ?? "")
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
    // The design's floating "Shadow Watch" pill: dark slab, bottom-right,
    // status dot + one-line state, expand and dismiss. Every value below is
    // measured — replica provider, real duration, real error — or omitted.
    const durationLabel =
      extras.execution?.actual_duration_seconds != null
        ? formatDuration(extras.execution.actual_duration_seconds)
        : null
    return (
      <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex justify-end">
        <div className="border-border bg-foreground text-background pointer-events-auto w-[320px] rounded-xl border px-4 py-3 shadow-lg">
          <div className="flex items-start gap-2.5">
            <span
              aria-hidden
              className={cn(
                "mt-1.5 size-2 shrink-0 rounded-full",
                isLive
                  ? "animate-pulse bg-[var(--tone-warn-dot)]"
                  : extras.execution?.success === false
                    ? "bg-[var(--tone-fail-dot)]"
                    : extras.execution
                      ? "bg-[var(--tone-pass-dot)]"
                      : "bg-background/40"
              )}
            />
            <div className="min-w-0 flex-1">
              <div className="text-[11px] font-bold tracking-[0.08em] uppercase">
                Shadow Watch
              </div>
              <div className="text-background/90 mt-0.5 truncate text-[13px] font-medium">
                {isLive
                  ? "Running — expand to watch"
                  : extras.execution?.success === false
                    ? "Failed — expand for detail"
                    : extras.execution
                      ? "Finished — expand for results"
                      : `run ${runId.slice(0, 8)}`}
              </div>
              {extras.shadow || durationLabel ? (
                <div className="text-background/70 mt-2 space-y-1 font-mono text-[11px]">
                  {extras.shadow ? (
                    <div>
                      {extras.shadow.provider}
                      {extras.shadow.region ? ` · ${extras.shadow.region}` : ""}
                      {durationLabel ? ` · ${durationLabel}` : ""}
                    </div>
                  ) : durationLabel ? (
                    <div>{durationLabel}</div>
                  ) : null}
                  {extras.execution ? (
                    <div>
                      {extras.execution.rollback_required
                        ? "rollback required"
                        : "no rollback required"}
                      {extras.execution.timed_out ? " · timed out" : ""}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
            <button
              type="button"
              aria-label="Expand shadow watch"
              onClick={() => setMinimized(false)}
              className="text-background/60 hover:text-background transition-colors"
            >
              <ChevronUp className="size-4" />
            </button>
            <button
              type="button"
              aria-label="Dismiss shadow watch"
              onClick={closeWatch}
              className="text-background/60 hover:text-background transition-colors"
            >
              <X className="size-4" />
            </button>
          </div>
        </div>
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
          <p className="section-label">Shadow visualization</p>
          <p className="truncate font-mono text-xs text-foreground/85">
            run {runId.slice(0, 8)}
            {isLive ? (
              <span className={cn("ml-2", toneText("warn"))}>· live</span>
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
        {error ? <p className={cn("text-sm", toneText("fail"))}>{error}</p> : null}

        {run ? (
          <>
            <section className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <p className="section-label">
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
