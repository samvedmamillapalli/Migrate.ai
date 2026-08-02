"use client"

import * as React from "react"

import { cn } from "@workspace/ui/lib/utils"
import { Label, ToneDot, toneText, type Tone } from "@workspace/ui/components/ui-kit"

import {
  formatDuration,
  formatRelativeTime,
  mapCostStrip,
  mapExecutePanel,
  mapShadowEventLog,
  mapShadowHold,
  mapShadowLifecycleRail,
  teardownShadowClusterNow,
  useShadowStream,
  type ComparisonRow,
  type LifecycleRailStage,
  type MigrationRun,
  type RunExtras,
} from "@/lib/api"

const STAGE_TONE: Record<"pending" | "current" | "complete" | "failed", Tone> = {
  pending: "neutral",
  current: "warn",
  complete: "pass",
  failed: "fail",
}

function StageDot({
  state,
}: {
  state: "pending" | "current" | "complete" | "failed"
}) {
  return (
    <ToneDot
      tone={STAGE_TONE[state]}
      className={cn(
        "size-2.5 ring-2 ring-transparent",
        state === "current" && "animate-pulse"
      )}
    />
  )
}

/** Band 1 — the lifecycle rail. Always visible, doesn't change shape. */
function LifecycleRail({
  stages,
  elapsedLabel,
}: {
  stages: LifecycleRailStage[]
  elapsedLabel: string | null
}) {
  return (
    <ol className="flex items-stretch gap-0">
      {stages.map((stage, idx) => (
        <li key={stage.id} className="relative flex flex-1 flex-col gap-1.5">
          <div className="flex items-center gap-1.5">
            <StageDot state={stage.state} />
            {idx < stages.length - 1 ? (
              <span
                aria-hidden
                className={cn(
                  "h-px flex-1",
                  stage.state === "complete" ? "bg-[var(--tone-pass-border)]" : "bg-border"
                )}
              />
            ) : null}
          </div>
          <div>
            <p
              className={cn(
                "section-label",
                stage.state === "current" && "text-foreground",
                stage.state === "failed" && toneText("fail")
              )}
            >
              {stage.label}
            </p>
            <p className="text-muted-foreground/70 text-[11px] tabular-nums">
              {stage.state === "current"
                ? elapsedLabel || "…"
                : stage.durationLabel || (stage.state === "pending" ? "—" : "")}
            </p>
          </div>
        </li>
      ))}
    </ol>
  )
}

/** Band 2 — content that changes depending on which stage is active. */
function StagePanel({
  currentStageId,
  shadow,
  costStrip,
  showHoldDeleteButton = true,
}: {
  currentStageId: string | null
  shadow: RunExtras["shadow"]
  costStrip: ReturnType<typeof mapCostStrip>
  showHoldDeleteButton?: boolean
}) {
  if (!shadow) {
    return (
      <p className="text-muted-foreground text-[13px]">
        Waiting for the shadow cluster to be created…
      </p>
    )
  }

  if (currentStageId === "provision") {
    return (
      <div className="space-y-1.5 text-[13px]">
        <p className="text-foreground font-mono">
          {shadow.cluster_name || "Provisioning cluster identity…"}
        </p>
        <p className="text-muted-foreground font-mono text-[12px]">
          region: {shadow.region || "…"} · tier: {shadow.scale_tier || "…"} ·
          provider: {shadow.provider || "…"}
        </p>
      </div>
    )
  }

  if (currentStageId === "seed") {
    return (
      <div className="space-y-1.5 text-[13px]">
        <p className="text-foreground">
          Seeding tables from your discovered schema onto {shadow.cluster_name || "the shadow cluster"}…
        </p>
        <p className="text-muted-foreground text-[12px] leading-relaxed">
          Rows are synthetic and tier-capped — this measures schema-load
          time, not your production data volume.
        </p>
      </div>
    )
  }

  if (currentStageId === "execute") {
    const exec = mapExecutePanel(shadow)
    return (
      <div className="space-y-2">
        {exec.jobId ? (
          <p className="text-muted-foreground font-mono text-[11px] tracking-tight">
            job {exec.jobId}
          </p>
        ) : null}
        {exec.description ? (
          <pre className="border-border bg-muted/40 max-h-20 overflow-auto rounded-md border p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
            {exec.description}
          </pre>
        ) : null}
        <p className="text-foreground text-sm font-medium tracking-tight">
          {exec.runningStatus || "Running your migration SQL…"}
        </p>
        {exec.fractionCompleted != null ? (
          <div className="space-y-1">
            <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
              <div
                className="h-full rounded-full bg-[var(--tone-warn-dot)] transition-all"
                style={{
                  width: `${Math.max(0, Math.min(100, exec.fractionCompleted * 100))}%`,
                }}
              />
            </div>
            <p className="text-muted-foreground text-[11px] tabular-nums">
              {Math.round(exec.fractionCompleted * 100)}% — reported directly by
              CockroachDB (`fraction_completed`)
            </p>
          </div>
        ) : !exec.observedLive ? (
          <p className="text-muted-foreground text-[12px] leading-relaxed">
            No live job progress observed for this run — showing the
            post-execution job snapshot only, never a fabricated bar.
          </p>
        ) : null}
        {!exec.observedLive && exec.fallbackJobs.length > 0 ? (
          <ul className="border-border space-y-1 border-t pt-2">
            {exec.fallbackJobs.slice(0, 5).map((j, idx) => (
              <li
                key={`${j.jobId}-${idx}`}
                className="text-muted-foreground font-mono text-[11px] tracking-tight"
              >
                {j.jobType || "job"} · {j.status || "?"} —{" "}
                {j.description || "no description"}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    )
  }

  if (currentStageId === "measure") {
    return (
      <div className="space-y-2 text-[13px]">
        <p className="text-foreground">
          Migration finished — measuring storage delta and diffing the
          schema before collecting results.
        </p>
        {costStrip ? (
          <p className="text-muted-foreground">
            {costStrip.durationLabel} · {costStrip.storageLabel} ·{" "}
            {costStrip.jobsRun} job{costStrip.jobsRun === 1 ? "" : "s"} run
          </p>
        ) : null}
      </div>
    )
  }

  // teardown
  if (shadow.status === "holding") {
    return <HoldingPanel shadow={shadow} showDeleteButton={showHoldDeleteButton} />
  }
  const isDone = shadow.status === "destroyed"
  return (
    <div className="space-y-1.5 text-[13px]">
      <p className="text-foreground">
        {isDone
          ? `Cluster destroyed — ${shadow.cluster_name || "the shadow cluster"} no longer exists.`
          : `Tearing down ${shadow.cluster_name || "the shadow cluster"}…`}
      </p>
      {isDone && shadow.destroyed_at ? (
        <p className="text-muted-foreground">
          torn down {formatRelativeTime(shadow.destroyed_at)} — no ongoing cost.
        </p>
      ) : null}
      {shadow.error_message ? (
        <p className={toneText("fail")}>{shadow.error_message}</p>
      ) : null}
    </div>
  )
}

/** Execute+measure are done, but the cluster is deliberately held (not torn
 * down) so the row-sample/schema-diff data stays inspectable — see
 * ShadowClusterStatus.HOLDING. Ticks its own countdown locally (no extra
 * polling needed) and lets the user end the hold immediately. */
function HoldingPanel({
  shadow,
  showDeleteButton = true,
}: {
  shadow: NonNullable<RunExtras["shadow"]>
  /** False where the host page already renders its own teardown control, so
   * the same action isn't offered twice on one screen. */
  showDeleteButton?: boolean
}) {
  const [now, setNow] = React.useState(() => Date.now())
  const [deleting, setDeleting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const hold = mapShadowHold(shadow, now)

  const handleDeleteNow = async () => {
    setDeleting(true)
    setError(null)
    try {
      await teardownShadowClusterNow(shadow.migration_run_id)
      // Deliberately leave `deleting` true — the next live-stream/poll tick
      // will flip status to destroying/destroyed and this panel unmounts.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete shadow cluster")
      setDeleting(false)
    }
  }

  const label =
    hold.secondsRemaining == null
      ? "any moment now"
      : hold.secondsRemaining >= 60
        ? `${Math.floor(hold.secondsRemaining / 60)}m ${hold.secondsRemaining % 60}s`
        : `${hold.secondsRemaining}s`

  return (
    <div className="space-y-2.5 text-[13px]">
      <p className="text-foreground">
        {shadow.cluster_name || "The shadow cluster"} is still live — held for
        inspection.
      </p>
      <p className="text-muted-foreground">
        Auto-deletes in {label}. Look over the Data columns comparison above,
        then delete it early if you are done looking — no need to wait.
      </p>
      {showDeleteButton ? (
        <button
          type="button"
          onClick={handleDeleteNow}
          disabled={deleting}
          className={cn(
            "rounded-md border px-2.5 py-1.5 text-[12px] font-semibold transition-colors",
            "border-[var(--tone-fail-border)]",
            toneText("fail"),
            "hover:bg-[var(--tone-fail-bg)] disabled:opacity-50"
          )}
        >
          {deleting ? "Deleting…" : "Delete now"}
        </button>
      ) : null}
      {error ? <p className={toneText("fail")}>{error}</p> : null}
    </div>
  )
}

/** Band 3 — append-only event log. Never stops producing output. */
/** Exported for reuse by `ShadowClusterComparison`'s "Event log" accordion on
 * the standalone Shadow Execution page. */
export function EventLog({ shadow }: { shadow: RunExtras["shadow"] }) {
  const lines = mapShadowEventLog(shadow)
  if (lines.length === 0) {
    return (
      <p className="text-muted-foreground text-[12px]">
        No events recorded yet.
      </p>
    )
  }
  return (
    <div className="max-h-40 space-y-1 overflow-y-auto font-mono text-[11px] leading-relaxed tracking-tight">
      {lines.map((line, idx) => (
        <p key={idx} className="text-muted-foreground">
          <span className="text-muted-foreground/60">
            {line.at ? new Date(line.at).toLocaleTimeString() : "…"}
          </span>{" "}
          {line.text}
        </p>
      ))}
    </div>
  )
}

/** Exported for reuse by `ShadowClusterComparison`'s "Prediction vs. actual"
 * accordion on the standalone Shadow Execution page. */
export function ComparisonsBlock({ rows }: { rows: ComparisonRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground text-[12px]">
        Pred → actual appears after measurement.
      </p>
    )
  }
  return (
    <dl className="space-y-2">
      {rows.map((row) => (
        <div
          key={row.label}
          className="border-border grid gap-1 border-b pb-2 last:border-b-0 last:pb-0 sm:grid-cols-[6rem_1fr_auto] sm:items-baseline sm:gap-3"
        >
          <dt className="section-label">{row.label}</dt>
          <dd className="text-foreground font-mono text-[12.5px] tracking-tight">
            <span className="text-muted-foreground">pred </span>
            {row.predicted}
            <span className="text-muted-foreground/50 mx-1.5">→</span>
            <span className="text-muted-foreground">actual </span>
            {row.actual}
          </dd>
          {row.withinBand != null ? (
            <span
              className={cn(
                "text-[11px] tracking-tight sm:text-right",
                row.withinBand ? toneText("pass") : toneText("fail")
              )}
            >
              {row.withinBand ? "within band" : "outside band"}
            </span>
          ) : null}
        </div>
      ))}
    </dl>
  )
}

export type ShadowLiveViewProps = {
  run: MigrationRun
  extras: RunExtras
  comparisons: ComparisonRow[]
  isLive?: boolean
  awaitingStart?: boolean
  /** False where the host page renders its own teardown control instead. */
  showHoldDeleteButton?: boolean
  /** False where the host page renders its own measured/pred-vs-actual/event
   * log presentation instead (the standalone Shadow Execution page groups
   * these into its own "Technical details" accordions). Default true so the
   * other three embeds of this component (Current Migration workspace,
   * migrations/[id], the execution overlay window) keep their existing,
   * always-visible layout unchanged. */
  showCostStrip?: boolean
  showComparisons?: boolean
  showEventLog?: boolean
  /**
   * Receives the shadow row this view actually resolved to (SSE frame when
   * live, polled `extras.shadow` otherwise). Lets a host page render off the
   * same live value without opening a second EventSource to the same stream.
   */
  onShadowResolved?: (shadow: RunExtras["shadow"]) => void
  children?: React.ReactNode
}

/**
 * The shadow-execution live view: lifecycle rail, stage-dependent panel, cost
 * strip, pred-vs-actual, event log. Driven by SSE when live; falls back to
 * whatever `extras.shadow` the parent already polled otherwise (and doubles
 * as the replay view for a finished run — same component, no live stream).
 * Schema/column detail lives in `ShadowClusterComparison` instead, not here.
 */
export function ShadowLiveView({
  run,
  extras,
  comparisons,
  isLive = false,
  awaitingStart = false,
  showHoldDeleteButton = true,
  showCostStrip = true,
  showComparisons = true,
  showEventLog = true,
  onShadowResolved,
  children,
}: ShadowLiveViewProps) {
  const stream = useShadowStream(run.id, { enabled: isLive })
  const shadow = (isLive ? stream.shadow : null) ?? extras.shadow

  React.useEffect(() => {
    onShadowResolved?.(shadow)
  }, [shadow, onShadowResolved])

  const stages = mapShadowLifecycleRail(shadow, { workflowRunning: isLive, awaitingStart })
  const current = stages.find((s) => s.state === "current")
  const currentStageId = current?.id ?? null
  const costStrip = mapCostStrip({ ...extras, shadow })

  const [elapsedMs, setElapsedMs] = React.useState(0)
  const stageStartRef = React.useRef<{ id: string | null; startedAt: number }>({
    id: null,
    startedAt: 0,
  })
  React.useEffect(() => {
    if (stageStartRef.current.id !== currentStageId) {
      stageStartRef.current = { id: currentStageId, startedAt: Date.now() }
      setElapsedMs(0)
    }
  }, [currentStageId])
  React.useEffect(() => {
    if (!currentStageId) return
    const id = setInterval(() => {
      setElapsedMs(Date.now() - stageStartRef.current.startedAt)
    }, 1000)
    return () => clearInterval(id)
  }, [currentStageId])

  const isReplay = !isLive && Boolean(shadow) && !current
  const doneCount = stages.filter((s) => s.state === "complete").length

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground text-[13px]">
          {isLive
            ? stream.connected
              ? "Live"
              : "Live · reconnecting…"
            : isReplay
              ? "Replay of a real recorded run"
              : awaitingStart
                ? "Ready to start"
                : shadow
                  ? "Shadow steps"
                  : "Waiting"}
        </p>
        <p className="text-muted-foreground text-[11px] tabular-nums">
          {doneCount}/{stages.length}
          {current ? ` · ${current.label}` : null}
        </p>
      </div>

      <LifecycleRail
        stages={stages}
        elapsedLabel={
          currentStageId ? formatDuration(Math.max(0, elapsedMs) / 1000) : null
        }
      />

      <div className="border-border bg-card rounded-lg border p-4">
        <StagePanel
          currentStageId={currentStageId}
          shadow={shadow}
          costStrip={costStrip}
          showHoldDeleteButton={showHoldDeleteButton}
        />
      </div>

      {showCostStrip && costStrip ? (
        <div className="border-border bg-card flex flex-wrap items-baseline gap-x-5 gap-y-1 rounded-lg border p-3.5 text-[12.5px]">
          <span className="section-label">Measured</span>
          <span className="text-foreground">{costStrip.durationLabel}</span>
          <span className="text-foreground">{costStrip.storageLabel}</span>
          <span className="text-foreground">
            {costStrip.jobsRun} job{costStrip.jobsRun === 1 ? "" : "s"}
          </span>
          <span className={costStrip.success ? toneText("pass") : toneText("fail")}>
            {costStrip.timedOut
              ? "timed out"
              : costStrip.success
                ? "succeeded"
                : "failed"}
          </span>
        </div>
      ) : null}

      {showComparisons ? (
        <div className="border-border space-y-2.5 border-t pt-4">
          <Label>Pred → actual</Label>
          <ComparisonsBlock rows={comparisons} />
        </div>
      ) : null}

      {showEventLog ? (
        <div className="border-border space-y-2.5 border-t pt-4">
          <Label>Event log</Label>
          <EventLog shadow={shadow} />
        </div>
      ) : null}

      {children}
    </div>
  )
}
