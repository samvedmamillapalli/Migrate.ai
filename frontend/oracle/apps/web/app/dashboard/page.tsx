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
import { mapRunListItem } from "@/lib/api/map-run"
import {
  getActiveWorkspaceId,
  getOwnerIdentity,
  setCurrentRunId,
} from "@/lib/api/owner"
import {
  type AccuracyTrendPoint,
  AnalyticsChartHeader,
  AccuracyTrendChart,
  ChartTheme,
  MigrationTypeDonut,
  type MigrationTypeSlice,
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
  SqlBlock,
  StatusPill,
  ToneDot,
  toneText,
  type Tone,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

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
    return () => {
      cancelled = true
    }
  }, [])

  const latest = runs && runs.length > 0 ? mapRunListItem(runs[0]!) : null
  const rest = runs && runs.length > 1 ? runs.slice(1).map(mapRunListItem) : []

  const approvals = asRecord(metrics?.approval_breakdown)
  const memoryCorpus = asRecord(metrics?.memory_corpus)

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
        p.runId && !Number.isNaN(p.predictedSeconds) && !Number.isNaN(p.actualSeconds)
    )

  const typeSlices: MigrationTypeSlice[] = asRecordArray(
    metrics?.migration_type_distribution
  )
    .map((row) => ({
      type: String(row.migration_type ?? "unknown"),
      count: Number(row.n ?? 0),
    }))
    .filter((s) => s.count > 0)

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
    <div className="mx-auto w-full max-w-[1500px] px-6 pb-10 lg:px-10">
      <PageHeader
        title="Overview"
        subtitle="Track your migration analyses and how well predictions hold up."
        action={
          <Link
            href="/dashboard/migrations/new"
            className="bg-primary text-primary-foreground hover:bg-primary/90 inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold shadow-sm transition-all duration-150 active:scale-[0.98]"
          >
            <Plus className="size-4" />
            New Migration
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {/* Latest Migration + Recent */}
        <Panel delay={0.04}>
          <div className="px-6 py-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <Label>Latest Migration</Label>
              {latest ? <StatusPill status={latest.status} /> : null}
            </div>
            {runsError ? (
              <ErrorNote>{runsError}</ErrorNote>
            ) : loading ? (
              <SkeletonLines lines={3} />
            ) : !latest ? (
              <EmptyNote>
                No migration runs yet. Create one to get started.
              </EmptyNote>
            ) : (
              <>
                <div className="bg-muted/70 rounded-lg px-4 py-3">
                  <SqlBlock>{latest.sqlSnippet}</SqlBlock>
                </div>
                <div className="text-muted-foreground mt-3 text-[13px]">
                  {latest.createdAgo}
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-4">
                  <Link
                    href="/dashboard/migrations/current"
                    onClick={() => setCurrentRunId(latest.id)}
                    className="border-border bg-secondary text-foreground hover:bg-muted rounded-lg border px-3.5 py-2 text-[13px] font-semibold transition-colors active:scale-[0.98]"
                  >
                    Set as current
                  </Link>
                  <Link
                    href={`/dashboard/migrations/${latest.id}`}
                    className="text-primary inline-flex items-center gap-1 text-[13px] font-semibold hover:underline"
                  >
                    View detail <ArrowRight className="size-3.5" />
                  </Link>
                </div>
              </>
            )}
          </div>
          {rest.length > 0 ? (
            <div className="border-border border-t px-6 py-5">
              <Label className="mb-3">Recent</Label>
              <div className="space-y-2.5">
                {rest.map((m) => (
                  <Link
                    key={m.id}
                    href={`/dashboard/migrations/${m.id}`}
                    className="flex items-center justify-between gap-3"
                  >
                    <SqlBlock className="min-w-0 flex-1 truncate text-[12px]">
                      {m.sqlSnippet}
                    </SqlBlock>
                    <StatusPill status={m.status} />
                  </Link>
                ))}
              </div>
            </div>
          ) : null}
        </Panel>

        {/* Recent Activity */}
        <Panel className="px-6 py-5" delay={0.06}>
          <Label className="mb-4">Recent Activity</Label>
          {activityError ? (
            <ErrorNote>{activityError}</ErrorNote>
          ) : loading ? (
            <SkeletonLines lines={5} />
          ) : !activity || activity.length === 0 ? (
            <EmptyNote>No activity recorded yet.</EmptyNote>
          ) : (
            <div className="space-y-4">
              {activity.map((a, i) => (
                <div
                  key={`${a.migration_run_id}-${a.kind}-${a.at}-${i}`}
                  className="flex gap-3 text-[13px]"
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

      {/* Approval decisions */}
      <Panel className="mt-5 px-6 py-5" delay={0.1}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <Label>Approval Decisions</Label>
          <Link
            href="/dashboard/memory"
            className="text-primary inline-flex items-center gap-1 text-[11px] font-bold tracking-[0.08em] uppercase hover:underline"
          >
            Memory <ArrowRight className="size-3" />
          </Link>
        </div>
        {metricsError ? (
          <ErrorNote>{metricsError}</ErrorNote>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {(
              [
                ["proceed", "Proceeded", "", "Approved and sent to a shadow test."],
                [
                  "accept_recommended",
                  "Accepted Plan",
                  "",
                  "Plan accepted without running a shadow test.",
                ],
                ["cancel", "Cancelled", "", "Rejected by a reviewer."],
                [
                  "awaiting_decision",
                  "No Decision Yet",
                  "warn",
                  // Deliberately not called "Awaiting Decision": this counts
                  // every run without an approval row, which includes runs
                  // still being set up or predicted.
                  "Every run with no decision recorded, including ones still being set up or predicted.",
                ],
              ] as const
            ).map(([key, label, tone, help]) => (
              <div key={key} title={help}>
                <div className="section-label">{label}</div>
                <div
                  className={cn(
                    "mt-1.5 text-[26px] font-bold tabular-nums",
                    tone === "warn" ? toneText("warn") : "text-foreground"
                  )}
                >
                  {Number(approvals?.[key] ?? 0)}
                </div>
              </div>
            ))}
          </div>
        )}
        {memoryCorpus ? (
          <div className="border-border mt-5 flex items-center gap-3 border-t pt-4 text-[12px]">
            <span className="section-label">Memory</span>
            <span className="text-primary font-semibold">
              {String(memoryCorpus.memories_ready ?? 0)} ready
            </span>
            <span className="text-muted-foreground">
              {String(memoryCorpus.pending ?? 0)} pending
            </span>
          </div>
        ) : null}
      </Panel>

      {/* Migration intelligence — accuracy trend, predicted vs. actual
          runtime, migration-type mix, and risk-level distribution. */}
      <Panel className="analytics-charts mt-5 px-6 py-5" delay={0.16}>
        <ChartTheme />
        <div className="mb-5 flex items-center justify-between gap-3">
          <div>
            <Label>Migration Intelligence</Label>
            <p className="text-muted-foreground mt-1 text-[12.5px] leading-relaxed">
              How well predictions track reality across every graded run.
            </p>
          </div>
          {metricsError ? <ErrorNote>{metricsError}</ErrorNote> : null}
        </div>
        <div className="grid grid-cols-1 gap-x-8 gap-y-7 xl:grid-cols-2">
          <div>
            <AnalyticsChartHeader>Prediction Accuracy Over Time</AnalyticsChartHeader>
            <AccuracyTrendChart points={trendPoints} loading={loading} />
          </div>
          <div>
            <AnalyticsChartHeader>Predicted vs. Actual Runtime</AnalyticsChartHeader>
            <RuntimeScatterChart points={scatterPoints} loading={loading} />
            {!loading && scatterPoints.length > 0 ? <RuntimeScatterLegend /> : null}
          </div>
          <div>
            <AnalyticsChartHeader>Migration Type Distribution</AnalyticsChartHeader>
            <MigrationTypeDonut slices={typeSlices} loading={loading} />
          </div>
          <div>
            <AnalyticsChartHeader>Risk Level Distribution</AnalyticsChartHeader>
            <RiskLevelBarChart buckets={riskBuckets} loading={loading} />
          </div>
        </div>
      </Panel>
    </div>
  )
}
