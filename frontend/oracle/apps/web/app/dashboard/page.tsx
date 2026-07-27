"use client"

import * as React from "react"
import Link from "next/link"

import { NewMigrationDialog } from "@/components/new-migration-dialog"
import {
  type AccuracyMetrics,
  type HealthResponse,
  type MigrationRunSummary,
  getAccuracyMetrics,
  getHealth,
  isSfnReady,
  listRuns,
} from "@/lib/api/endpoints"
import { mapRunListItem } from "@/lib/api/map-run"
import { getOwnerIdentity, setCurrentRunId } from "@/lib/api/owner"
import { buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

function Section({
  title,
  children,
  className,
  action,
}: {
  title: string
  children: React.ReactNode
  className?: string
  action?: React.ReactNode
}) {
  return (
    <section
      aria-label={title}
      className={cn(
        "border-border flex w-full flex-col gap-3 rounded-lg border p-4",
        className
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-muted-foreground text-[11px] font-medium tracking-[0.16em] uppercase">
          {title}
        </p>
        {action}
      </div>
      {children}
    </section>
  )
}

function StatusDot({ ok }: { ok: boolean | null }) {
  return (
    <span
      aria-hidden
      className={cn(
        "size-1.5 shrink-0 rounded-full",
        ok === null
          ? "bg-muted-foreground/40"
          : ok
            ? "bg-[var(--oracle-verified)]"
            : "bg-[var(--oracle-risk)]"
      )}
    />
  )
}

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
  if (den === 0) return `0 / 0`
  return `${num} / ${den}${pct != null ? ` · ${pct}%` : ""}`
}

export default function DashboardPage() {
  const [health, setHealth] = React.useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = React.useState<string | null>(null)
  const [runs, setRuns] = React.useState<MigrationRunSummary[] | null>(null)
  const [runsError, setRunsError] = React.useState<string | null>(null)
  const [metrics, setMetrics] = React.useState<AccuracyMetrics | null>(null)
  const [metricsError, setMetricsError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      const owner = getOwnerIdentity()
      const [healthRes, runsRes, metricsRes] = await Promise.allSettled([
        getHealth(),
        listRuns({
          limit: 5,
          ...(owner ? { owner_identity: owner } : {}),
        }),
        getAccuracyMetrics(),
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

  const trend = Array.isArray(metrics?.scalar_accuracy_trend)
    ? (metrics!.scalar_accuracy_trend as unknown[])
    : []
  const recRates = asRecord(metrics?.recommendation_rates)
  const acceptance = asRecord(recRates?.acceptance)
  const success = asRecord(recRates?.success)
  const memoryCorpus = asRecord(metrics?.memory_corpus)

  const integrations = health?.integrations
  const sfnReady = health ? isSfnReady(health) : null
  const bedrockReady =
    typeof integrations?.bedrock_configured === "boolean"
      ? integrations.bedrock_configured
      : null
  const apiOk = health ? health.status === "healthy" : null

  return (
    <div className="flex flex-1 flex-col gap-6 px-4 pb-6 md:px-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col gap-1">
          <h1 className="text-foreground text-2xl font-medium tracking-tight">
            Overview
          </h1>
          <p className="text-muted-foreground text-sm">
            Your migration environment.
          </p>
        </div>
        <NewMigrationDialog />
      </div>

      <Section title="System Health">
        {healthError ? (
          <p className="text-[var(--oracle-risk)] font-mono text-xs tracking-tight">
            {healthError}
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="flex items-center gap-2">
              <StatusDot ok={apiOk} />
              <span className="text-foreground/85 font-mono text-xs tracking-tight">
                API
              </span>
              <span className="text-muted-foreground/60 font-mono text-[11px] tracking-tight">
                {apiOk == null
                  ? loading
                    ? "…"
                    : "unknown"
                  : apiOk
                    ? "Ready"
                    : "Needs setup"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <StatusDot ok={sfnReady} />
              <span className="text-foreground/85 font-mono text-xs tracking-tight">
                Shadow
              </span>
              <span className="text-muted-foreground/60 font-mono text-[11px] tracking-tight">
                {sfnReady == null
                  ? "unknown"
                  : sfnReady
                    ? "Ready"
                    : "Needs setup"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <StatusDot ok={bedrockReady} />
              <span className="text-foreground/85 font-mono text-xs tracking-tight">
                Predictions
              </span>
              <span className="text-muted-foreground/60 font-mono text-[11px] tracking-tight">
                {bedrockReady == null
                  ? "unknown"
                  : bedrockReady
                    ? "Ready"
                    : "Needs setup"}
              </span>
            </div>
          </div>
        )}
      </Section>

      <Section title="Latest Migration">
        {runsError ? (
          <p className="text-[var(--oracle-risk)] font-mono text-xs tracking-tight">
            {runsError}
          </p>
        ) : !latest ? (
          <p className="text-muted-foreground text-sm leading-relaxed">
            {loading
              ? "Loading…"
              : "No migration runs yet. Create one to get started."}
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-baseline sm:justify-between sm:gap-6">
              <div className="min-w-0 space-y-1">
                <p className="text-foreground truncate font-mono text-sm tracking-tight">
                  {latest.sqlSnippet}
                </p>
                <p className="text-muted-foreground font-mono text-xs tracking-tight">
              {latest.createdAgo}
            </p>
              </div>
              <div className="flex items-center gap-2 self-start sm:self-auto">
                <span
                  aria-hidden
                  className={cn(
                    "size-1.5 shrink-0 rounded-full",
                    latest.isFailed
                      ? "bg-[var(--oracle-risk)]"
                      : latest.status === "completed"
                        ? "bg-[var(--oracle-verified)]"
                        : "bg-muted-foreground/60"
                  )}
                />
                <span
                  className={cn(
                    "font-mono text-[11px] tracking-[0.14em] uppercase",
                    latest.isFailed
                      ? "text-[var(--oracle-risk)]"
                      : latest.status === "completed"
                        ? "text-[var(--oracle-verified)]"
                        : "text-muted-foreground"
                  )}
                >
                  {latest.statusLabel}
                </span>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 border-t border-border/60 pt-3">
              <button
                type="button"
                onClick={() => setCurrentRunId(latest.id)}
                className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
              >
                Set as current
              </button>
              <Link
                href={`/dashboard/migrations/${latest.id}`}
                className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
              >
                View detail →
              </Link>
            </div>
          </div>
        )}

        {rest.length > 0 ? (
          <div className="space-y-1.5 border-t border-border/60 pt-3">
            <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
              Recent
            </p>
            <ul className="space-y-1.5">
              {rest.map((r) => (
                <li key={r.id}>
                  <Link
                    href={`/dashboard/migrations/${r.id}`}
                    className={cn(
                      "flex items-center justify-between gap-3 rounded-md px-1.5 py-1 font-mono text-[11px] tracking-tight transition-colors hover:bg-muted/40",
                      r.isFailed ? "text-[var(--oracle-risk)]" : "text-foreground/80"
                    )}
                  >
                    <span className="truncate">{r.sqlSnippet}</span>
                    <span className="text-muted-foreground/60 shrink-0 uppercase">
                      {r.statusLabel}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Section>

      <Section
        title="Accuracy"
        action={
          <Link
            href="/dashboard/memory"
            className="text-muted-foreground hover:text-foreground font-mono text-[10px] tracking-[0.1em] uppercase transition-colors"
          >
            Memory →
          </Link>
        }
      >
        {metricsError ? (
          <p className="text-[var(--oracle-risk)] font-mono text-xs tracking-tight">
            {metricsError}
          </p>
        ) : trend.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No graded runs yet.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="space-y-0.5">
              <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
                Graded
              </p>
              <p className="text-foreground font-mono text-lg tracking-tight">
                {trend.length}
              </p>
            </div>
            <div className="space-y-0.5">
              <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
                Accepted
              </p>
              <p className="text-foreground font-mono text-lg tracking-tight">
                {formatRate(
                  acceptance as {
                    numerator?: unknown
                    denominator?: unknown
                    rate?: unknown
                  } | null
                )}
              </p>
            </div>
            <div className="space-y-0.5">
              <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
                Succeeded
              </p>
              <p className="text-foreground font-mono text-lg tracking-tight">
                {formatRate(
                  success as {
                    numerator?: unknown
                    denominator?: unknown
                    rate?: unknown
                  } | null
                )}
              </p>
            </div>
          </div>
        )}

        {memoryCorpus ? (
          <div className="border-border/60 flex flex-wrap items-baseline gap-x-6 gap-y-1 border-t pt-3 font-mono text-[11px] tracking-tight">
            <span className="text-muted-foreground/60 uppercase">Memory</span>
            <span className="text-foreground/80">
              {String(memoryCorpus.memories_ready ?? 0)} ready
            </span>
            <span className="text-foreground/80">
              {String(memoryCorpus.pending ?? 0)} pending
            </span>
          </div>
        ) : null}
      </Section>
    </div>
  )
}
