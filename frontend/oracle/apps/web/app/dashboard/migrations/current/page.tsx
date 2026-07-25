import type { ReactNode } from "react"
import Link from "next/link"

import { Button, buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

import { CURRENT_MIGRATION, type RiskLevel } from "./data"
import { SqlCodePanel } from "./sql-panel"

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

function riskClass(level: RiskLevel) {
  if (level === "LOW") return "text-[var(--oracle-verified)]"
  if (level === "MEDIUM") return "text-amber-400/90"
  return "text-[var(--oracle-risk)]"
}

function AssessmentBlock({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="border-border/60 space-y-2.5 border-t pt-4">
      <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
        {label}
      </p>
      {children}
    </div>
  )
}

function ImpactRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-muted-foreground/65 font-mono text-[10px] tracking-[0.08em]">
        {label}
      </dt>
      <dd className="text-foreground/85 font-mono text-xs tracking-tight tabular-nums">
        {value}
      </dd>
    </div>
  )
}

export default function CurrentMigrationPage() {
  const migration = CURRENT_MIGRATION
  const { assessment, decision } = migration

  return (
    <div className="flex flex-1 flex-col gap-5 px-4 pb-8 md:px-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          href="/dashboard"
          className={cn(
            buttonVariants({ variant: "ghost", size: "sm" }),
            "text-muted-foreground hover:text-foreground -ml-2 font-mono text-[11px] tracking-tight"
          )}
        >
          ← Back to Overview
        </Link>
        <Link
          href="/dashboard/migrations/history"
          className="text-muted-foreground hover:text-foreground font-mono text-[11px] tracking-tight transition-colors"
        >
          Past Migrations →
        </Link>
      </div>

      <header className="space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <h1 className="text-foreground text-2xl font-medium tracking-tight">
              Current Migration
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
          <div className="flex flex-col items-start gap-1 sm:items-end">
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="bg-muted-foreground/70 size-1.5 shrink-0 rounded-full"
              />
              <span className="text-muted-foreground font-mono text-[11px] tracking-[0.14em] uppercase">
                {migration.status}
              </span>
            </div>
            <p className="text-muted-foreground/55 font-mono text-[10px] tracking-tight">
              submitted {migration.submittedAgo}
            </p>
          </div>
        </div>

        <div className="border-border/70 flex flex-col gap-3 border-t pt-3 sm:flex-row sm:items-center sm:justify-between">
          <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
            {migration.process.map((stage, index) => (
              <li key={stage.id} className="flex items-center gap-1.5">
                {index > 0 ? (
                  <span className="text-muted-foreground/35 font-mono text-[10px]">
                    →
                  </span>
                ) : null}
                <span
                  className={cn(
                    "font-mono text-[10px] tracking-[0.08em] uppercase",
                    stage.state === "complete" && "text-muted-foreground/65",
                    stage.state === "current" && "text-foreground",
                    stage.state === "pending" && "text-muted-foreground/35"
                  )}
                >
                  {stage.label}
                </span>
              </li>
            ))}
          </ol>
          <Link
            href="/dashboard/migrations/current/shadow"
            className={cn(
              buttonVariants({ variant: "outline" }),
              "w-full shrink-0 sm:w-auto"
            )}
          >
            View Shadow Execution
          </Link>
        </div>
      </header>

      <Section title="Migration">
        <SqlCodePanel filename={migration.filename} sql={migration.sql} />
        <p className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
          {migration.metadata.tablesAffected} tables affected
          <span className="text-muted-foreground/35 mx-1.5">·</span>
          {migration.metadata.indexes} indexes
          <span className="text-muted-foreground/35 mx-1.5">·</span>
          {migration.metadata.statements} statements
        </p>
      </Section>

      <Section title="Analysis">
        <div className="space-y-1">
          <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
            Migration assessment
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-0.5">
              <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
                Recommendation
              </p>
              <p className="font-mono text-xs tracking-[0.08em] text-amber-400/90 uppercase">
                {assessment.recommendation}
              </p>
            </div>
            <div className="space-y-0.5">
              <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
                Overall risk
              </p>
              <p
                className={cn(
                  "font-mono text-xs tracking-[0.08em] uppercase",
                  riskClass(assessment.overallRisk)
                )}
              >
                {assessment.overallRisk}
              </p>
            </div>
            <div className="space-y-0.5">
              <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
                Confidence
              </p>
              <p className="font-mono text-xs tracking-tight text-[var(--oracle-reasoning-soft)]">
                {assessment.confidence}
              </p>
            </div>
          </div>
        </div>

        <AssessmentBlock label="What this migration does">
          <p className="text-foreground/80 max-w-3xl text-sm leading-relaxed">
            {assessment.summary}
          </p>
        </AssessmentBlock>

        <AssessmentBlock label="Benefits">
          <ul className="space-y-1.5">
            {assessment.benefits.map((item) => (
              <li
                key={item}
                className="flex gap-2 text-sm leading-relaxed text-foreground/80"
              >
                <span className="shrink-0 font-mono text-[var(--oracle-verified)]">
                  +
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </AssessmentBlock>

        <AssessmentBlock label="Concerns">
          <ul className="space-y-1.5">
            {assessment.concerns.map((item) => (
              <li
                key={item}
                className="flex gap-2 text-sm leading-relaxed text-foreground/80"
              >
                <span className="shrink-0 font-mono text-amber-400/90">!</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </AssessmentBlock>

        <AssessmentBlock label="Expected impact">
          <dl className="max-w-md space-y-1.5">
            <ImpactRow
              label="Predicted Runtime"
              value={assessment.expectedImpact.predictedRuntime}
            />
            <ImpactRow
              label="Expected Storage"
              value={assessment.expectedImpact.expectedStorage}
            />
            <ImpactRow
              label="Tables Affected"
              value={String(assessment.expectedImpact.tablesAffected)}
            />
            <ImpactRow
              label="Indexes Created"
              value={String(assessment.expectedImpact.indexesCreated)}
            />
            <ImpactRow
              label="Constraints Added"
              value={String(assessment.expectedImpact.constraintsAdded)}
            />
          </dl>
          <p className="text-[var(--oracle-reasoning-soft)]/80 pt-1 font-mono text-[10px] tracking-tight">
            Model prediction · {assessment.confidence} confidence
          </p>
        </AssessmentBlock>

        <AssessmentBlock label="Risk breakdown">
          <dl className="max-w-md space-y-1.5">
            {(
              [
                ["Lock Risk", assessment.riskBreakdown.lockRisk],
                ["Rollback Risk", assessment.riskBreakdown.rollbackRisk],
                ["Data Loss Risk", assessment.riskBreakdown.dataLossRisk],
                ["Performance Risk", assessment.riskBreakdown.performanceRisk],
              ] as const
            ).map(([label, level]) => (
              <div
                key={label}
                className="flex items-baseline justify-between gap-4"
              >
                <dt className="text-muted-foreground/65 font-mono text-[10px] tracking-[0.08em]">
                  {label}
                </dt>
                <dd
                  className={cn(
                    "font-mono text-xs tracking-[0.08em] uppercase",
                    riskClass(level)
                  )}
                >
                  {level}
                </dd>
              </div>
            ))}
          </dl>
        </AssessmentBlock>

        <AssessmentBlock label="Recommended actions">
          <ul className="space-y-1.5">
            {assessment.recommendedActions.map((item) => (
              <li
                key={item}
                className="flex gap-2 text-sm leading-relaxed text-foreground/80"
              >
                <span className="text-muted-foreground/50 shrink-0 font-mono">
                  →
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </AssessmentBlock>

        <AssessmentBlock label="Reasoning">
          <p className="text-muted-foreground max-w-3xl text-sm leading-relaxed">
            {assessment.reasoning}
          </p>
        </AssessmentBlock>
      </Section>

      <Section title="Decision">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="size-1.5 rounded-full bg-[var(--oracle-verified)]"
          />
          <p className="font-mono text-sm tracking-[0.12em] text-[var(--oracle-verified)] uppercase">
            {decision.verdict}
          </p>
        </div>

        <p className="text-muted-foreground max-w-3xl text-sm leading-relaxed">
          {decision.recommendation}
        </p>

        <div className="flex flex-col-reverse gap-2 border-t border-border/60 pt-4 sm:flex-row sm:justify-end">
          <Button variant="outline" className="sm:min-w-28">
            Reject
          </Button>
          <Button className="sm:min-w-40">Approve Migration</Button>
        </div>
      </Section>
    </div>
  )
}
