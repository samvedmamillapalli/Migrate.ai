"use client"

import { mapRowSamplePanel, type RowSampleTableView, type ShadowCluster } from "@/lib/api"
import { cn } from "@workspace/ui/lib/utils"

const DIFF_TEXT: Record<string, string> = {
  added: "text-[var(--oracle-verified)]",
  removed: "text-[var(--oracle-risk)]",
  changed: "text-amber-400/90",
  unchanged: "text-muted-foreground/55",
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "null"
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

function TableCard({
  table,
  side,
}: {
  table: RowSampleTableView
  side: "before" | "after"
}) {
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

  return (
    <div className="border-border/50 rounded-md border p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-mono text-xs text-foreground/90">{label}</p>
        {table.totalRowCount != null ? (
          <span className="text-muted-foreground/60 font-mono text-[10px] tabular-nums">
            {table.totalRowCount > table.sampledCount
              ? `${table.sampledCount} of ${table.totalRowCount}`
              : `${table.totalRowCount} row${table.totalRowCount === 1 ? "" : "s"}`}
          </span>
        ) : null}
      </div>
      {table.note ? (
        <p className="text-amber-400/80 mb-2 text-[10px] leading-relaxed">{table.note}</p>
      ) : null}
      {table.columns.length === 0 ? (
        <p className="text-muted-foreground/60 font-mono text-[11px]">
          No columns captured.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-max border-collapse font-mono text-[10.5px]">
            <thead>
              <tr>
                {table.columns.map((c) => (
                  <th
                    key={c.name}
                    className={cn(
                      "border-border/40 border-b px-2 py-1 text-left align-bottom whitespace-nowrap",
                      DIFF_TEXT[c.diffKind],
                      side === "after" &&
                        c.diffKind === "added" &&
                        "bg-[var(--oracle-verified)]/10"
                    )}
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
              {table.rows.length === 0 ? (
                <tr>
                  <td
                    colSpan={table.columns.length}
                    className="text-muted-foreground/60 px-2 py-2"
                  >
                    No rows.
                  </td>
                </tr>
              ) : (
                table.rows.map((row, idx) => (
                  <tr key={idx} className="border-border/20 border-b last:border-b-0">
                    {table.columns.map((c) => (
                      <td
                        key={c.name}
                        className={cn(
                          "text-foreground/80 px-2 py-1 whitespace-nowrap",
                          side === "after" &&
                            c.diffKind === "added" &&
                            "bg-[var(--oracle-verified)]/5"
                        )}
                      >
                        {formatCell(row[c.name])}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/**
 * Real before/after row samples, above the lifecycle timeline on the full
 * Shadow Execution page only (not the compact ShadowLiveView). Renders
 * instantly from persisted data for a replayed/finished run — no polling.
 */
export function ShadowRowSamplesPanel({ shadow }: { shadow: ShadowCluster | null }) {
  const view = mapRowSamplePanel(shadow)

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
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
              Before
            </p>
            {view.before.length === 0 ? (
              <p className="text-muted-foreground/60 font-mono text-[11px]">
                No tables sampled.
              </p>
            ) : (
              view.before.map((t) => (
                <TableCard key={t.requestedName} table={t} side="before" />
              ))
            )}
          </div>
          <div className="space-y-3">
            <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
              After
            </p>
            {view.after.length === 0 ? (
              <p className="text-muted-foreground/60 font-mono text-[11px]">
                {(shadow?.status || "").toLowerCase() === "migrating"
                  ? "Migration still running — measured right after it finishes."
                  : "No tables sampled."}
              </p>
            ) : (
              view.after.map((t) => (
                <TableCard key={t.requestedName} table={t} side="after" />
              ))
            )}
          </div>
        </div>
      )}
    </section>
  )
}
