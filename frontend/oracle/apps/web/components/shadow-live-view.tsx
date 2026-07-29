"use client"

import * as React from "react"

import { cn } from "@workspace/ui/lib/utils"

import {
  formatDuration,
  formatRelativeTime,
  mapCostStrip,
  mapExecutePanel,
  mapRowSamplePanel,
  mapSchemaDiff,
  mapShadowEventLog,
  mapShadowLifecycleRail,
  useShadowStream,
  type ComparisonRow,
  type LifecycleRailStage,
  type MigrationRun,
  type RowSampleTableView,
  type RunExtras,
} from "@/lib/api"

function StageDot({
  state,
}: {
  state: "pending" | "current" | "complete" | "failed"
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "size-2.5 shrink-0 rounded-full border",
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
                  stage.state === "complete" ? "bg-[var(--oracle-verified)]/50" : "bg-border"
                )}
              />
            ) : null}
          </div>
          <div>
            <p
              className={cn(
                "font-mono text-[10px] tracking-[0.1em] uppercase",
                stage.state === "current" && "text-foreground",
                stage.state === "complete" && "text-muted-foreground/70",
                stage.state === "failed" && "text-[var(--oracle-risk)]",
                stage.state === "pending" && "text-muted-foreground/35"
              )}
            >
              {stage.label}
            </p>
            <p className="text-muted-foreground/60 font-mono text-[10px] tabular-nums">
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
}: {
  currentStageId: string | null
  shadow: RunExtras["shadow"]
  costStrip: ReturnType<typeof mapCostStrip>
}) {
  if (!shadow) {
    return (
      <p className="text-muted-foreground font-mono text-xs tracking-tight">
        Waiting for the shadow cluster to be created…
      </p>
    )
  }

  if (currentStageId === "provision") {
    return (
      <div className="space-y-1.5 font-mono text-xs tracking-tight">
        <p className="text-foreground/85">
          {shadow.cluster_name || "Provisioning cluster identity…"}
        </p>
        <p className="text-muted-foreground/70">
          region: {shadow.region || "…"} · tier: {shadow.scale_tier || "…"} ·
          provider: {shadow.provider || "…"}
        </p>
      </div>
    )
  }

  if (currentStageId === "seed") {
    return (
      <div className="space-y-1 font-mono text-xs tracking-tight">
        <p className="text-foreground/85">
          Seeding tables from your discovered schema onto {shadow.cluster_name || "the shadow cluster"}…
        </p>
        <p className="text-muted-foreground/60 text-[11px] leading-relaxed">
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
          <p className="font-mono text-[10px] tracking-tight text-muted-foreground/70">
            job {exec.jobId}
          </p>
        ) : null}
        {exec.description ? (
          <pre className="border-border/50 bg-muted/20 max-h-20 overflow-auto rounded-md border p-2 font-mono text-[10px] leading-relaxed whitespace-pre-wrap">
            {exec.description}
          </pre>
        ) : null}
        <p className="text-foreground/90 font-mono text-sm tracking-tight">
          {exec.runningStatus || "Running your migration SQL…"}
        </p>
        {exec.fractionCompleted != null ? (
          <div className="space-y-1">
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-amber-400/90 transition-all"
                style={{
                  width: `${Math.max(0, Math.min(100, exec.fractionCompleted * 100))}%`,
                }}
              />
            </div>
            <p className="text-muted-foreground/60 font-mono text-[10px] tabular-nums">
              {Math.round(exec.fractionCompleted * 100)}% — reported directly by
              CockroachDB (`fraction_completed`)
            </p>
          </div>
        ) : !exec.observedLive ? (
          <p className="text-muted-foreground/55 text-[11px] leading-relaxed">
            No live job progress observed for this run — showing the
            post-execution job snapshot only, never a fabricated bar.
          </p>
        ) : null}
        {!exec.observedLive && exec.fallbackJobs.length > 0 ? (
          <ul className="space-y-1 border-t border-border/40 pt-2">
            {exec.fallbackJobs.slice(0, 5).map((j, idx) => (
              <li
                key={`${j.jobId}-${idx}`}
                className="font-mono text-[10px] tracking-tight text-muted-foreground/70"
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
      <div className="space-y-2 font-mono text-xs tracking-tight">
        <p className="text-foreground/85">
          Migration finished — measuring storage delta and diffing the
          schema before collecting results.
        </p>
        {costStrip ? (
          <p className="text-muted-foreground/70">
            {costStrip.durationLabel} · {costStrip.storageLabel} ·{" "}
            {costStrip.jobsRun} job{costStrip.jobsRun === 1 ? "" : "s"} run
          </p>
        ) : null}
      </div>
    )
  }

  // teardown
  const isDone = shadow.status === "destroyed"
  return (
    <div className="space-y-1 font-mono text-xs tracking-tight">
      <p className="text-foreground/85">
        {isDone
          ? `Cluster destroyed — ${shadow.cluster_name || "the shadow cluster"} no longer exists.`
          : `Tearing down ${shadow.cluster_name || "the shadow cluster"}…`}
      </p>
      {isDone && shadow.destroyed_at ? (
        <p className="text-muted-foreground/60">
          torn down {formatRelativeTime(shadow.destroyed_at)} — no ongoing cost.
        </p>
      ) : null}
      {shadow.error_message ? (
        <p className="text-[var(--oracle-risk)]">{shadow.error_message}</p>
      ) : null}
    </div>
  )
}

/** Band 3 — append-only event log. Never stops producing output. */
function EventLog({ shadow }: { shadow: RunExtras["shadow"] }) {
  const lines = mapShadowEventLog(shadow)
  if (lines.length === 0) {
    return (
      <p className="text-muted-foreground/60 font-mono text-[10px] tracking-tight">
        No events recorded yet.
      </p>
    )
  }
  return (
    <div className="max-h-40 space-y-0.5 overflow-y-auto font-mono text-[10px] leading-relaxed tracking-tight">
      {lines.map((line, idx) => (
        <p key={idx} className="text-muted-foreground/75">
          <span className="text-muted-foreground/45">
            {line.at ? new Date(line.at).toLocaleTimeString() : "…"}
          </span>{" "}
          {line.text}
        </p>
      ))}
    </div>
  )
}

function ComparisonsBlock({ rows }: { rows: ComparisonRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
        Pred → actual appears after measurement.
      </p>
    )
  }
  return (
    <dl className="space-y-2">
      {rows.map((row) => (
        <div
          key={row.label}
          className="grid gap-1 border-b border-border/40 pb-2 last:border-b-0 last:pb-0 sm:grid-cols-[6rem_1fr_auto] sm:items-baseline sm:gap-3"
        >
          <dt className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.1em] uppercase">
            {row.label}
          </dt>
          <dd className="text-foreground/85 font-mono text-xs tracking-tight">
            <span className="text-muted-foreground/55">pred </span>
            {row.predicted}
            <span className="text-muted-foreground/40 mx-1.5">→</span>
            <span className="text-muted-foreground/55">actual </span>
            {row.actual}
          </dd>
          {row.withinBand != null ? (
            <span
              className={cn(
                "font-mono text-[10px] tracking-tight sm:text-right",
                row.withinBand ? "text-[var(--oracle-verified)]" : "text-[var(--oracle-risk)]"
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

const DIFF_COLOR: Record<string, string> = {
  added: "text-[var(--oracle-verified)]",
  removed: "text-[var(--oracle-risk)]",
  changed: "text-amber-400/90",
  unchanged: "text-muted-foreground/45",
}

/** Schema diff — color means structural change, never quality. */
function SchemaDiffPanel({ shadow }: { shadow: RunExtras["shadow"] }) {
  const tables = mapSchemaDiff(shadow)
  const changedTables = tables.filter((t) => t.kind !== "unchanged")
  if (tables.length === 0) {
    return (
      <p className="text-muted-foreground/60 font-mono text-[11px] tracking-tight">
        Schema diff appears once before/after snapshots are captured (measure
        stage).
      </p>
    )
  }
  const toShow = changedTables.length > 0 ? changedTables : tables.slice(0, 3)
  return (
    <div className="space-y-3">
      {toShow.map((table) => (
        <div key={table.name} className="border-border/40 rounded-md border p-2.5">
          <p className={cn("font-mono text-xs tracking-tight", DIFF_COLOR[table.kind])}>
            {table.name}{" "}
            <span className="text-muted-foreground/50 text-[10px] uppercase">
              {table.kind}
            </span>
          </p>
          <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
            {table.columns
              .filter((c) => c.kind !== "unchanged")
              .map((c) => (
                <li
                  key={c.name}
                  className={cn("font-mono text-[10px] tracking-tight", DIFF_COLOR[c.kind])}
                >
                  {c.name}
                  {c.kind === "changed"
                    ? ` (${c.beforeType} → ${c.afterType})`
                    : c.type
                      ? `: ${c.type}`
                      : ""}
                </li>
              ))}
            {table.indexesAdded.map((name) => (
              <li key={`idx-add-${name}`} className="text-[var(--oracle-verified)] font-mono text-[10px]">
                +index {name}
              </li>
            ))}
            {table.indexesRemoved.map((name) => (
              <li key={`idx-rm-${name}`} className="text-[var(--oracle-risk)] font-mono text-[10px]">
                -index {name}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <p className="text-muted-foreground/55 text-[10px] leading-relaxed">
        Schema shape changes are real and match what would happen to your
        production database. Row counts and duration above are shadow-tier
        measurements, not production scale.
      </p>
    </div>
  )
}

/** Reuses the row-sample tables (real column list + real row counts) but
 * never touches `.rows` — this panel exists specifically to show table shape
 * without exposing any value, sampled or otherwise. */
function tableShapesFromShadow(shadow: RunExtras["shadow"]): RowSampleTableView[] {
  const panel = mapRowSamplePanel(shadow)
  const byName = new Map<string, RowSampleTableView>()
  for (const t of panel.before) byName.set(t.requestedName, t)
  for (const t of panel.after) byName.set(t.requestedName, t) // after wins once ready
  return Array.from(byName.values())
}

const SHAPE_ROWS_SHOWN = 6

/** One table, rendered as a column header row + a row-number column with
 * every interior cell masked — real shape, no values, forming the visible
 * "header row + row-index column" outline of the table. */
function TableShapeCard({ table }: { table: RowSampleTableView }) {
  const label = table.tableName ?? table.requestedName
  const total = table.totalRowCount ?? table.sampledCount
  const shown = Math.min(SHAPE_ROWS_SHOWN, Math.max(total, 0))
  const hasMore = total > shown

  return (
    <div className="border-border/50 rounded-md border p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-mono text-xs text-foreground/90">{label}</p>
        <span className="text-muted-foreground/60 font-mono text-[10px] tabular-nums">
          {total} row{total === 1 ? "" : "s"} × {table.columns.length} column
          {table.columns.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-max border-collapse font-mono text-[10.5px]">
          <thead>
            <tr>
              <th className="border-border/40 text-muted-foreground/50 border-b px-2 py-1 text-left align-bottom font-normal">
                #
              </th>
              {table.columns.map((c) => (
                <th
                  key={c.name}
                  className="border-border/40 text-foreground/85 border-b px-2 py-1 text-left align-bottom whitespace-nowrap"
                >
                  {c.name}
                  <span className="text-muted-foreground/45 block font-normal">
                    {c.type || "?"}
                    {c.nullable === false ? " · not null" : ""}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown === 0 ? (
              <tr>
                <td
                  colSpan={table.columns.length + 1}
                  className="text-muted-foreground/60 px-2 py-2"
                >
                  No rows.
                </td>
              </tr>
            ) : (
              Array.from({ length: shown }, (_, idx) => (
                <tr key={idx} className="border-border/20 border-b last:border-b-0">
                  <td className="text-muted-foreground/50 px-2 py-1 tabular-nums">
                    {idx + 1}
                  </td>
                  {table.columns.map((c) => (
                    <td key={c.name} className="text-muted-foreground/25 px-2 py-1">
                      ·
                    </td>
                  ))}
                </tr>
              ))
            )}
            {hasMore ? (
              <tr>
                <td className="text-muted-foreground/40 px-2 py-1">…</td>
                {table.columns.map((c) => (
                  <td key={c.name} className="text-muted-foreground/25 px-2 py-1">
                    ·
                  </td>
                ))}
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Table shape — real column names and real row counts, never a real value.
 * Distinct from the full row-samples panel (which shows real shadow-tier
 * values with its own disclaimer): this is a quick "what does this table
 * actually look like" glance that shows no data at all, not even synthetic. */
function TableShapePanel({ shadow }: { shadow: RunExtras["shadow"] }) {
  const tables = tableShapesFromShadow(shadow).filter(
    (t) => !t.error && t.columns.length > 0
  )
  if (tables.length === 0) {
    return (
      <p className="text-muted-foreground/60 font-mono text-[11px] tracking-tight">
        Table shape appears once a schema snapshot is captured.
      </p>
    )
  }
  return (
    <div className="space-y-3">
      {tables.map((t) => (
        <TableShapeCard key={t.requestedName} table={t} />
      ))}
      <p className="text-muted-foreground/55 text-[10px] leading-relaxed">
        Real column names and real row counts from the shadow cluster. Cell
        values are never shown here.
      </p>
    </div>
  )
}

export type ShadowLiveViewProps = {
  run: MigrationRun
  extras: RunExtras
  comparisons: ComparisonRow[]
  isLive?: boolean
  awaitingStart?: boolean
  children?: React.ReactNode
}

/**
 * The shadow-execution live view: lifecycle rail, stage-dependent panel,
 * event log, schema diff, cost strip. Driven by SSE when live; falls back to
 * whatever `extras.shadow` the parent already polled otherwise (and doubles
 * as the replay view for a finished run — same component, no live stream).
 */
export function ShadowLiveView({
  run,
  extras,
  comparisons,
  isLive = false,
  awaitingStart = false,
  children,
}: ShadowLiveViewProps) {
  const stream = useShadowStream(run.id, { enabled: isLive })
  const shadow = (isLive ? stream.shadow : null) ?? extras.shadow

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
        <p className="text-muted-foreground font-mono text-[11px] tracking-tight">
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
        <p className="text-muted-foreground/70 font-mono text-[10px] tabular-nums tracking-tight">
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

      <div className="border-border/60 rounded-lg border p-3.5">
        <StagePanel
          currentStageId={currentStageId}
          shadow={shadow}
          costStrip={costStrip}
        />
      </div>

      {costStrip ? (
        <div className="border-border/60 flex flex-wrap items-baseline gap-x-5 gap-y-1 rounded-lg border p-3 font-mono text-[11px] tracking-tight">
          <span className="text-muted-foreground/55 uppercase">Measured</span>
          <span className="text-foreground/85">{costStrip.durationLabel}</span>
          <span className="text-foreground/85">{costStrip.storageLabel}</span>
          <span className="text-foreground/85">
            {costStrip.jobsRun} job{costStrip.jobsRun === 1 ? "" : "s"}
          </span>
          <span
            className={cn(
              costStrip.success
                ? "text-[var(--oracle-verified)]"
                : "text-[var(--oracle-risk)]"
            )}
          >
            {costStrip.timedOut
              ? "timed out"
              : costStrip.success
                ? "succeeded"
                : "failed"}
          </span>
        </div>
      ) : null}

      <div className="space-y-2 border-t border-border/60 pt-4">
        <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
          Pred → actual
        </p>
        <ComparisonsBlock rows={comparisons} />
      </div>

      <div className="space-y-2">
        <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
          Schema diff
        </p>
        <SchemaDiffPanel shadow={shadow} />
      </div>

      <div className="space-y-2 border-t border-border/60 pt-4">
        <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
          Table shape
        </p>
        <TableShapePanel shadow={shadow} />
      </div>

      <div className="space-y-2 border-t border-border/60 pt-4">
        <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
          Event log
        </p>
        <EventLog shadow={shadow} />
      </div>

      {children}
    </div>
  )
}
