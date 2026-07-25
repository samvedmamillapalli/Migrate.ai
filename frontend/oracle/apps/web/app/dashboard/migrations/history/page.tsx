"use client"

import * as React from "react"
import Link from "next/link"

import { ApiError } from "@/lib/api/client"
import { type MigrationRunSummary, listRuns } from "@/lib/api/endpoints"
import { mapRunListItem } from "@/lib/api/map-run"
import { cn } from "@workspace/ui/lib/utils"

export default function PastMigrationsPage() {
  const [runs, setRuns] = React.useState<MigrationRunSummary[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const res = await listRuns({ limit: 50 })
        if (cancelled) return
        setRuns(res.items)
        setError(null)
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
  }, [])

  const items = runs ? runs.map(mapRunListItem) : []

  return (
    <div className="flex flex-1 flex-col gap-5 px-4 pb-6 md:px-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-foreground text-2xl font-medium tracking-tight">
          Past Migrations
        </h1>
        <p className="text-muted-foreground text-sm">
          Review previous migration runs and their shadow execution results.
        </p>
      </div>

      <section className="border-border flex w-full flex-col gap-1 rounded-lg border p-2">
        {error ? (
          <p className="text-[var(--oracle-risk)] p-2 font-mono text-xs tracking-tight">
            {error}
          </p>
        ) : loading ? (
          <p className="text-muted-foreground p-2 text-sm">Loading…</p>
        ) : items.length === 0 ? (
          <p className="text-muted-foreground p-2 text-sm">
            No migration runs yet.
          </p>
        ) : (
          <>
            <div className="text-muted-foreground/60 hidden grid-cols-[6rem_1fr_9rem_9rem_7rem_6rem] gap-3 px-2 py-1.5 font-mono text-[10px] tracking-[0.1em] uppercase sm:grid">
              <span>ID</span>
              <span>SQL</span>
              <span>Status</span>
              <span>Workflow</span>
              <span>Policy</span>
              <span>Created</span>
            </div>
            <ul className="divide-border/60 divide-y">
              {items.map((item) => {
                const emphasize = item.isFailed
                return (
                  <li key={item.id}>
                    <Link
                      href={`/dashboard/migrations/${item.id}`}
                      className={cn(
                        "grid grid-cols-1 gap-1 rounded-md px-2 py-2.5 transition-colors hover:bg-muted/40 sm:grid-cols-[6rem_1fr_9rem_9rem_7rem_6rem] sm:items-center sm:gap-3",
                        emphasize && "border-l-2 border-[var(--oracle-risk)]"
                      )}
                    >
                      <span className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
                        {item.id.slice(0, 8)}
                      </span>
                      <span
                        className={cn(
                          "truncate font-mono text-xs tracking-tight",
                          emphasize ? "text-[var(--oracle-risk)]" : "text-foreground/85"
                        )}
                      >
                        {item.sqlSnippet}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span
                          aria-hidden
                          className={cn(
                            "size-1.5 shrink-0 rounded-full",
                            emphasize
                              ? "bg-[var(--oracle-risk)]"
                              : item.status === "completed"
                                ? "bg-[var(--oracle-verified)]"
                                : "bg-muted-foreground/60"
                          )}
                        />
                        <span
                          className={cn(
                            "font-mono text-[11px] tracking-tight uppercase",
                            emphasize
                              ? "text-[var(--oracle-risk)] font-medium"
                              : "text-muted-foreground"
                          )}
                        >
                          {item.statusLabel}
                        </span>
                      </span>
                      <span className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
                        {item.workflowLabel}
                      </span>
                      <span className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
                        {item.policyDecision ?? "—"}
                      </span>
                      <span className="text-muted-foreground/55 font-mono text-[11px] tracking-tight">
                        {item.createdAgo}
                      </span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </>
        )}
      </section>
    </div>
  )
}
