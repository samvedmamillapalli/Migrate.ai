"use client"

import type { ReactNode } from "react"

import { cn } from "@workspace/ui/lib/utils"

import {
  formatRelativeTime,
  mapShadowLiveStages,
  type ComparisonRow,
  type MigrationRun,
  type RunExtras,
} from "@/lib/api"

function StageDot({ state }: { state: "pending" | "current" | "complete" | "failed" }) {
  return (
    <span
      aria-hidden
      className={cn(
        "mt-1 size-2.5 shrink-0 rounded-full border",
        state === "complete" &&
          "border-[var(--oracle-verified)] bg-[var(--oracle-verified)]",
        state === "current" &&
          "border-amber-400 bg-amber-400/90 animate-pulse shadow-[0_0_0_3px_rgba(251,191,36,0.2)]",
        state === "failed" && "border-[var(--oracle-risk)] bg-[var(--oracle-risk)]",
        state === "pending" && "border-muted-foreground/30 bg-transparent"
      )}
    />
  )
}

function Comparisons({ rows }: { rows: ComparisonRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
        Pred → actual appears after measurement.
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
                <span className="text-muted-foreground/55">pred </span>
                {row.predicted}
                <span className="text-muted-foreground/40 mx-1.5">→</span>
                <span className="text-muted-foreground/55">actual </span>
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

export type ShadowLivePanelProps = {
  run: MigrationRun
  extras: RunExtras
  comparisons: ComparisonRow[]
  /** Workflow is actively executing (poll live). */
  isLive?: boolean
  /** Approved / ready but SFN not kicked off yet. */
  awaitingStart?: boolean
  children?: ReactNode
}

/**
 * Real-time shadow cluster box: full step playbook + live status/timings,
 * plus prediction vs measured actuals (no mock numbers).
 */
export function ShadowLivePanel({
  run,
  extras,
  comparisons,
  isLive = false,
  awaitingStart = false,
  children,
}: ShadowLivePanelProps) {
  const shadow = extras.shadow
  const workflowRunning =
    isLive ||
    run.workflow_status === "running" ||
    (run.status === "running" && Boolean(run.sfn_execution_arn))

  const stages = mapShadowLiveStages(shadow, {
    workflowRunning,
    hasExecution: Boolean(extras.execution),
    awaitingStart,
  })

  const provider = shadow?.provider
  const isRealProvider =
    provider != null && provider !== "mock" && !provider.includes("mock")

  const current = stages.find((s) => s.state === "current")
  const doneCount = stages.filter((s) => s.state === "complete").length

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-muted-foreground font-mono text-[11px] tracking-tight">
          {isLive
            ? "Live"
            : awaitingStart
              ? "Ready to start"
              : shadow
                ? "Shadow steps"
                : "Waiting"}
        </p>
        <p className="text-muted-foreground/70 font-mono text-[10px] tabular-nums tracking-tight">
          {doneCount}/{stages.length}
          {current ? ` · ${current.label.replace(/^\d+\.\s*/, "")}` : null}
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <ol className="relative space-y-0">
          {stages.map((stage, idx) => (
            <li key={stage.id} className="relative flex gap-3 pb-4 last:pb-0">
              {idx < stages.length - 1 ? (
                <span
                  aria-hidden
                  className={cn(
                    "absolute top-3 left-[4px] h-[calc(100%-4px)] w-px",
                    stage.state === "complete"
                      ? "bg-[var(--oracle-verified)]/50"
                      : "bg-border"
                  )}
                />
              ) : null}
              <StageDot state={stage.state} />
              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p
                    className={cn(
                      "text-sm font-medium tracking-tight",
                      stage.state === "current" && "text-foreground",
                      stage.state === "complete" && "text-foreground/85",
                      stage.state === "failed" && "text-[var(--oracle-risk)]",
                      stage.state === "pending" && "text-muted-foreground/60"
                    )}
                  >
                    {stage.label}
                    {stage.state === "current" ? (
                      <span className="ml-2 font-mono text-[10px] tracking-[0.14em] text-amber-400/90 uppercase">
                        now
                      </span>
                    ) : null}
                    {stage.state === "complete" ? (
                      <span className="ml-2 font-mono text-[10px] tracking-[0.14em] text-[var(--oracle-verified)] uppercase">
                        done
                      </span>
                    ) : null}
                  </p>
                  <span className="font-mono text-[10px] tabular-nums tracking-tight text-muted-foreground/75">
                    {stage.durationLabel
                      ? stage.durationLabel
                      : stage.state === "current"
                        ? "…"
                        : stage.state === "pending"
                          ? "—"
                          : ""}
                  </span>
                </div>
                {stage.state === "current" || stage.state === "failed" ? (
                  <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground/80">
                    {stage.hint}
                  </p>
                ) : null}
                {stage.detail ? (
                  <p className="text-muted-foreground/65 mt-1 truncate font-mono text-[10px] tracking-tight">
                    {stage.detail}
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ol>

        <div className="space-y-3">
          <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
            Cluster
          </p>
          {shadow ? (
            <dl className="space-y-1.5 font-mono text-[11px] tracking-tight">
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground/60">Status</dt>
                <dd className="text-foreground/85">{shadow.status}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground/60">Region</dt>
                <dd className="text-foreground/85">{shadow.region || "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground/60">Scale</dt>
                <dd className="text-foreground/85">
                  {shadow.scale_tier || "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground/60">Torn down</dt>
                <dd className="text-foreground/85">
                  {shadow.destroyed_at
                    ? formatRelativeTime(shadow.destroyed_at)
                    : "still live"}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="text-muted-foreground/70 text-xs">
              Cluster details appear when provisioning starts.
            </p>
          )}
          {shadow?.error_message ? (
            <p className="font-mono text-xs leading-relaxed text-[var(--oracle-risk)]">
              {shadow.error_message}
            </p>
          ) : null}
          {!isRealProvider && shadow ? (
            <p className="text-xs text-[var(--oracle-risk)]">
              Not a real cloud cluster ({shadow.provider}).
            </p>
          ) : null}
        </div>
      </div>

      <div className="border-border/60 space-y-3 border-t pt-4">
        <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
          Pred → actual
        </p>
        <Comparisons rows={comparisons} />
      </div>

      {children}
    </div>
  )
}
