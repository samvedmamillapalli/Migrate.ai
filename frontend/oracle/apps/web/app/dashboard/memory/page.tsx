"use client"

import * as React from "react"
import Link from "next/link"

import { ApiError } from "@/lib/api/client"
import {
  type CorpusHealth,
  type MemoryListItem,
  listMemories,
} from "@/lib/api/endpoints"
import { getOwnerIdentity } from "@/lib/api/owner"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@workspace/ui/components/collapsible"
import { cn } from "@workspace/ui/lib/utils"

function Section({
  title,
  children,
  className,
}: {
  title: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      aria-label={title}
      className={cn(
        "border-border flex w-full flex-col gap-3 rounded-lg border p-4",
        className
      )}
    >
      <p className="text-muted-foreground text-[11px] font-medium tracking-[0.16em] uppercase">
        {title}
      </p>
      {children}
    </section>
  )
}

function EmbedTextBlock({ text }: { text: string }) {
  const [open, setOpen] = React.useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger
        render={
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground font-mono text-[10px] tracking-[0.1em] uppercase transition-colors"
          />
        }
      >
        {open ? "Hide" : "Show"} embed text ({text.length} chars)
      </CollapsibleTrigger>
      <CollapsibleContent>
        <pre className="border-border/60 bg-muted/20 mt-2 max-h-96 overflow-auto rounded-md border p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
          {text}
        </pre>
      </CollapsibleContent>
    </Collapsible>
  )
}

function MemoryCard({ item }: { item: MemoryListItem }) {
  const isCorpus =
    Boolean(item.not_a_graded_run) ||
    item.owner_identity === "__migration_oracle_corpus__"
  return (
    <div
      className={cn(
        "border-border/60 space-y-3 rounded-md border p-3",
        isCorpus && "border-dashed bg-muted/10"
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-foreground/85 font-mono text-xs tracking-tight">
            {item.owner_identity}
          </span>
          <span className="text-muted-foreground/40">·</span>
          <span className="text-muted-foreground font-mono text-[11px] tracking-tight">
            {item.scale_tier || "unknown tier"}
          </span>
          <span className="text-muted-foreground/40">·</span>
          <span className="text-muted-foreground font-mono text-[11px] tracking-tight">
            {item.migration_type || "unknown type"}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {isCorpus ? (
            <span className="border-border text-muted-foreground inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] uppercase">
              {item.ui_label || "Open-source corpus (not a graded run)"}
            </span>
          ) : null}
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] uppercase",
              item.has_embedding
                ? "border-emerald-500/40 text-[var(--oracle-verified)]"
                : "border-amber-500/40 text-amber-300/90"
            )}
          >
            {item.has_embedding ? "ready" : "indexing"}
          </span>
        </div>
      </div>

      {!item.has_embedding ? (
        <p className="text-muted-foreground text-xs">
          Indexing for search…
        </p>
      ) : null}

      {item.ui_label ? (
        <p className="text-muted-foreground/70 font-mono text-[11px] tracking-tight">
          {item.ui_label}
        </p>
      ) : null}

      <p className="text-foreground/80 text-sm leading-relaxed">
        {item.migration_summary}
      </p>

      {item.embedding_error ? (
        <p className="text-[var(--oracle-risk)] text-xs leading-relaxed">
          {item.embedding_error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3 border-t border-border/50 pt-2">
        <Link
          href={`/dashboard/migrations/${item.migration_run_id}`}
          className="text-muted-foreground hover:text-foreground font-mono text-[10px] tracking-[0.1em] uppercase transition-colors"
        >
          Source run →
        </Link>
        {item.source_url ? (
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            className="text-muted-foreground hover:text-foreground font-mono text-[10px] tracking-[0.1em] uppercase transition-colors"
          >
            Source URL →
          </a>
        ) : null}
        {item.scalar_accuracy_score != null ? (
          <span className="text-muted-foreground/60 font-mono text-[10px] tracking-tight">
            scalar accuracy {item.scalar_accuracy_score.toFixed(3)}
          </span>
        ) : null}
      </div>

      <EmbedTextBlock text={item.embed_text} />
    </div>
  )
}

export default function AgentMemoryPage() {
  const [items, setItems] = React.useState<MemoryListItem[] | null>(null)
  const [total, setTotal] = React.useState(0)
  const [health, setHealth] = React.useState<CorpusHealth | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const owner = getOwnerIdentity()
        const res = await listMemories({
          limit: 50,
          ...(owner ? { owner_identity: owner } : {}),
        })
        if (cancelled) return
        setItems(res.items)
        setTotal(res.total)
        setHealth((res.health as CorpusHealth) ?? null)
        setError(null)
      } catch (err) {
        if (cancelled) return
        setError(
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Failed to load memories."
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

  const problems = health?.problems ?? []
  const loudWarning = Boolean(health && (!health.healthy || problems.length > 0))

  return (
    <div className="flex flex-1 flex-col gap-5 px-4 pb-6 md:px-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-foreground text-2xl font-medium tracking-tight">
          Agent Memory
        </h1>
        <p className="text-muted-foreground text-sm">
          Learned outcomes from previous migrations.
        </p>
      </div>

      {loudWarning ? (
        <section
          aria-label="Corpus health warning"
          className="border-[var(--oracle-risk)]/50 bg-[var(--oracle-risk)]/5 flex w-full flex-col gap-2 rounded-lg border p-4"
        >
          <p className="text-[var(--oracle-risk)] font-mono text-[11px] font-medium tracking-[0.16em] uppercase">
            Corpus health problem
          </p>
          <ul className="space-y-1">
            {problems.map((problem) => (
              <li
                key={problem}
                className="text-[var(--oracle-risk)] text-sm leading-relaxed"
              >
                {problem}
              </li>
            ))}
          </ul>
          {health ? (
            <p className="text-muted-foreground font-mono text-[11px] tracking-tight">
              {health.total_memories ?? 0} total
              <span className="mx-1.5">·</span>
              {health.corpus_ready_count ?? 0} corpus-ready
              <span className="mx-1.5">·</span>
              {health.missing_embeddings ?? 0} missing embeddings
            </p>
          ) : null}
        </section>
      ) : health ? (
        <section
          aria-label="Corpus health"
          className="border-border flex w-full items-center gap-3 rounded-lg border p-4"
        >
          <span
            aria-hidden
            className="size-1.5 shrink-0 rounded-full bg-[var(--oracle-verified)]"
          />
          <p className="text-muted-foreground font-mono text-[11px] tracking-tight">
            Corpus healthy
            <span className="mx-1.5">·</span>
            {health.total_memories ?? 0} total
            <span className="mx-1.5">·</span>
            {health.corpus_ready_count ?? 0} corpus-ready
          </p>
        </section>
      ) : null}

      <Section title={`Memories (${total})`}>
        {error ? (
          <p className="text-[var(--oracle-risk)] font-mono text-xs tracking-tight">
            {error}
          </p>
        ) : loading ? (
          <p className="text-muted-foreground text-sm">Loading…</p>
        ) : !items || items.length === 0 ? (
          <div className="space-y-3">
            <p className="text-muted-foreground text-sm">
              No memories yet. Complete a shadow test to start learning.
            </p>
            <Link
              href="/dashboard/migrations/current"
              className="text-foreground hover:underline font-mono text-[11px] tracking-tight"
            >
              Start a migration →
            </Link>
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((item) => (
              <MemoryCard key={item.id} item={item} />
            ))}
          </div>
        )}
      </Section>
    </div>
  )
}
