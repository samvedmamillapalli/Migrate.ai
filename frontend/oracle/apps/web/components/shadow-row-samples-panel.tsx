"use client"

import * as React from "react"

import {
  isCellChanged,
  mapUnifiedTableDiff,
  type ShadowCluster,
  type UnifiedDiffColumnView,
  type UnifiedDiffRowView,
  type UnifiedTableDiffView,
} from "@/lib/api"
import { cn } from "@workspace/ui/lib/utils"

const HEADER_TEXT: Record<UnifiedDiffColumnView["diffKind"], string> = {
  added: "text-[var(--oracle-verified)]",
  removed: "text-[var(--oracle-risk)]",
  changed: "text-amber-400/90",
  unchanged: "text-muted-foreground/70",
}

const ROWS_SHOWN_DEFAULT = 6

function formatCell(value: unknown): string {
  if (value === undefined) return ""
  if (value === null) return "null"
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

/** A column only exists on one side of a migration that adds or removes it —
 * the other side renders a ghost placeholder in its place so both boxes stay
 * column-for-column aligned instead of silently reflowing. */
function isGhostOnSide(
  column: UnifiedDiffColumnView,
  side: "before" | "after"
): boolean {
  if (side === "before") return column.diffKind === "added"
  return column.diffKind === "removed"
}

/** One full side (Before or After) of the diff — every real column the
 * table has on that side, every sampled row, real values. Both sides render
 * from the exact same column list and the exact same row array (paired by
 * primary key upstream in mapUnifiedTableDiff) so they're guaranteed to line
 * up row-for-row and column-for-column; only the highlighting differs. */
function SideTable({
  side,
  columns,
  rows,
}: {
  side: "before" | "after"
  columns: UnifiedDiffColumnView[]
  rows: UnifiedDiffRowView[]
}) {
  return (
    <div className="border-border/50 overflow-hidden rounded-lg border">
      <div className="bg-muted/10 border-border/50 flex items-center justify-between border-b px-3.5 py-2">
        <span className="text-muted-foreground/60 font-mono text-[9.5px] tracking-[0.16em] uppercase">
          {side === "before" ? "Before" : "After"}
        </span>
        <span className="text-muted-foreground/50 font-mono text-[10px] tabular-nums">
          {columns.length} column{columns.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-max border-collapse font-mono text-[10.5px]">
          <thead>
            <tr>
              {columns.map((c) => {
                const ghost = isGhostOnSide(c, side)
                return (
                  <th
                    key={c.name}
                    className={cn(
                      "border-border/40 border-b px-2.5 py-1.5 text-left align-bottom whitespace-nowrap",
                      ghost ? "text-muted-foreground/35 italic" : HEADER_TEXT[c.diffKind],
                      !ghost &&
                        side === "after" &&
                        c.diffKind === "added" &&
                        "bg-[var(--oracle-verified)]/10",
                      !ghost &&
                        side === "before" &&
                        c.diffKind === "removed" &&
                        "bg-[var(--oracle-risk)]/10 line-through decoration-[var(--oracle-risk)]/50"
                    )}
                  >
                    {c.name}
                    <span className="text-muted-foreground/45 mt-0.5 block font-normal not-italic">
                      {ghost
                        ? side === "before"
                          ? "did not exist yet"
                          : "no longer exists"
                        : c.type || "?"}
                      {!ghost && c.isPrimaryKey ? " · pk" : ""}
                    </span>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={Math.max(columns.length, 1)}
                  className="text-muted-foreground/60 px-2.5 py-2"
                >
                  No rows.
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.key} className="border-border/20 border-b last:border-b-0">
                  {columns.map((c) => {
                    if (isGhostOnSide(c, side)) {
                      return (
                        <td
                          key={c.name}
                          className="text-muted-foreground/25 px-2.5 py-1 whitespace-nowrap"
                        >
                          —
                        </td>
                      )
                    }
                    const record = side === "before" ? row.before : row.after
                    const has = record != null && c.name in record
                    const changed = side === "after" && isCellChanged(row, c.name, c.diffKind)
                    return (
                      <td
                        key={c.name}
                        className={cn(
                          "px-2.5 py-1 whitespace-nowrap",
                          has ? "text-foreground/80" : "text-muted-foreground/30",
                          side === "after" &&
                            c.diffKind === "added" &&
                            "bg-[var(--oracle-verified)]/8",
                          side === "before" &&
                            c.diffKind === "removed" &&
                            "bg-[var(--oracle-risk)]/8",
                          changed && "bg-amber-400/15 text-amber-200"
                        )}
                      >
                        {record ? (has ? formatCell(record[c.name]) : "—") : "—"}
                      </td>
                    )
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** One table: two equal, identically-styled boxes (Before / After) showing
 * every real column the table has — no curation — with the diff carried
 * entirely by color (green = added, red = removed, amber = a changed value
 * within a matched row) rather than by hiding anything. Row count is capped
 * with an expand toggle since a table can have up to 20 sampled rows; the
 * column list is never capped. */
function TableDiffCard({ table }: { table: UnifiedTableDiffView }) {
  const [showAllRows, setShowAllRows] = React.useState(false)
  const label = table.tableName ?? table.requestedName

  if (table.error) {
    return (
      <div className="border-border/50 rounded-md border p-3">
        <p className="font-mono text-xs text-foreground/85">{label}</p>
        <p className="text-muted-foreground/70 mt-1.5 text-[11px] leading-relaxed">
          Row sample unavailable: {table.error}
        </p>
      </div>
    )
  }

  if (table.columns.length === 0) {
    return (
      <p className="text-muted-foreground/60 font-mono text-[11px]">No columns captured.</p>
    )
  }

  const rowsShown = showAllRows ? table.rows.length : ROWS_SHOWN_DEFAULT
  const visibleRows = table.rows.slice(0, rowsShown)
  const hasMoreRows = table.rows.length > rowsShown

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-mono text-xs text-foreground/90">{label}</p>
        <span className="text-muted-foreground/60 font-mono text-[10px] tabular-nums">
          {table.totalRowCount != null
            ? visibleRows.length < table.totalRowCount
              ? `${visibleRows.length} of ${table.totalRowCount} rows`
              : `${table.totalRowCount} row${table.totalRowCount === 1 ? "" : "s"}`
            : `${table.sampledCount} rows`}
          {table.matchedByPk ? " · matched by primary key" : ""}
        </span>
      </div>
      {table.note ? (
        <p className="text-amber-400/80 text-[10px] leading-relaxed">{table.note}</p>
      ) : null}

      <div className="text-muted-foreground/60 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10px]">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 rounded-sm bg-[var(--oracle-verified)]" />
          added
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 rounded-sm bg-[var(--oracle-risk)]" />
          removed
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 rounded-sm bg-amber-400" />
          changed
        </span>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <SideTable side="before" columns={table.columns} rows={visibleRows} />
        <SideTable side="after" columns={table.columns} rows={visibleRows} />
      </div>

      {hasMoreRows || showAllRows ? (
        <button
          type="button"
          onClick={() => setShowAllRows((v) => !v)}
          className="text-muted-foreground/60 hover:text-foreground/80 font-mono text-[10px] underline-offset-2 hover:underline"
        >
          {showAllRows ? "Show fewer rows" : `Show all ${table.rows.length} sampled rows`}
        </button>
      ) : null}
    </div>
  )
}

/**
 * Real before/after row samples, above the lifecycle timeline on the full
 * Shadow Execution page only (not the compact ShadowLiveView, which keeps
 * its own masked structural-only table-shape view for the smaller floating
 * window). Two equal, identically-styled boxes per table — every real
 * column shown on both sides, ghosted where a column doesn't exist on that
 * side — with green/red/amber carrying the diff. Renders instantly from
 * persisted data for a replayed/finished run — no polling.
 */
export function ShadowRowSamplesPanel({ shadow }: { shadow: ShadowCluster | null }) {
  const view = mapUnifiedTableDiff(shadow)

  return (
    <section
      aria-label="Row samples"
      className="border-border flex w-full flex-col gap-3 rounded-lg border p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-muted-foreground text-[11px] font-medium tracking-[0.16em] uppercase">
          Row samples
        </h2>
      </div>

      <p className="text-amber-300/95 text-[13px] leading-relaxed font-medium">
        Sample rows from the disposable shadow cluster. Synthetic data at the{" "}
        {view.scaleTier ?? "shadow"} scale tier — not your production data.
      </p>

      {view.status !== "ready" ? (
        <p className="text-muted-foreground font-mono text-xs leading-relaxed">
          {view.message}
        </p>
      ) : view.tables.length === 0 ? (
        <p className="text-muted-foreground font-mono text-xs leading-relaxed">
          No tables sampled.
        </p>
      ) : (
        <div className="space-y-5">
          {view.tables.map((t) => (
            <TableDiffCard key={t.requestedName} table={t} />
          ))}
        </div>
      )}
    </section>
  )
}
