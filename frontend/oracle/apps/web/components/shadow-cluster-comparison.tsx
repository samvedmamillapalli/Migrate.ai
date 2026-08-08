"use client"

import * as React from "react"
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react"

import { ComparisonsBlock, EventLog } from "@/components/shadow-live-view"
import {
  mapClusterComparison,
  mapCostStrip,
  type ClusterCardView,
  type ClusterColumnRowView,
  type ClusterTableView,
  type ComparisonRow,
  type MigrationRun,
  type RunExtras,
  type ShadowCluster,
} from "@/lib/api"
import {
  EmptyNote,
  Label,
  Panel,
  ToneDot,
  toneSurface,
  toneText,
  type Tone,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

/**
 * Side-by-side structural comparison of the shadow cluster before and after
 * the migration ran, plus the change summary underneath.
 *
 * Deliberately shows ROWS and not a byte size: per-table storage is not
 * readable on the CockroachDB Cloud BASIC plan shadow clusters run on
 * (`crdb_internal` is restricted, `pg_total_relation_size` doesn't exist, and
 * `SHOW RANGES` reports one tenant-wide range), so there is no honest number
 * to put in a SIZE column. Row counts are real. Total storage delta is
 * measured separately and already shown in the cost strip.
 */

/** Wide tables (real customer schemas can run to hundreds of columns) show
 * 10 column rows at a time per table instead of dumping the whole list
 * inline under the table's summary row. */
const COLUMNS_PAGE_SIZE = 10

const DIFF_TONE: Record<ClusterTableView["diffKind"], Tone | null> = {
  added: "pass",
  removed: "fail",
  changed: "warn" as Tone,
  unchanged: null,
}

const BADGE_LABEL: Partial<Record<ClusterTableView["diffKind"], string>> = {
  added: "new",
  removed: "dropped",
  changed: "changed",
}

function formatCount(value: number | null): string {
  if (value == null) return "—"
  return value.toLocaleString()
}

function formatDelta(value: number): string | null {
  if (value === 0) return null
  return value > 0 ? `+${value}` : String(value)
}

/** Row background/text for a diffed table or column row — orange for
 * changed, red for removed, green for added, plain for unchanged. */
function diffRowClass(kind: ClusterTableView["diffKind"]): string {
  const tone = DIFF_TONE[kind]
  if (!tone) return "text-foreground/85"
  return cn(toneSurface(tone), toneText(tone))
}

function ClusterCard({
  title,
  subtitle,
  card,
  emphasis,
  compareTo,
  columnsByTableKey,
}: {
  title: string
  subtitle: string
  card: ClusterCardView
  emphasis: boolean
  compareTo?: ClusterCardView | null
  /** This side's real column list for tables the migration touched, keyed by
   * "schema.table" — same key as `table.key`. Renders as extra rows directly
   * under that table's summary row: real column names, immediately visible,
   * no click required. Tables not in this map (unchanged ones) just show
   * their summary row as before. */
  columnsByTableKey?: Map<string, ClusterColumnRowView[]>
}) {
  const tableDelta = compareTo ? formatDelta(card.tableCount - compareTo.tableCount) : null
  const indexDelta = compareTo ? formatDelta(card.indexCount - compareTo.indexCount) : null

  // Keyed by table key so each table's column list pages independently.
  const [columnsPageByTable, setColumnsPageByTable] = React.useState<Record<string, number>>({})

  return (
    <Panel
      aria-label={title}
      className={cn(
        "flex min-w-0 flex-1 flex-col gap-3 px-5 py-4",
        emphasis && "border-[var(--tone-pass-border)]"
      )}
    >
      <header className="space-y-1">
        <h3 className="text-foreground text-sm font-semibold tracking-tight">
          {title}
        </h3>
        <p className="section-label">
          <span className={emphasis ? toneText("pass") : undefined}>
            {subtitle}
          </span>
          {card.schemaLabel ? (
            <>
              <span className="text-muted-foreground/40 normal-case"> · </span>
              <span className="text-muted-foreground normal-case tracking-tight lowercase">
                {card.schemaLabel}
              </span>
            </>
          ) : null}
        </p>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full min-w-max border-collapse text-[13px]">
          <thead>
            <tr className="section-label">
              <th className="border-border/60 border-b px-2 py-1.5 text-left font-semibold">
                Table
              </th>
              <th className="border-border/60 border-b px-2 py-1.5 text-right font-semibold">
                Columns
              </th>
              <th className="border-border/60 border-b px-2 py-1.5 text-right font-semibold">
                Indexes
              </th>
              <th className="border-border/60 border-b px-2 py-1.5 text-right font-semibold">
                Rows
              </th>
            </tr>
          </thead>
          <tbody>
            {card.tables.map((table) => {
              const columns = columnsByTableKey?.get(table.key)
              return (
                <React.Fragment key={table.key}>
                  <tr
                    className={cn(
                      "border-border/40 border-b last:border-b-0",
                      diffRowClass(table.diffKind)
                    )}
                  >
                    <td className="px-2 py-1.5 font-mono whitespace-nowrap">
                      {table.name}
                      {BADGE_LABEL[table.diffKind] ? (
                        <span className="ml-1.5 font-sans text-[10px] font-semibold tracking-[0.1em] uppercase opacity-80">
                          {BADGE_LABEL[table.diffKind]}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                      {table.columnCount}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                      {table.indexCount}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                      {formatCount(table.rowCount)}
                    </td>
                  </tr>
                  {columns && columns.length > 0
                    ? (() => {
                        const page = columnsPageByTable[table.key] ?? 0
                        const pageCount = Math.max(
                          1,
                          Math.ceil(columns.length / COLUMNS_PAGE_SIZE)
                        )
                        const clamped = Math.min(page, pageCount - 1)
                        const paged = columns.slice(
                          clamped * COLUMNS_PAGE_SIZE,
                          clamped * COLUMNS_PAGE_SIZE + COLUMNS_PAGE_SIZE
                        )
                        return (
                          <>
                            {paged.map((column) => (
                              <tr
                                key={`${table.key}.${column.name}`}
                                className={cn(
                                  "border-border/40 border-b last:border-b-0",
                                  diffRowClass(column.kind)
                                )}
                              >
                                <td
                                  className={cn(
                                    "py-1 pr-2 pl-5 font-mono whitespace-nowrap",
                                    column.kind === "removed" && "line-through"
                                  )}
                                >
                                  {column.name}
                                </td>
                                <td
                                  colSpan={3}
                                  className="text-muted-foreground py-1 pr-2 text-right font-mono whitespace-nowrap"
                                >
                                  {column.type ?? "—"}
                                </td>
                              </tr>
                            ))}
                            {columns.length > COLUMNS_PAGE_SIZE ? (
                              <tr className="border-border/40 border-b last:border-b-0">
                                <td colSpan={4} className="py-1 pr-2 pl-5">
                                  <div className="flex items-center justify-between gap-2">
                                    <span className="text-muted-foreground text-[11px]">
                                      {clamped * COLUMNS_PAGE_SIZE + 1}–
                                      {Math.min(
                                        clamped * COLUMNS_PAGE_SIZE + COLUMNS_PAGE_SIZE,
                                        columns.length
                                      )}{" "}
                                      of {columns.length} columns
                                    </span>
                                    <div className="flex items-center gap-1.5">
                                      <button
                                        type="button"
                                        onClick={() =>
                                          setColumnsPageByTable((s) => ({
                                            ...s,
                                            [table.key]: Math.max(0, clamped - 1),
                                          }))
                                        }
                                        disabled={clamped === 0}
                                        className="border-border text-foreground grid size-6 place-items-center rounded border disabled:cursor-not-allowed disabled:opacity-40"
                                        aria-label="Previous columns"
                                      >
                                        <ChevronLeft className="size-3.5" />
                                      </button>
                                      <span className="text-muted-foreground min-w-[48px] text-center text-[11px]">
                                        Page {clamped + 1} of {pageCount}
                                      </span>
                                      <button
                                        type="button"
                                        onClick={() =>
                                          setColumnsPageByTable((s) => ({
                                            ...s,
                                            [table.key]: Math.min(pageCount - 1, clamped + 1),
                                          }))
                                        }
                                        disabled={clamped >= pageCount - 1}
                                        className="border-border text-foreground grid size-6 place-items-center rounded border disabled:cursor-not-allowed disabled:opacity-40"
                                        aria-label="Next columns"
                                      >
                                        <ChevronRight className="size-3.5" />
                                      </button>
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            ) : null}
                          </>
                        )
                      })()
                    : null}
                </React.Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      <footer className="text-muted-foreground flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[12px] tabular-nums">
        <span>
          {card.tableCount} table{card.tableCount === 1 ? "" : "s"}
          {tableDelta ? (
            <span className={toneText("pass")}> ({tableDelta})</span>
          ) : null}
        </span>
        <span className="text-muted-foreground/40">·</span>
        <span>
          {card.indexCount} index{card.indexCount === 1 ? "" : "es"}
          {indexDelta ? (
            <span className={toneText("pass")}> ({indexDelta})</span>
          ) : null}
        </span>
        <span className="text-muted-foreground/40">·</span>
        <span>{formatCount(card.rowCount)} rows</span>
      </footer>
    </Panel>
  )
}

function ChangesDetected({
  changes,
}: {
  changes: NonNullable<ReturnType<typeof mapClusterComparison>["changes"]>
}) {
  const items: Array<{ label: string; value: string; tone: Tone }> = []
  if (changes.addedTables.length > 0) {
    items.push({
      label: "Added",
      value: changes.addedTables
        .map((name) => `${name.split(".").pop()} table`)
        .join(", "),
      tone: "pass",
    })
  }
  if (changes.removedTables.length > 0) {
    items.push({
      label: "Dropped",
      value: changes.removedTables
        .map((name) => `${name.split(".").pop()} table`)
        .join(", "),
      tone: "fail",
    })
  }
  if (changes.modifiedColumns.length > 0) {
    items.push({
      label: "Modified",
      value: changes.modifiedColumns
        .map((name) => {
          const parts = name.split(".")
          return `${parts.slice(-2).join(".")} column`
        })
        .join(", "),
      tone: "warn",
    })
  }
  if (changes.unchangedTableCount > 0) {
    items.push({
      label: "Unchanged",
      value: `${changes.unchangedTableCount} existing table${
        changes.unchangedTableCount === 1 ? "" : "s"
      }`,
      tone: "neutral",
    })
  }

  return (
    <Panel aria-label="Changes detected" className="flex flex-col gap-2.5 px-5 py-4">
      <Label>Changes Detected</Label>
      {items.length === 0 ? (
        <EmptyNote>
          The migration changed nothing structural — both snapshots are identical.
        </EmptyNote>
      ) : (
        <dl className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
          {items.map((item) => (
            <div key={item.label} className="flex items-baseline gap-2">
              <dt className="section-label">{item.label}</dt>
              <dd className={cn("text-[13px] tracking-tight", toneText(item.tone))}>
                {item.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </Panel>
  )
}

/** The right-hand card before a shadow run has produced an after-snapshot.
 * Keeps the two-column shape on screen at all times so the panel never
 * collapses to a bare sentence — the layout is the point. */
function PendingClusterCard({ message }: { message: string | null }) {
  return (
    <section
      aria-label="Shadow Cluster"
      className="border-border/70 flex min-w-0 flex-1 flex-col gap-3 rounded-xl border border-dashed bg-transparent px-5 py-4"
    >
      <header className="space-y-1">
        <h3 className="text-foreground/70 text-sm font-semibold tracking-tight">
          Shadow Cluster
        </h3>
        <p className="section-label">Awaiting run</p>
      </header>
      <p className="text-muted-foreground text-[13px] leading-relaxed">
        {message ??
          "Run a shadow test to capture the after side of this comparison."}
      </p>
    </section>
  )
}

/** A collapsed-by-default technical-detail block: a title, a one-line
 * summary shown whether open or closed, and full content revealed on click.
 * Native `<details>` — no extra state, keyboard/AT-accessible for free. */
function AccordionItem({
  title,
  summary,
  children,
}: {
  title: string
  summary: string
  children: React.ReactNode
}) {
  return (
    <details className="group border-border bg-card rounded-lg border">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-3.5 select-none">
        <div className="space-y-0.5">
          <p className="text-foreground text-[13.5px] font-semibold tracking-tight">
            {title}
          </p>
          <p className="text-muted-foreground text-[12px] tracking-tight">
            {summary}
          </p>
        </div>
        <ChevronDown className="text-muted-foreground size-4 shrink-0 transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-border border-t p-3.5">{children}</div>
    </details>
  )
}

const VERDICT_TONE: Record<"success" | "timedOut" | "failed", { tone: Tone; tagLabel: string }> = {
  success: { tone: "pass", tagLabel: "execution complete" },
  timedOut: { tone: "warn", tagLabel: "execution timed out" },
  failed: { tone: "fail", tagLabel: "execution failed" },
}

/** The measured-outcome chip row and the plain-language verdict beneath it.
 * Renders nothing until `extras.execution` exists — there's no verdict to
 * give before the migration has actually run. */
function ExecutionVerdict({ extras }: { extras: RunExtras }) {
  const costStrip = mapCostStrip(extras)
  if (!costStrip || !extras.execution) return null

  const outcome = costStrip.timedOut ? "timedOut" : costStrip.success ? "success" : "failed"
  const { tone, tagLabel } = VERDICT_TONE[outcome]
  const jobsWord = costStrip.timedOut ? "timed out" : costStrip.success ? "succeeded" : "failed"

  const headline =
    outcome === "success"
      ? "Migration ran cleanly in the shadow environment."
      : outcome === "timedOut"
        ? "Migration timed out in the shadow environment."
        : "Migration failed in the shadow environment."

  const subtext =
    outcome === "success"
      ? "No blocking locks or query regressions were detected. Review technical evidence only if you need the full trace."
      : (extras.execution.error_message?.slice(0, 240) ??
        "Review technical evidence for the full trace.")

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="border-border text-foreground/80 rounded-full border px-2.5 py-1 text-[11px] tracking-tight">
          {costStrip.durationLabel} duration
        </span>
        <span className="border-border text-foreground/80 rounded-full border px-2.5 py-1 text-[11px] tracking-tight">
          {costStrip.storageLabel} storage
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-tight",
            toneSurface(tone),
            toneText(tone)
          )}
        >
          <ToneDot tone={tone} />
          {costStrip.jobsRun} job{costStrip.jobsRun === 1 ? "" : "s"} {jobsWord}
        </span>
      </div>

      <div className={cn("space-y-1.5 rounded-lg border p-4", toneSurface(tone))}>
        <p className={cn("section-label", toneText(tone))}>{tagLabel}</p>
        <p className="text-foreground text-[14px] font-semibold tracking-tight">
          {headline}
        </p>
        <p className="text-muted-foreground text-sm leading-relaxed">
          {subtext}
        </p>
      </div>
    </div>
  )
}

function predictionSummary(rows: ComparisonRow[]): string {
  if (rows.length === 0) return "Appears after measurement."
  const withBand = rows.filter((r) => r.withinBand != null)
  if (withBand.length === 0) return `${rows.length} prediction${rows.length === 1 ? "" : "s"} compared.`
  const within = withBand.filter((r) => r.withinBand).length
  return `${within} of ${withBand.length} prediction${withBand.length === 1 ? "" : "s"} within band.`
}

export type ShadowClusterComparisonProps = {
  run: MigrationRun | null
  shadow: ShadowCluster | null
  extras: RunExtras
  comparisons: ComparisonRow[]
}

export function ShadowClusterComparison({
  run,
  shadow,
  extras,
  comparisons,
}: ShadowClusterComparisonProps) {
  const view = mapClusterComparison(run, shadow)

  // Only genuinely empty states (no database attached / discovery never ran)
  // fall back to a bare message. Once the customer's schema is known, the
  // side-by-side layout is always on screen.
  if (!view.source) {
    return <EmptyNote>{view.message ?? "Cluster comparison is not available for this run."}</EmptyNote>
  }

  // Real column list per touched table, per side — rendered as extra rows
  // directly inside each ClusterCard, right under that table's summary row.
  // Only ready state has anything here: source_only has no "after" yet, and
  // there's nothing to single out until a diff exists.
  const columnsByTableKeyBefore = new Map<string, ClusterColumnRowView[]>()
  const columnsByTableKeyAfter = new Map<string, ClusterColumnRowView[]>()
  if (view.status === "ready") {
    for (const t of view.columnDetails) {
      columnsByTableKeyBefore.set(t.tableName, t.before)
      columnsByTableKeyAfter.set(t.tableName, t.after)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col items-stretch gap-3 lg:flex-row lg:items-start">
        <ClusterCard
          title="Production Cluster"
          subtitle="Source"
          card={view.source}
          emphasis={false}
          columnsByTableKey={columnsByTableKeyBefore}
        />
        <div
          aria-hidden
          className="text-muted-foreground/50 flex shrink-0 items-center justify-center self-center text-lg lg:pt-16"
        >
          <span className="lg:hidden">↓</span>
          <span className="hidden lg:inline">→</span>
        </div>
        {view.shadow ? (
          <ClusterCard
            title="Shadow Cluster"
            subtitle="After migration"
            card={view.shadow}
            emphasis
            compareTo={view.source}
            columnsByTableKey={columnsByTableKeyAfter}
          />
        ) : (
          <PendingClusterCard message={view.message} />
        )}
      </div>

      {view.changes ? <ChangesDetected changes={view.changes} /> : null}

      <ExecutionVerdict extras={extras} />

      {extras.execution ? (
        <div className="space-y-2.5">
          <Label>Technical details</Label>
          <div className="space-y-2">
            <AccordionItem
              title="Prediction vs. actual"
              summary={predictionSummary(comparisons)}
            >
              <div className="space-y-3">
                <ComparisonsBlock rows={comparisons} />
                {extras.grade ? (
                  <div className="border-border flex items-baseline gap-4 border-t pt-3 text-[12px] tracking-tight">
                    <span className="text-muted-foreground">
                      Grade{" "}
                      <span className="text-foreground font-semibold">
                        {extras.grade.scalar_accuracy_score.toFixed(3)}
                      </span>
                    </span>
                    <span className="text-muted-foreground">
                      Class{" "}
                      <span className="text-foreground font-semibold">
                        {extras.grade.outcome_class}
                      </span>
                    </span>
                  </div>
                ) : null}
              </div>
            </AccordionItem>
            <AccordionItem
              title="Event log"
              summary="Full step-by-step timeline of this run."
            >
              <EventLog shadow={shadow} />
            </AccordionItem>
          </div>
        </div>
      ) : null}

      <p className="text-muted-foreground text-[11px] leading-relaxed">
        {view.shadow ? (
          <>
            Both sides are the disposable shadow cluster, captured immediately
            before and immediately after your migration ran — so every
            difference above is a migration effect, not a difference between two
            databases. Table and column shape changes are real and match what
            would happen to production. Row counts on the shadow side are
            tier-capped synthetic rows, not your production volume.
          </>
        ) : (
          <>
            The source side is your own database exactly as discovered — real
            tables, real columns, real index and row counts. The shadow side
            fills in once a shadow test runs your migration against a
            throwaway copy.
          </>
        )}{" "}
        Per-table storage is not readable on the CockroachDB Cloud BASIC plan
        these clusters run on, so this shows row counts instead; total storage
        delta is measured separately.
      </p>
    </div>
  )
}
