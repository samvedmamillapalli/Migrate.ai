"use client"

import * as React from "react"
import Link from "next/link"
import { motion } from "motion/react"
import { ArrowRight, Plus } from "lucide-react"

import {
  type AccuracyMetrics,
  type ActivityEvent,
  type HealthResponse,
  type MigrationRunSummary,
  getAccuracyMetrics,
  getActivityFeed,
  getHealth,
  getMemoriesHealth,
  isSfnReady,
  listRuns,
  type CorpusHealth,
} from "@/lib/api/endpoints"
import { mapRunListItem, type RunListItem } from "@/lib/api/map-run"
import { getCurrentRunId, getOwnerIdentity, setCurrentRunId } from "@/lib/api/owner"
import {
  EmptyNote,
  ErrorNote,
  Label,
  PageHeader,
  Panel,
  SkeletonLines,
  SkeletonStats,
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

function formatRate(
  rate: { numerator?: unknown; denominator?: unknown; rate?: unknown } | null
): string {
  if (!rate) return "—"
  const num = Number(rate.numerator ?? 0)
  const den = Number(rate.denominator ?? 0)
  const pct = rate.rate == null ? null : Math.round(Number(rate.rate) * 100)
  if (den === 0) return "0 / 0"
  return `${num} / ${den}${pct != null ? ` · ${pct}%` : ""}`
}

/** One dependency in the System Health strip. `ok === null` means unknown. */
function Health({ name, ok }: { name: string; ok: boolean | null }) {
  return (
    <div className="flex items-center gap-2">
      <ToneDot tone={ok === null ? "neutral" : ok ? "pass" : "fail"} />
      <span className="text-foreground text-sm font-semibold">{name}</span>
      <span
        className={cn(
          "text-sm",
          ok === null
            ? "text-muted-foreground"
            : ok
              ? toneText("pass")
              : toneText("fail")
        )}
      >
        {ok === null ? "Unknown" : ok ? "Ready" : "Needs setup"}
      </span>
    </div>
  )
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

function riskLabel(item: RunListItem): React.ReactNode {
  if (!item.risk) {
    return <span className="text-muted-foreground">Risk not assessed</span>
  }
  return (
    <span className={cn("font-semibold capitalize", toneText(item.riskTone))}>
      {item.risk} Risk
    </span>
  )
}

export default function DashboardPage() {
  const [health, setHealth] = React.useState<HealthResponse | null>(null)
  const [corpus, setCorpus] = React.useState<CorpusHealth | null>(null)
  const [healthError, setHealthError] = React.useState<string | null>(null)
  const [runs, setRuns] = React.useState<MigrationRunSummary[] | null>(null)
  const [runsError, setRunsError] = React.useState<string | null>(null)
  const [queue, setQueue] = React.useState<MigrationRunSummary[] | null>(null)
  const [queueTotal, setQueueTotal] = React.useState(0)
  const [activity, setActivity] = React.useState<ActivityEvent[] | null>(null)
  const [activityError, setActivityError] = React.useState<string | null>(null)
  const [metrics, setMetrics] = React.useState<AccuracyMetrics | null>(null)
  const [metricsError, setMetricsError] = React.useState<string | null>(null)
  const [currentRun, setCurrentRun] = React.useState<RunListItem | null>(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      const owner = getOwnerIdentity()
      const scope = owner ? { owner_identity: owner } : {}
      const [
        healthRes,
        corpusRes,
        runsRes,
        queueRes,
        activityRes,
        metricsRes,
      ] = await Promise.allSettled([
        getHealth(),
        getMemoriesHealth(),
        listRuns({ limit: 5, exclude_kinds: "chaos,debug", ...scope }),
        listRuns({
          limit: 8,
          status: "awaiting_approval",
          exclude_kinds: "chaos,debug",
          ...scope,
        }),
        getActivityFeed({ limit: 6, ...scope }),
        getAccuracyMetrics({ owner_identity: owner || undefined }),
      ])
      if (cancelled) return

      if (healthRes.status === "fulfilled") {
        setHealth(healthRes.value)
        setHealthError(null)
      } else {
        setHealthError(
          healthRes.reason instanceof Error
            ? healthRes.reason.message
            : "Failed to load health"
        )
      }
      if (corpusRes.status === "fulfilled") setCorpus(corpusRes.value)

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
      if (queueRes.status === "fulfilled") {
        setQueue(queueRes.value.items)
        setQueueTotal(queueRes.value.total)
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

  // "Current Migration" = whatever run the workspace is pinned to, falling
  // back to the oldest thing still awaiting a decision, then to the newest
  // run. Never a placeholder.
  React.useEffect(() => {
    if (!runs && !queue) return
    const pinned = getCurrentRunId()
    const all = [...(queue ?? []), ...(runs ?? [])]
    const match = pinned ? all.find((r) => r.id === pinned) : undefined
    const chosen = match ?? queue?.[0] ?? runs?.[0]
    setCurrentRun(chosen ? mapRunListItem(chosen) : null)
  }, [runs, queue])

  const latest = runs && runs.length > 0 ? mapRunListItem(runs[0]!) : null
  const rest = runs && runs.length > 1 ? runs.slice(1).map(mapRunListItem) : []
  const queueItems = queue ? queue.map(mapRunListItem) : []

  const trend = Array.isArray(metrics?.scalar_accuracy_trend)
    ? (metrics!.scalar_accuracy_trend as unknown[])
    : []
  const successRate = asRecord(metrics?.migration_success_rate)
  const approvals = asRecord(metrics?.approval_breakdown)
  const memoryCorpus = asRecord(metrics?.memory_corpus)

  const integrations = health?.integrations
  const sfnReady = health ? isSfnReady(health) : null
  const bedrockReady =
    typeof integrations?.bedrock_configured === "boolean"
      ? integrations.bedrock_configured
      : null
  const apiOk = health ? health.status === "healthy" : null
  const memoryOk = corpus ? corpus.healthy !== false : null

  return (
    <div className="mx-auto w-full max-w-[1500px] px-6 pb-10 lg:px-10">
      <PageHeader
        title="Overview"
        subtitle="Your migration environment."
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

      <Panel className="mb-5 px-6 py-5">
        <Label className="mb-3">System Health</Label>
        {healthError ? (
          <ErrorNote>{healthError}</ErrorNote>
        ) : (
          <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
            <Health name="API" ok={apiOk} />
            <Health name="Shadow" ok={sfnReady} />
            <Health name="Predictions" ok={bedrockReady} />
            <Health name="Memory" ok={memoryOk} />
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          {/* Current Migration */}
          <Panel className="px-6 py-5" delay={0.04}>
            <div className="mb-4 flex items-center justify-between gap-3">
              <Label>Current Migration</Label>
              {currentRun ? <StatusPill status={currentRun.status} /> : null}
            </div>
            {loading ? (
              <SkeletonLines lines={4} />
            ) : !currentRun ? (
              <EmptyNote>
                No migration yet. Start one to see it here.
              </EmptyNote>
            ) : (
              <>
                <SqlBlock className="text-[14px] font-semibold">
                  {currentRun.sqlSnippet}
                </SqlBlock>
                <div className="text-muted-foreground mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
                  <span>
                    Stage:{" "}
                    <span className="text-foreground font-semibold">
                      {currentRun.statusLabel.toLowerCase()}
                    </span>
                  </span>
                  <span className="text-border">·</span>
                  <span>
                    Risk:{" "}
                    <span
                      className={cn(
                        "font-semibold",
                        toneText(currentRun.riskTone)
                      )}
                    >
                      {currentRun.risk ?? "not assessed"}
                    </span>
                  </span>
                  <span className="text-border">·</span>
                  <span>
                    Confidence:{" "}
                    <span className="text-foreground font-semibold">
                      {currentRun.confidencePercent == null
                        ? "—"
                        : `${currentRun.confidencePercent}%`}
                    </span>
                  </span>
                  {currentRun.durationLabel ? (
                    <>
                      <span className="text-border">·</span>
                      <span>
                        Measured duration:{" "}
                        <span className="text-foreground font-semibold">
                          {currentRun.durationLabel}
                        </span>
                      </span>
                    </>
                  ) : null}
                </div>
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--tone-warn-border)] bg-[var(--tone-warn-bg)] px-4 py-3">
                  <div className="flex flex-wrap items-center gap-3 text-[13px]">
                    <span className="text-[11px] font-bold tracking-[0.08em] text-[var(--tone-warn-fg)] uppercase">
                      Next Action
                    </span>
                    <span className="text-border">·</span>
                    <span className="text-foreground">
                      {nextActionText(currentRun)}
                    </span>
                  </div>
                  <Link
                    href="/dashboard/migrations/current"
                    onClick={() => setCurrentRunId(currentRun.id)}
                    className="text-primary inline-flex items-center gap-1 text-[13px] font-semibold hover:underline"
                  >
                    Review <ArrowRight className="size-3.5" />
                  </Link>
                </div>
              </>
            )}
          </Panel>

          {/* Decision Queue */}
          <Panel className="px-6 py-5" delay={0.08}>
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Label>Decision Queue</Label>
                {queueTotal > 0 ? (
                  <span className="rounded-full border border-[var(--tone-warn-border)] bg-[var(--tone-warn-bg)] px-2 py-0.5 text-[11px] font-bold text-[var(--tone-warn-fg)]">
                    {queueTotal}
                  </span>
                ) : null}
              </div>
              <Link
                href="/dashboard/migrations/history"
                className="text-primary inline-flex items-center gap-1 text-[13px] font-semibold hover:underline"
              >
                View all decisions <ArrowRight className="size-3.5" />
              </Link>
            </div>
            {loading ? (
              <SkeletonLines lines={3} />
            ) : queueItems.length === 0 ? (
              <EmptyNote>
                Nothing is waiting on a decision right now. Runs only appear
                here once a prediction has finished.
              </EmptyNote>
            ) : (
              <div className="space-y-2">
                {queueItems.map((q) => (
                  <motion.div key={q.id} whileHover={{ x: 2 }}>
                    <Link
                      href="/dashboard/migrations/current"
                      onClick={() => setCurrentRunId(q.id)}
                      className="bg-muted/70 hover:bg-muted flex flex-wrap items-center justify-between gap-3 rounded-lg px-4 py-3 transition-colors"
                    >
                      <SqlBlock className="min-w-0 flex-1">
                        {q.sqlSnippet}
                      </SqlBlock>
                      <div className="flex items-center gap-3 text-[12px]">
                        {riskLabel(q)}
                        <span className="text-muted-foreground">
                          {q.confidencePercent == null
                            ? "confidence pending"
                            : `${q.confidencePercent}% confidence`}
                        </span>
                      </div>
                    </Link>
                  </motion.div>
                ))}
              </div>
            )}
          </Panel>
        </div>

        <div className="space-y-5">
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

          {/* AI Insight */}
          <Panel
            className="border-[var(--tone-warn-border)] bg-[var(--tone-warn-bg)] px-6 py-5"
            delay={0.1}
          >
            <Label className="!text-primary mb-3">AI Insight</Label>
            <InsightBody
              corpus={corpus}
              successRate={successRate}
              loading={loading}
            />
            <Link
              href="/dashboard/memory"
              className="text-primary mt-4 inline-flex items-center gap-1 text-[13px] font-semibold hover:underline"
            >
              Supporting memories <ArrowRight className="size-3.5" />
            </Link>
          </Panel>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
        {/* Latest Migration + Recent */}
        <Panel delay={0.12}>
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

        {/* Accuracy + Approval decisions */}
        <Panel delay={0.14}>
          <div className="grid grid-cols-1 gap-6 px-6 py-5 sm:grid-cols-[1fr_1.6fr]">
            <div>
              <Label className="mb-3">Accuracy</Label>
              <div className="text-muted-foreground text-[13px]">Graded</div>
              <div className="text-foreground text-[44px] leading-none font-bold tracking-tight">
                {metricsError ? "—" : trend.length}
              </div>
            </div>
            <div className="sm:text-right">
              <div className="mb-3 flex items-center gap-2 sm:justify-end">
                <Label>Migration Success Rate</Label>
                <Link
                  href="/dashboard/memory"
                  className="text-primary inline-flex items-center gap-1 text-[11px] font-bold tracking-[0.08em] uppercase hover:underline"
                >
                  Memory <ArrowRight className="size-3" />
                </Link>
              </div>
              <div className="text-foreground text-[40px] leading-none font-bold tracking-tight tabular-nums">
                {metricsError
                  ? "—"
                  : formatRate(
                      successRate as {
                        numerator?: unknown
                        denominator?: unknown
                        rate?: unknown
                      } | null
                    )}
              </div>
              <p className="text-muted-foreground mt-3 text-[12px] leading-relaxed">
                % of graded runs whose shadow execution actually succeeded.
              </p>
            </div>
          </div>
          <div className="border-border border-t px-6 py-5">
            <Label className="mb-4">Approval Decisions</Label>
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
                      // still being set up or predicted — a larger set than the
                      // Decision Queue above, which is only awaiting_approval.
                      "Every run with no decision recorded, including ones still being set up or predicted. Wider than the Decision Queue.",
                    ],
                  ] as const
                ).map(([key, label, tone, help]) => (
                  <div key={key} title={help}>
                    <div className="section-label">{label}</div>
                    <div
                      className={cn(
                        "mt-1.5 text-[26px] font-bold tabular-nums",
                        tone === "warn"
                          ? toneText("warn")
                          : "text-foreground"
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
          </div>
        </Panel>
      </div>
    </div>
  )
}

/** Plain-language "what should I do next" for the pinned run. */
function nextActionText(item: RunListItem): string {
  switch (item.status) {
    case "pending":
      return "Connect a database and run the prediction."
    case "predicting":
      return "Prediction is running — the assessment will appear when it finishes."
    case "awaiting_approval":
      return item.policyDecision === "block"
        ? "Policy blocked this migration — review the risk flags before overriding."
        : "Review the assessment, then decide whether to run the shadow test."
    case "running":
      return "Shadow execution is in progress — watch the live results."
    case "completed":
      return "Finished. Review the measured outcome against the prediction."
    case "failed":
      return "This run failed or was cancelled — open it for the error detail."
    default:
      return "Open the run for detail."
  }
}

/**
 * AI Insight. States a fact drawn from the corpus and graded population, or
 * says plainly that there isn't enough evidence yet. Never a fixed claim.
 */
function InsightBody({
  corpus,
  successRate,
  loading,
}: {
  corpus: CorpusHealth | null
  successRate: Record<string, unknown> | null
  loading: boolean
}) {
  if (loading) {
    return <EmptyNote>Loading…</EmptyNote>
  }
  const ready = Number(corpus?.corpus_ready_count ?? 0)
  const graded = Number(successRate?.denominator ?? 0)
  const passed = Number(successRate?.numerator ?? 0)

  if (ready === 0 && graded === 0) {
    return (
      <p className="text-foreground text-[14px] leading-relaxed">
        No verified runs in memory yet. Complete a shadow test and the model
        will start grounding its confidence in your own migration history.
      </p>
    )
  }

  return (
    <p className="text-foreground text-[14px] leading-relaxed">
      Predictions are grounded in{" "}
      <span className="font-semibold">
        {ready} indexed {ready === 1 ? "memory" : "memories"}
      </span>
      {graded > 0 ? (
        <>
          {" "}
          and {graded} graded {graded === 1 ? "run" : "runs"}, of which{" "}
          <span className="font-semibold">
            {passed} passed shadow execution
          </span>
        </>
      ) : (
        <>, none of them graded yet</>
      )}
      .
    </p>
  )
}
