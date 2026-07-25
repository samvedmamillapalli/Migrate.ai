import type { ReactNode } from "react"
import Link from "next/link"

import { cn } from "@workspace/ui/lib/utils"

import type { MigrationRun } from "../data"

function Section({
  title,
  children,
  className,
}: {
  title: string
  children: ReactNode
  className?: string
}) {
  return (
    <section
      aria-label={title}
      className={cn(
        "border-border flex w-full flex-col gap-4 rounded-lg border p-4",
        className
      )}
    >
      <h2 className="text-muted-foreground text-[11px] font-medium tracking-[0.16em] uppercase">
        {title}
      </h2>
      {children}
    </section>
  )
}

function MetricRow({
  label,
  value,
  valueClassName,
}: {
  label: string
  value: string
  valueClassName?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-muted-foreground/65 font-mono text-[10px] tracking-[0.12em] uppercase">
        {label}
      </dt>
      <dd
        className={cn(
          "text-foreground/85 font-mono text-xs tracking-tight",
          valueClassName
        )}
      >
        {value}
      </dd>
    </div>
  )
}

function ClusterTopology() {
  return (
    <svg
      viewBox="0 0 120 100"
      className="text-muted-foreground/55 h-16 w-24"
      aria-hidden
    >
      <line
        x1="60"
        y1="18"
        x2="22"
        y2="82"
        stroke="currentColor"
        strokeWidth="1"
      />
      <line
        x1="60"
        y1="18"
        x2="98"
        y2="82"
        stroke="currentColor"
        strokeWidth="1"
      />
      <line
        x1="22"
        y1="82"
        x2="98"
        y2="82"
        stroke="currentColor"
        strokeWidth="1"
      />
      <circle
        cx="60"
        cy="18"
        r="5"
        fill="var(--background)"
        stroke="currentColor"
        strokeWidth="1.25"
      />
      <circle
        cx="22"
        cy="82"
        r="5"
        fill="var(--background)"
        stroke="currentColor"
        strokeWidth="1.25"
      />
      <circle
        cx="98"
        cy="82"
        r="5"
        fill="var(--background)"
        stroke="currentColor"
        strokeWidth="1.25"
      />
    </svg>
  )
}

/** Existing completed Shadow Execution results UI — keep unchanged. */
export function CompletedShadowExecution({
  migration,
}: {
  migration: MigrationRun
}) {
  const { shadow, decision } = migration

  return (
    <div className="flex flex-1 flex-col gap-5 px-4 pb-8 md:px-6">
      <header className="space-y-3">
        <nav
          aria-label="Breadcrumb"
          className="text-muted-foreground flex flex-wrap items-center gap-1.5 font-mono text-[11px] tracking-tight"
        >
          <Link
            href="/dashboard/migrations/current"
            className="hover:text-foreground transition-colors"
          >
            Current Migration
          </Link>
          <span className="text-muted-foreground/40">/</span>
          <span className="text-foreground">Shadow Execution</span>
        </nav>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <h1 className="text-foreground text-2xl font-medium tracking-tight">
              Shadow Execution
            </h1>
            <p className="text-foreground/90 truncate font-mono text-sm tracking-tight">
              {migration.filename}
            </p>
            <p className="text-muted-foreground font-mono text-xs tracking-tight">
              {migration.sourceDb}
              <span className="text-muted-foreground/50 mx-2">→</span>
              {migration.targetDb}
            </p>
          </div>
          <div className="flex items-center gap-2 self-start">
            <span
              aria-hidden
              className="size-1.5 shrink-0 rounded-full bg-[var(--oracle-verified)]"
            />
            <span className="font-mono text-[11px] tracking-[0.14em] text-[var(--oracle-verified)] uppercase">
              {shadow.status}
            </span>
          </div>
        </div>
      </header>

      <Section title="Shadow Cluster">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,14rem)_1fr]">
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-foreground/85 font-mono text-xs tracking-tight">
                {shadow.id}
              </p>
              <div className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="size-1.5 rounded-full bg-[var(--oracle-verified)]"
                />
                <span className="font-mono text-[10px] tracking-[0.12em] text-[var(--oracle-verified)] uppercase">
                  {shadow.status}
                </span>
              </div>
            </div>
            <div className="text-muted-foreground font-mono text-[10px] leading-relaxed tracking-tight">
              <p>{shadow.engine}</p>
              {shadow.region ? (
                <p className="text-muted-foreground/70">{shadow.region}</p>
              ) : null}
              <p className="text-muted-foreground/50">{shadow.lifecycle}</p>
            </div>
            <div className="flex justify-center py-2">
              <ClusterTopology />
            </div>
          </div>

          <div className="min-w-0 space-y-1 border-t border-border/50 pt-3 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-6">
            <p className="text-muted-foreground/60 mb-2 font-mono text-[10px] tracking-[0.12em] uppercase">
              Execution history
            </p>
            <ul className="space-y-1.5">
              {shadow.events.map((event) => (
                <li
                  key={`${event.time}-${event.message}`}
                  className="flex gap-3 font-mono text-[11px] tracking-tight"
                >
                  <span className="text-muted-foreground/45 w-14 shrink-0 tabular-nums">
                    {event.time}
                  </span>
                  <span className="text-foreground/80">{event.message}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="border-border/60 space-y-2 border-t pt-4">
          <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
            Observed results
          </p>
          <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <MetricRow label="Runtime" value={shadow.observed.runtime} />
            <MetricRow label="Storage" value={shadow.observed.storage} />
            <MetricRow
              label="Statements"
              value={`${shadow.observed.statementsCompleted} / ${shadow.observed.statementsTotal}`}
            />
            <MetricRow
              label="Blocking locks"
              value={String(shadow.observed.blockingLocks)}
            />
            <MetricRow
              label="Failures"
              value={String(shadow.observed.failures)}
            />
            <MetricRow
              label="Rollback test"
              value={shadow.observed.rollbackTest}
              valueClassName="text-[var(--oracle-verified)]"
            />
          </dl>
        </div>
      </Section>

      <Section title="Prediction vs Actual">
        <dl className="space-y-2.5">
          {decision.comparisons.map((row) => (
            <div
              key={row.label}
              className="grid gap-1 border-b border-border/40 pb-2.5 last:border-b-0 last:pb-0 sm:grid-cols-[7rem_1fr_auto] sm:items-baseline sm:gap-4"
            >
              <dt className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
                {row.label}
              </dt>
              <dd className="text-foreground/85 font-mono text-xs tracking-tight">
                {row.predicted}
                <span className="text-muted-foreground/40 mx-1.5">→</span>
                {row.actual}
              </dd>
              {row.delta ? (
                <span className="text-muted-foreground font-mono text-[11px] tracking-tight sm:text-right">
                  {row.delta}
                </span>
              ) : null}
            </div>
          ))}
          <div className="grid gap-1 sm:grid-cols-[7rem_1fr] sm:items-baseline sm:gap-4">
            <dt className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
              Confidence
            </dt>
            <dd className="font-mono text-xs tracking-tight text-[var(--oracle-reasoning-soft)]">
              {decision.confidence}
            </dd>
          </div>
        </dl>
      </Section>
    </div>
  )
}
