"use client"

import * as React from "react"
import Link from "next/link"
import { motion } from "motion/react"
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Search,
  X,
} from "lucide-react"

import { ApiError } from "@/lib/api/client"
import {
  type AccuracyMetrics,
  type ApprovalDecisionFilter,
  type MigrationRunSummary,
  type RunSortKey,
  type RunVolume,
  getAccuracyMetrics,
  getRunVolume,
  listRuns,
} from "@/lib/api/endpoints"
import { migrationKindLabel, mapRunListItem, type RunListItem } from "@/lib/api/map-run"
import { getActiveWorkspaceId, getOwnerIdentity, setCurrentRunId } from "@/lib/api/owner"
import {
  EmptyNote,
  ErrorNote,
  Label,
  PageHeader,
  Panel,
  SkeletonBar,
  SkeletonStats,
  StatusPill,
  Stat,
  toneText,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

const PAGE_SIZES = [5, 8, 10, 20, 50]

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return null
}

/** Shadow column: measured outcome, or an explicit dash when none ran. */
function ShadowIcon({ outcome }: { outcome: RunListItem["shadowOutcome"] }) {
  if (outcome === "pass")
    return <Check className="size-4 text-[var(--tone-pass-fg)]" />
  if (outcome === "warn")
    return <AlertTriangle className="size-4 text-[var(--tone-warn-fg)]" />
  if (outcome === "fail")
    return <X className="size-4 text-[var(--tone-fail-fg)]" />
  return <span className="text-muted-foreground/50 text-xs">—</span>
}

/**
 * Outcome column. Shows the recorded human decision when one exists,
 * otherwise the run's own terminal state — never a guess.
 */
function OutcomePill({ item }: { item: RunListItem }) {
  if (item.approvalDecision) {
    return <StatusPill status={item.approvalDecision} />
  }
  return <StatusPill status={item.status} />
}

const selectCls =
  "h-10 rounded-lg border border-border bg-card px-3 text-sm text-foreground outline-none transition-colors focus:border-primary"

/**
 * Daily migration volume from `GET /runs/volume` — the whole history, not
 * just the page currently loaded in the table. The two series are real
 * categories, not the design's unlabelled a/b: succeeded vs failed-or-cancelled.
 */
function useVolumeChart(volume: RunVolume | null) {
  return React.useMemo(() => {
    const days = (volume?.days ?? []).map((d) => ({
      key: d.day,
      day: new Date(`${d.day}T00:00:00`).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      }),
      ok: d.ok,
      bad: d.bad,
    }))
    const max = Math.max(1, ...days.map((d) => d.ok + d.bad))
    // Distinct integer ticks only — a 0..1 range must not render as 1,1,1,0,0.
    const step = Math.max(1, Math.ceil(max / 4))
    const ticks: number[] = []
    for (let v = Math.ceil(max / step) * step; v >= 0; v -= step) ticks.push(v)
    return { days, max, ticks }
  }, [volume])
}

/** Debounce the search box so each keystroke isn't a request. */
function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = React.useState(value)
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(t)
  }, [value, delayMs])
  return debounced
}

/** Row-shaped placeholder so the table doesn't collapse while loading. */
function TableSkeleton({ rows }: { rows: number }) {
  return (
    <div className="px-6 py-4" role="status" aria-busy>
      <span className="sr-only">Loading migrations…</span>
      <div className="space-y-4">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="flex items-center gap-4">
            <SkeletonBar className="h-4 flex-1" />
            <SkeletonBar className="h-4 w-20" />
            <SkeletonBar className="h-4 w-16" />
            <SkeletonBar className="h-4 w-24" />
            <SkeletonBar className="h-4 w-20" />
          </div>
        ))}
      </div>
    </div>
  )
}

/** "2026-07-30" + "14:07" — stable in a table, unlike a relative label. */
/** Date only — the time of day was noise in a list scanned by day. */
function executedAt(iso: string | null | undefined): { date: string } {
  if (!iso) return { date: "—" }
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return { date: "—" }
  const d = new Date(t)
  return {
    date: d.toLocaleDateString([], { month: "short", day: "numeric" }),
  }
}

export default function PastMigrationsPage() {
  const [runs, setRuns] = React.useState<MigrationRunSummary[] | null>(null)
  const [total, setTotal] = React.useState(0)
  const [metrics, setMetrics] = React.useState<AccuracyMetrics | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  const [query, setQuery] = React.useState("")
  const [risk, setRisk] = React.useState("all")
  const [outcome, setOutcome] = React.useState("all")
  const [perPage, setPerPage] = React.useState(8)
  const [page, setPage] = React.useState(1)
  const [sortKey, setSortKey] = React.useState<RunSortKey>("created_at")
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("desc")
  const [volume, setVolume] = React.useState<RunVolume | null>(null)
  const [reloadKey, setReloadKey] = React.useState(0)

  const debouncedQuery = useDebounced(query, 350)

  // Every filter and the sort are server-side, so they apply across the whole
  // history rather than to whichever page happens to be loaded. Changing any
  // of them resets to page 1 — otherwise you can land on an empty page 4 of a
  // now two-page result set.
  React.useEffect(() => {
    setPage(1)
  }, [debouncedQuery, risk, outcome, perPage, sortKey, sortDir])

  React.useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const owner = getOwnerIdentity()
        const workspaceId = getActiveWorkspaceId()
        const scope = {
          ...(owner ? { owner_identity: owner } : {}),
          ...(workspaceId ? { workspace_id: workspaceId } : {}),
        }
        const [runsRes, metricsRes, volumeRes] =
          await Promise.allSettled([
            listRuns({
              limit: perPage,
              offset: (page - 1) * perPage,
              exclude_kinds: "chaos,debug",
              order_by: sortKey,
              order_dir: sortDir,
              ...(debouncedQuery.trim() ? { q: debouncedQuery.trim() } : {}),
              ...(risk !== "all"
                ? { risk: risk as "low" | "medium" | "high" }
                : {}),
              ...(outcome !== "all"
                ? { decision: outcome as ApprovalDecisionFilter }
                : {}),
              ...scope,
            }),
            getAccuracyMetrics({
              owner_identity: owner || undefined,
              workspace_id: workspaceId || undefined,
            }),
            getRunVolume({ days: 7, ...scope }),
          ])
        if (cancelled) return
        if (runsRes.status === "fulfilled") {
          setRuns(runsRes.value.items)
          setTotal(runsRes.value.total)
          setError(null)
        } else {
          throw runsRes.reason
        }
        if (metricsRes.status === "fulfilled") setMetrics(metricsRes.value)
        if (volumeRes.status === "fulfilled") setVolume(volumeRes.value)
      } catch (err) {
        if (cancelled) return
        setError(
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Failed to load migration runs."
        )
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [
    page,
    perPage,
    debouncedQuery,
    risk,
    outcome,
    sortKey,
    sortDir,
    reloadKey,
  ])

  const items = React.useMemo(
    () => (runs ? runs.map(mapRunListItem) : []),
    [runs]
  )

  const { days, max, ticks } = useVolumeChart(volume)

  const pages = Math.max(1, Math.ceil(total / perPage))
  const current = Math.min(page, pages)
  const rangeStart = total === 0 ? 0 : (current - 1) * perPage + 1
  const rangeEnd = Math.min(current * perPage, total)

  const trend = Array.isArray(metrics?.scalar_accuracy_trend)
    ? (metrics!.scalar_accuracy_trend as unknown[])
    : []
  const successRate = asRecord(metrics?.migration_success_rate)
  const approvals = asRecord(metrics?.approval_breakdown)
  const passRate =
    successRate?.rate == null
      ? null
      : Math.round(Number(successRate.rate) * 100)

  return (
    <div className="mx-auto w-full max-w-[1500px] px-6 pb-10 lg:px-10">
      <PageHeader
        title="Past Migrations"
        subtitle={`Full audit trail — ${total} migration${total === 1 ? "" : "s"} on record.`}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
        <Panel className="px-6 py-5">
          <Label className="mb-4">Accuracy Summary</Label>
          {/* Two headline numbers instead of four equal-weight blocks. Graded
              and Cancelled are supporting detail, not headlines, so they read
              as one quiet caption underneath. */}
          <div className="grid grid-cols-2 gap-5">
            <Stat label="Total Migrations" value={total} sub="all time" />
            <Stat
              label="Shadow Pass Rate"
              value={passRate == null ? "—" : `${passRate}%`}
              sub={
                successRate
                  ? `${Number(successRate.numerator ?? 0)} of ${Number(successRate.denominator ?? 0)} graded`
                  : "no graded runs yet"
              }
              valueClassName={passRate == null ? undefined : toneText("pass")}
            />
          </div>
          <p className="text-muted-foreground mt-4 text-[12px]">
            {trend.length} graded
            <span className="text-muted-foreground/40 mx-1.5">·</span>
            <span
              className={
                Number(approvals?.cancel ?? 0) > 0 ? toneText("fail") : undefined
              }
            >
              {Number(approvals?.cancel ?? 0)} cancelled
            </span>
          </p>
        </Panel>

        <Panel className="px-6 py-5" delay={0.05}>
          <div className="mb-4 flex items-center justify-between">
            <Label>Daily Migration Volume</Label>
            <span className="text-muted-foreground text-[12px]">
              Last 7 days · this page
            </span>
          </div>
          <div className="flex h-[150px] gap-2">
            <div className="text-muted-foreground flex w-4 flex-col justify-between py-1 text-right text-[11px]">
              {ticks.map((n) => (
                <span key={n}>{n}</span>
              ))}
            </div>
            <div className="border-border flex flex-1 items-end justify-between gap-3 border-b">
              {days.map((d) => (
                <div
                  key={d.key}
                  className="flex flex-1 flex-col items-center gap-2"
                  title={`${d.day}: ${d.ok} succeeded, ${d.bad} failed`}
                >
                  <div className="flex h-[120px] w-full items-end justify-center gap-1">
                    <motion.div
                      initial={{ height: 0 }}
                      animate={{ height: `${(d.ok / max) * 100}%` }}
                      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                      className="bg-primary w-3 rounded-t-[2px]"
                    />
                    <motion.div
                      initial={{ height: 0 }}
                      animate={{ height: `${(d.bad / max) * 100}%` }}
                      transition={{
                        duration: 0.5,
                        delay: 0.06,
                        ease: [0.22, 1, 0.36, 1],
                      }}
                      className="w-3 rounded-t-[2px] bg-[var(--tone-fail-dot)]"
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-2 flex gap-3 pl-6">
            {days.map((d) => (
              <div
                key={d.key}
                className="text-muted-foreground flex-1 text-center text-[11px]"
              >
                {d.day}
              </div>
            ))}
          </div>
          <div className="text-muted-foreground mt-3 flex items-center gap-4 text-[11px]">
            <span className="flex items-center gap-1.5">
              <span className="bg-primary size-2 rounded-[2px]" /> Succeeded
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2 rounded-[2px] bg-[var(--tone-fail-dot)]" />{" "}
              Failed or cancelled
            </span>
          </div>
        </Panel>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <div className="relative min-w-[260px] flex-1 sm:max-w-[320px]">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search migrations…"
            className="border-border bg-card placeholder:text-muted-foreground focus:border-primary h-10 w-full rounded-lg border pr-3 pl-9 text-sm outline-none transition-colors"
          />
        </div>
        <select
          value={risk}
          onChange={(e) => setRisk(e.target.value)}
          className={selectCls}
          aria-label="Filter by risk level"
        >
          <option value="all">All risk levels</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
        <select
          value={outcome}
          onChange={(e) => setOutcome(e.target.value)}
          className={selectCls}
          aria-label="Filter by outcome"
        >
          <option value="all">All outcomes</option>
          <option value="proceed">Proceeded</option>
          <option value="accept_recommended">Accepted plan</option>
          <option value="cancel">Cancelled</option>
          <option value="none">No decision yet</option>
        </select>
      </div>

      <Panel className="mt-4 overflow-hidden" delay={0.08}>
        {error ? (
          <div className="space-y-3 px-6 py-5">
            <ErrorNote>{error}</ErrorNote>
            <button
              type="button"
              onClick={() => setReloadKey((k) => k + 1)}
              className="border-border text-foreground hover:bg-muted rounded-lg border px-3.5 py-2 text-[13px] font-semibold transition-colors"
            >
              Retry
            </button>
          </div>
        ) : loading ? (
          <TableSkeleton rows={Math.min(perPage, 6)} />
        ) : items.length === 0 ? (
          <div className="space-y-3 px-6 py-5">
            <EmptyNote>
              {total === 0
                ? "No migration runs yet."
                : "No runs on this page match the current filters."}
            </EmptyNote>
            {total === 0 ? (
              <Link
                href="/dashboard/migrations/new"
                className="text-primary font-mono text-[11px] tracking-tight hover:underline"
              >
                Start a migration →
              </Link>
            ) : null}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1050px] border-collapse text-left">
              <thead>
                <tr className="border-border bg-muted/50 border-b">
                  {(
                    [
                      ["Migration", null],
                      ["Executed", "created_at"],
                      ["Duration", null],
                      ["Risk", "compatibility_risk"],
                      ["Confidence", null],
                      ["Shadow", null],
                      ["Outcome", "status"],
                      ["Graded", null],
                    ] as Array<[string, RunSortKey | null]>
                  ).map(([label, key]) => (
                    <th
                      key={label}
                      className="section-label py-3 pr-4 font-semibold first:pl-6 last:pr-6"
                    >
                      {/* Only columns the backend can actually order by are
                          sortable — duration and confidence live outside the
                          runs table, so offering them would be a lie. */}
                      {key ? (
                        <button
                          type="button"
                          onClick={() => {
                            if (sortKey === key) {
                              setSortDir((d) => (d === "asc" ? "desc" : "asc"))
                            } else {
                              setSortKey(key)
                              setSortDir("desc")
                            }
                          }}
                          className={cn(
                            "hover:text-foreground inline-flex items-center gap-1 transition-colors",
                            sortKey === key && "text-foreground"
                          )}
                          aria-label={`Sort by ${label}`}
                        >
                          {label}
                          <span aria-hidden className="text-[9px]">
                            {sortKey === key
                              ? sortDir === "asc"
                                ? "▲"
                                : "▼"
                              : "↕"}
                          </span>
                        </button>
                      ) : (
                        label
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((m) => (
                  <tr
                    key={m.id}
                    className="border-border hover:bg-muted/40 border-b transition-colors"
                  >
                    <td className="max-w-[300px] py-4 pr-4 pl-6">
                      <Link
                        href={`/dashboard/migrations/${m.id}`}
                        onClick={() => setCurrentRunId(m.id)}
                        className="block"
                      >
                        <div className="text-foreground truncate text-[13px] font-medium">
                          {migrationKindLabel(m.migrationSql)}
                        </div>
                        <div className="text-muted-foreground mt-0.5 font-mono text-[11.5px]">
                          {m.tableName ?? "—"}
                        </div>
                      </Link>
                    </td>
                    <td className="text-foreground py-4 pr-4 font-mono text-[12.5px] whitespace-nowrap">
                      <div>{executedAt(m.createdAt).date}</div>
                    </td>
                    <td className="text-foreground py-4 pr-4 font-mono text-[12.5px]">
                      {m.durationLabel ?? (
                        <span className="text-muted-foreground/50">—</span>
                      )}
                    </td>
                    <td
                      className={cn(
                        "py-4 pr-4 text-[13px] font-semibold capitalize",
                        m.risk ? toneText(m.riskTone) : "text-muted-foreground/50"
                      )}
                    >
                      {m.risk ?? "—"}
                    </td>
                    <td className="py-4 pr-4">
                      {m.confidencePercent == null ? (
                        <span className="text-muted-foreground/50 text-[12.5px]">
                          —
                        </span>
                      ) : (
                        <div className="flex items-center gap-2">
                          <div className="bg-muted h-1.5 w-[70px] overflow-hidden rounded-full">
                            <motion.div
                              initial={{ width: 0 }}
                              animate={{ width: `${m.confidencePercent}%` }}
                              transition={{ duration: 0.5 }}
                              className={cn(
                                "h-full rounded-full",
                                m.riskTone === "pass" &&
                                  "bg-[var(--tone-pass-dot)]",
                                m.riskTone === "warn" &&
                                  "bg-[var(--tone-warn-dot)]",
                                m.riskTone === "fail" &&
                                  "bg-[var(--tone-fail-dot)]",
                                m.riskTone === "neutral" && "bg-primary"
                              )}
                            />
                          </div>
                          <span className="text-foreground text-[12.5px] tabular-nums">
                            {m.confidencePercent}%
                          </span>
                        </div>
                      )}
                    </td>
                    <td className="py-4 pr-4">
                      <ShadowIcon outcome={m.shadowOutcome} />
                    </td>
                    <td className="py-4 pr-4">
                      <OutcomePill item={m} />
                    </td>
                    <td className="py-4 pr-6">
                      <span
                        className={cn(
                          "rounded-full border px-2.5 py-1 text-[11px] font-semibold",
                          m.isGraded
                            ? "border-[var(--tone-pass-border)] bg-[var(--tone-pass-bg)] text-[var(--tone-pass-fg)]"
                            : "border-border bg-muted text-muted-foreground"
                        )}
                      >
                        {m.isGraded ? "Graded" : "Ungraded"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="text-muted-foreground text-[13px]">
              Rows per page
            </span>
            <select
              value={perPage}
              onChange={(e) => {
                setPerPage(Number(e.target.value))
                setPage(1)
              }}
              className="border-border bg-card h-8 rounded-md border px-2 text-[13px] outline-none"
              aria-label="Rows per page"
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground mr-2 text-[13px] tabular-nums">
              {total === 0 ? "0 of 0" : `${rangeStart}–${rangeEnd} of ${total}`}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="text-muted-foreground hover:bg-muted grid size-8 place-items-center rounded-md transition-colors disabled:opacity-40"
              disabled={current === 1}
              aria-label="Previous page"
            >
              <ChevronLeft className="size-4" />
            </button>
            {Array.from({ length: pages }, (_, i) => i + 1)
              .filter(
                (n) => pages <= 7 || Math.abs(n - current) <= 2 || n === 1 || n === pages
              )
              .map((n, idx, arr) => (
                <React.Fragment key={n}>
                  {idx > 0 && arr[idx - 1]! < n - 1 ? (
                    <span className="text-muted-foreground/50 px-1">…</span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setPage(n)}
                    className={cn(
                      "size-8 rounded-md text-[13px] font-semibold transition-colors",
                      n === current
                        ? "bg-primary text-primary-foreground"
                        : "text-foreground hover:bg-muted"
                    )}
                  >
                    {n}
                  </button>
                </React.Fragment>
              ))}
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              className="text-muted-foreground hover:bg-muted grid size-8 place-items-center rounded-md transition-colors disabled:opacity-40"
              disabled={current === pages}
              aria-label="Next page"
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
        </div>
      </Panel>
    </div>
  )
}
