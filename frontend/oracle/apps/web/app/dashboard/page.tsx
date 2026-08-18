"use client"

import * as React from "react"
import Link from "next/link"
import { ArrowRight, Plus } from "lucide-react"

import {
  type AccuracyMetrics,
  type ActivityEvent,
  type MigrationRunSummary,
  getAccuracyMetrics,
  getActivityFeed,
  listRuns,
} from "@/lib/api/endpoints"
import { mapRunListItem, migrationSummaryLabel } from "@/lib/api/map-run"
import {
  getActiveWorkspaceId,
  getOwnerIdentity,
  setCurrentRunId,
} from "@/lib/api/owner"
import { AUTH_READY_EVENT } from "@/lib/api/clerk-token"
import {
  type AccuracyTrendPoint,
  AnalyticsChartHeader,
  AccuracyTrendChart,
  ApprovalDecisionChart,
  type ApprovalDecisionBucket,
  ChartTheme,
  RiskLevelBarChart,
  type RiskLevelBucket,
  RuntimeScatterChart,
  RuntimeScatterLegend,
  type RuntimeScatterPoint,
} from "@/components/analytics-charts"
import {
  EmptyNote,
  ErrorNote,
  Label,
  PageHeader,
  Panel,
  SkeletonLines,
  StatusPill,
  ToneDot,
  type Tone,
} from "@workspace/ui/components/ui-kit"

const CHART_H = 168

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return null
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return []
  return value.map((v) => asRecord(v) ?? {})
}

const ACTIVITY_TONES: Record<string, Tone> = {
  emerald: "pass",
  blue: "info",
  violet: "model",
  amber: "warn",
  red: "fail",
}

function clockLabel(iso: string | null): string {
  if (!iso) return "—"
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return "—"
  return new Date(t).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function DashboardPage() {
  const [runs, setRuns] = React.useState<MigrationRunSummary[] | null>(null)
  const [runsError, setRunsError] = React.useState<string | null>(null)
  const [activity, setActivity] = React.useState<ActivityEvent[] | null>(null)
  const [activityError, setActivityError] = React.useState<string | null>(null)
  const [metrics, setMetrics] = React.useState<AccuracyMetrics | null>(null)
  const [metricsError, setMetricsError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      const owner = getOwnerIdentity()
      const workspaceId = getActiveWorkspaceId()
      const scope = {
        ...(owner ? { owner_identity: owner } : {}),
        ...(workspaceId ? { workspace_id: workspaceId } : {}),
      }
      const [runsRes, activityRes, metricsRes] = await Promise.allSettled([
        listRuns({ limit: 5, exclude_kinds: "chaos,debug", ...scope }),
        getActivityFeed({ limit: 6, ...scope }),
        getAccuracyMetrics({
          owner_identity: owner || undefined,
          workspace_id: workspaceId || undefined,
        }),
      ])
      if (cancelled) return

      if (runsRes.status === "fulfilled") {
        setRuns(runsRes.value.items)
        setRunsError(null)
      } else {
        setRunsError(
          runsRes.reason instanceof Error
            ? runsRes.reason.message
            : "Failed to load runs"
        )
      }
      if (activityRes.status === "fulfilled") {
        setActivity(activityRes.value.items)
        setActivityError(null)
      } else {
        setActivityError(
          activityRes.reason instanceof Error
            ? activityRes.reason.message
            : "Failed to load activity"
        )
      }
      if (metricsRes.status === "fulfilled") {
        setMetrics(metricsRes.value)
        setMetricsError(null)
      } else {
        setMetricsError(
          metricsRes.reason instanceof Error
            ? metricsRes.reason.message
            : "Failed to load accuracy metrics"
        )
      }
      setLoading(false)
    }
    void load()
    // A ticket/magic-link sign-in resolves Clerk's auth state mid-render
    // rather than before this page ever mounts, so the very first `load()`
    // above can lose the race and land with no bearer token — a real,
    // permanent 401 with nothing to make it retry. Re-running once auth
    // actually comes online recovers that case for free without touching
    // the normal-login path, where the getter is already registered by
    // the time this effect runs and this listener just never fires again.
    window.addEventListener(AUTH_READY_EVENT, load)
    return () => {
      cancelled = true
      window.removeEventListener(AUTH_READY_EVENT, load)
    }
  }, [])

  const latest = runs && runs.length > 0 ? mapRunListItem(runs[0]!) : null

  const approvals = asRecord(metrics?.approval_breakdown)

  const trendPoints: AccuracyTrendPoint[] = asRecordArray(
    metrics?.scalar_accuracy_trend
  )
    .map((row) => ({
      createdAt: String(row.created_at ?? ""),
      score: Number(row.scalar_accuracy_score ?? NaN),
      scaleTier: row.scale_tier != null ? String(row.scale_tier) : null,
      outcomeClass: row.outcome_class != null ? String(row.outcome_class) : null,
    }))
    .filter((p) => p.createdAt && !Number.isNaN(p.score))

  const scatterPoints: RuntimeScatterPoint[] = asRecordArray(
    metrics?.runtime_scatter
  )
    .map((row) => ({
      runId: String(row.migration_run_id ?? ""),
      predictedSeconds: Number(row.estimated_duration_seconds ?? NaN),
      actualSeconds: Number(row.actual_duration_seconds ?? NaN),
      outcomeClass: row.outcome_class != null ? String(row.outcome_class) : null,
    }))
    .filter(
      (p) =>
        p.runId &&
        !Number.isNaN(p.predictedSeconds) &&
        !Number.isNaN(p.actualSeconds)
    )

  const approvalBuckets: ApprovalDecisionBucket[] = (
    [
      "proceed",
      "accept_recommended",
      "cancel",
      "awaiting_decision",
    ] as const
  ).map((decision) => ({
    decision,
    count: Number(approvals?.[decision] ?? 0),
  }))

  const riskBuckets: RiskLevelBucket[] = asRecordArray(
    metrics?.risk_level_distribution
  )
    .filter((row) =>
      ["low", "medium", "high", "critical"].includes(String(row.risk_level))
    )
    .map((row) => ({
      level: String(row.risk_level) as RiskLevelBucket["level"],
      count: Number(row.n ?? 0),
    }))

  return (
    <div
      // No top padding here on purpose — DashboardLayout's wrapper already
      // supplies pt-5/md:pt-7 for every dashboard page. This page used to
      // carry its own top padding too (from back when the layout had none),
      // which double-stacked into a visibly larger gap above "Overview"
      // than every other dashboard page has above its own title.
      className="mx-auto flex h-full min-h-0 w-full max-w-[1500px] flex-col overflow-hidden px-6 pb-4 lg:px-10 lg:pb-5"
    >
      <PageHeader
        compact
        title="Overview"
        subtitle="Track migration analyses and prediction accuracy."
        action={
          <Link
            href="/dashboard/migrations/new"
            className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold shadow-sm transition-all duration-150 active:scale-[0.98]"
          >
            <Plus className="size-4" />
            New Migration
          </Link>
        }
      />

      <div className="grid shrink-0 grid-cols-1 items-start gap-3 xl:grid-cols-2">
        <Panel className="self-start" delay={0.04}>
          <div className="px-4 py-3 sm:px-5">
            <div className="mb-2 flex items-center justify-between gap-3">
              <Label>Latest Migration</Label>
              {latest ? <StatusPill status={latest.status} /> : null}
            </div>
            {runsError ? (
              <ErrorNote>{runsError}</ErrorNote>
            ) : loading ? (
              <SkeletonLines lines={2} />
            ) : !latest ? (
              <EmptyNote>
                No migration runs yet. Create one to get started.
              </EmptyNote>
            ) : (
              <>
                {/* Plain-English summary instead of a truncated SQL statement —
                    the full SQL is one click away on the run detail page. */}
                <div className="text-foreground text-[14px] font-medium">
                  {migrationSummaryLabel(latest.migrationSql)}
                </div>
                <div className="text-muted-foreground mt-1.5 text-[12px]">
                  {latest.createdAgo}
                </div>
                <div className="mt-2.5 flex flex-wrap items-center gap-3">
                  <Link
                    href="/dashboard/migrations/current"
                    onClick={() => setCurrentRunId(latest.id)}
                    className="border-border bg-secondary text-foreground hover:bg-muted rounded-lg border px-3 py-1.5 text-[12px] font-semibold transition-colors active:scale-[0.98]"
                  >
                    Set as current
                  </Link>
                  <Link
                    href={`/dashboard/migrations/${latest.id}`}
                    className="text-primary inline-flex items-center gap-1 text-[12px] font-semibold hover:underline"
                  >
                    View detail <ArrowRight className="size-3.5" />
                  </Link>
                </div>
              </>
            )}
          </div>
          {/* The "Recent" list was removed — it repeated the Past Migrations
              page in a narrower column and showed raw SQL. "Recent Activity"
              below is a different panel (a timeline of what happened) and
              stays. */}
        </Panel>

        <Panel className="self-start px-4 py-3 sm:px-5" delay={0.06}>
          <Label className="mb-2">Recent Activity</Label>
          {activityError ? (
            <ErrorNote>{activityError}</ErrorNote>
          ) : loading ? (
            <SkeletonLines lines={3} />
          ) : !activity || activity.length === 0 ? (
            <EmptyNote>No activity recorded yet.</EmptyNote>
          ) : (
            // Capped + scrollable rather than growing with however many
            // events there are -- this card sits next to "Latest Migration"
            // in the same row, and an unbounded activity list was making it
            // grow much taller than its neighbor, leaving a visible gap
            // between that row and the analytics panel below it.
            <div className="max-h-[130px] space-y-2 overflow-y-auto pr-1">
              {activity.slice(0, 4).map((a, i) => (
                <div
                  key={`${a.migration_run_id}-${a.kind}-${a.at}-${i}`}
                  className="flex gap-3 text-[12.5px]"
                >
                  <span className="text-muted-foreground w-11 shrink-0 tabular-nums">
                    {clockLabel(a.at)}
                  </span>
                  <ToneDot
                    tone={ACTIVITY_TONES[a.tone] ?? "neutral"}
                    className="mt-1.5"
                  />
                  <p className="text-muted-foreground flex-1">
                    <span className="text-foreground font-semibold">
                      {a.kind}
                    </span>
                    <span className="text-border px-1.5">·</span>
                    {a.text}
                  </p>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel
        className="analytics-charts mt-3 flex min-h-0 flex-1 flex-col overflow-hidden px-4 py-3 sm:px-5 sm:py-3.5"
        delay={0.12}
      >
        <ChartTheme />
        {metricsError ? (
          <div className="mb-2 shrink-0">
            <ErrorNote>{metricsError}</ErrorNote>
          </div>
        ) : null}
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-x-6 gap-y-3 overflow-hidden xl:grid-cols-2">
            <div className="flex min-h-0 min-w-0 flex-col">
              <AnalyticsChartHeader>
                Prediction Accuracy Over Time
              </AnalyticsChartHeader>
              <div className="min-h-0 flex-1">
                <AccuracyTrendChart
                  points={trendPoints}
                  loading={loading}
                  height={CHART_H}
                />
              </div>
            </div>
            <div className="flex min-h-0 min-w-0 flex-col">
              <AnalyticsChartHeader>
                Predicted vs. Actual Runtime
              </AnalyticsChartHeader>
              {/* flex-col, not a bare flex-1 div: the chart grows to fill
                  whatever space the grid row actually has (varies by
                  viewport height), while the legend below it keeps its own
                  natural size instead of being squeezed to make room. */}
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="min-h-0 flex-1">
                  <RuntimeScatterChart
                    points={scatterPoints}
                    loading={loading}
                    height={CHART_H}
                  />
                </div>
                {!loading && scatterPoints.length > 0 ? (
                  <RuntimeScatterLegend />
                ) : null}
              </div>
            </div>
          </div>
          <div className="grid shrink-0 grid-cols-1 gap-x-6 gap-y-2 xl:grid-cols-2">
            <div className="min-w-0">
              <AnalyticsChartHeader>Approval Decisions</AnalyticsChartHeader>
              <ApprovalDecisionChart
                buckets={approvalBuckets}
                loading={loading}
                compact
              />
            </div>
            <div className="min-w-0">
              <AnalyticsChartHeader>Risk Level Distribution</AnalyticsChartHeader>
              <RiskLevelBarChart
                buckets={riskBuckets}
                loading={loading}
                compact
              />
            </div>
          </div>
        </div>
      </Panel>
    </div>
  )
}
