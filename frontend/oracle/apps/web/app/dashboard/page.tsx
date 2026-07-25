import { NewMigrationDialog } from "@/components/new-migration-dialog"
import { cn } from "@workspace/ui/lib/utils"

const STAGES = [
  { id: "analyze", label: "Analyze", state: "complete" },
  { id: "predict", label: "Predict", state: "complete" },
  { id: "shadow", label: "Shadow", state: "complete" },
  { id: "execute", label: "Execute", state: "complete" },
  { id: "verify", label: "Verify", state: "verified" },
  { id: "learn", label: "Learn", state: "pending" },
] as const

const COMPARISONS = [
  { label: "Runtime", predicted: "3.6s", actual: "3.8s" },
  { label: "Storage", predicted: "+18 MB", actual: "+17 MB" },
  { label: "Rollback", predicted: "Low", actual: "Safe" },
] as const

export default function DashboardPage() {
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

      <section
        aria-label="Migration Command Center"
        className="border-border flex min-h-72 w-full flex-col rounded-lg border p-4 md:min-h-96"
      >
        <div className="flex flex-1 flex-col justify-between gap-8">
          <div className="flex flex-col gap-3">
            <p className="text-muted-foreground text-[11px] font-medium tracking-[0.16em] uppercase">
              Migration Command Center
            </p>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-baseline sm:justify-between sm:gap-6">
              <div className="min-w-0 space-y-1">
                <p className="text-foreground truncate font-mono text-sm tracking-tight">
                  migration_2026_07_24.sql
                </p>
                <p className="text-muted-foreground font-mono text-xs tracking-tight">
                  PostgreSQL
                  <span className="text-muted-foreground/50 mx-2">→</span>
                  CockroachDB
                </p>
              </div>
              <div className="flex items-center gap-2 self-start sm:self-auto">
                <span
                  aria-hidden
                  className="size-1.5 shrink-0 rounded-full bg-[var(--oracle-verified)]"
                />
                <span className="font-mono text-[11px] tracking-[0.14em] text-[var(--oracle-verified)] uppercase">
                  Verified
                </span>
              </div>
            </div>
          </div>

          <div className="w-full overflow-x-auto">
            <ol className="relative flex min-w-[36rem] items-start justify-between gap-2 px-1">
              <li
                aria-hidden
                className="bg-border absolute top-[5px] right-3 left-3 h-px"
              />
              {STAGES.map((stage) => {
                const isVerified = stage.state === "verified"
                const isComplete = stage.state === "complete"
                const isPending = stage.state === "pending"

                return (
                  <li
                    key={stage.id}
                    className="relative z-10 flex flex-1 flex-col items-center gap-2"
                  >
                    <span
                      aria-hidden
                      className={cn(
                        "size-2.5 rounded-full border",
                        isVerified &&
                          "border-[var(--oracle-verified)] bg-[var(--oracle-verified)]",
                        isComplete &&
                          "border-muted-foreground/50 bg-muted-foreground/50",
                        isPending && "border-border bg-background"
                      )}
                    />
                    <span
                      className={cn(
                        "font-mono text-[10px] tracking-[0.12em] uppercase",
                        isVerified && "text-[var(--oracle-verified)]",
                        isComplete && "text-muted-foreground/70",
                        isPending && "text-muted-foreground/40"
                      )}
                    >
                      {stage.label}
                    </span>
                  </li>
                )
              })}
            </ol>
          </div>

          <div className="space-y-3 border-t border-border/60 pt-4">
            <p className="text-muted-foreground/70 font-mono text-[10px] tracking-[0.14em] uppercase">
              Prediction vs Reality
            </p>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between sm:gap-8">
              <dl className="grid flex-1 grid-cols-1 gap-x-8 gap-y-2 sm:grid-cols-3">
                {COMPARISONS.map((row) => (
                  <div key={row.label} className="min-w-0">
                    <dt className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
                      {row.label}
                    </dt>
                    <dd className="text-foreground/85 mt-0.5 font-mono text-xs tracking-tight">
                      {row.predicted}
                      <span className="text-muted-foreground/45 mx-1.5">→</span>
                      {row.actual}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="font-mono text-[11px] tracking-tight text-[var(--oracle-verified)] sm:text-right">
                Δ +0.2s
                <span className="text-muted-foreground/50 mx-1.5">·</span>
                <span className="text-muted-foreground">
                  WITHIN EXPECTED RANGE
                </span>
              </p>
            </div>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <section
          aria-label="Shadow Cluster"
          className="border-border flex min-h-44 w-full flex-col rounded-lg border p-4 md:min-h-52"
        >
          <div className="flex flex-1 flex-col gap-3">
            <div className="flex items-start justify-between gap-3">
              <p className="text-muted-foreground text-[11px] font-medium tracking-[0.16em] uppercase">
                Shadow Cluster
              </p>
              <div className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="size-1.5 shrink-0 rounded-full bg-[var(--oracle-verified)]"
                />
                <span className="font-mono text-[10px] tracking-[0.14em] text-[var(--oracle-verified)] uppercase">
                  Ready
                </span>
              </div>
            </div>

            <div className="flex flex-1 flex-col justify-between gap-4">
              <div className="flex items-start justify-between gap-4">
                <p className="text-foreground/80 font-mono text-xs tracking-tight">
                  SHADOW-7F2A
                </p>
                <div className="text-right font-mono text-[10px] leading-relaxed tracking-tight text-muted-foreground">
                  <p>CockroachDB</p>
                  <p className="text-muted-foreground/70">us-east-1</p>
                  <p className="text-muted-foreground/50">ephemeral</p>
                </div>
              </div>

              <div className="flex flex-1 items-center justify-center py-2">
                <svg
                  viewBox="0 0 120 100"
                  className="text-muted-foreground/55 h-20 w-28"
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
              </div>

              <div className="flex items-end justify-between gap-3">
                <div className="font-mono text-[10px] leading-relaxed tracking-tight text-muted-foreground">
                  <p>3 nodes</p>
                  <p className="text-muted-foreground/70">12 / 12 statements</p>
                </div>
                <p className="max-w-[11rem] text-right font-mono text-[10px] leading-relaxed tracking-tight text-muted-foreground/55">
                  Created 2m ago
                  <span className="mx-1.5">·</span>
                  Auto-destroy after verification
                </p>
              </div>
            </div>
          </div>
        </section>
        <section
          aria-label="Prediction Engine"
          className="border-border flex min-h-44 w-full flex-col rounded-lg border p-4 md:min-h-52"
        >
          <div className="flex flex-1 flex-col justify-between gap-4">
            <div className="flex items-start justify-between gap-3">
              <p className="text-muted-foreground text-[11px] font-medium tracking-[0.16em] uppercase">
                Prediction Engine
              </p>
              <p className="font-mono text-[10px] tracking-[0.12em] text-[var(--oracle-reasoning-soft)] uppercase">
                97% confidence
              </p>
            </div>

            <div className="flex flex-1 flex-col justify-center gap-1 py-1">
              <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
                Runtime
              </p>
              <p className="font-mono text-3xl leading-none tracking-tight text-[var(--oracle-reasoning-soft)]">
                3.6s
              </p>
              <p className="text-muted-foreground/70 mt-1 font-mono text-[11px] tracking-tight">
                predicted
                <span className="text-muted-foreground/40 mx-1.5">·</span>
                ±0.4s range
              </p>
            </div>

            <div className="space-y-2.5 border-t border-border/60 pt-3">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
                  Storage Impact
                </span>
                <span className="text-foreground/80 font-mono text-xs tracking-tight">
                  +18 MB
                </span>
              </div>
              <div className="border-border/40 border-t" />
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
                  Rollback Risk
                </span>
                <span className="text-foreground/80 font-mono text-xs tracking-[0.08em] uppercase">
                  Low
                </span>
              </div>
              <div className="border-border/40 border-t" />
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
                  Lock Risk
                </span>
                <span className="text-foreground/80 font-mono text-xs tracking-[0.08em] uppercase">
                  Low
                </span>
              </div>
            </div>

            <p className="text-muted-foreground/50 font-mono text-[10px] tracking-tight">
              Based on 23 similar learned outcomes
            </p>
          </div>
        </section>
      </div>

      <section
        aria-label="Agent Memory"
        className="border-border flex min-h-44 w-full flex-col rounded-lg border p-4 md:min-h-52"
      >
        <h2 className="text-muted-foreground text-sm font-medium tracking-wide uppercase">
          Agent Memory
        </h2>
      </section>
    </div>
  )
}
