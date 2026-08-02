"use client"

import * as React from "react"
import Link from "next/link"
import { Search } from "lucide-react"

import { ApiError } from "@/lib/api/client"
import {
  CORPUS_OWNER_IDENTITY,
  type CorpusHealth,
  type MemoryListItem,
  type MemorySearchHit,
  type MemorySearchResponse,
  listMemories,
  searchMemories,
} from "@/lib/api/endpoints"
import { getOwnerIdentity } from "@/lib/api/owner"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@workspace/ui/components/collapsible"
import {
  EmptyNote,
  ErrorNote,
  Label,
  PageHeader,
  Panel,
  SkeletonLines,
  ToneDot,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

/** Debounce the search box so each keystroke isn't a request. */
function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = React.useState(value)
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(t)
  }, [value, delayMs])
  return debounced
}

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
    <Panel
      aria-label={title}
      className={cn("flex w-full flex-col gap-3 px-6 py-5", className)}
    >
      <Label>{title}</Label>
      {children}
    </Panel>
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
    item.owner_identity === CORPUS_OWNER_IDENTITY
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
                : "border-[var(--oracle-warning)]/40 text-[var(--oracle-warning)]"
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

/** Cosine similarity as a filled bar — same track/fill convention as the
 * schema-discovery progress bar elsewhere in this app. */
function SimilarityBar({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-[var(--oracle-reasoning-soft)] transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-muted-foreground font-mono text-[11px] tabular-nums">
        {pct}%
      </span>
    </div>
  )
}

/**
 * Predicted-vs-actual delta — the thing that makes this a graded memory layer
 * rather than a document store. Prefers duration (the primary predicted
 * metric); falls back to storage when duration isn't comparable.
 */
function PredictedVsActual({ hit }: { hit: MemorySearchHit }) {
  const durBoth =
    hit.predicted_duration_seconds != null &&
    hit.actual_duration_seconds != null
  const stoBoth =
    hit.predicted_storage_mb != null && hit.actual_storage_mb != null

  if (!durBoth && !stoBoth) {
    return (
      <span className="text-muted-foreground/60 font-mono text-[11px] tracking-tight">
        predicted/actual not recorded
      </span>
    )
  }

  if (durBoth) {
    const predicted = hit.predicted_duration_seconds as number
    const actual = hit.actual_duration_seconds as number
    const delta = actual - predicted
    const exact = Math.abs(delta) < 0.5
    const tone = exact
      ? "text-[var(--oracle-verified)]"
      : "text-[var(--oracle-warning)]"
    return (
      <span className={cn("font-mono text-[12px] font-semibold", tone)}>
        {predicted.toFixed(0)}s predicted → {actual.toFixed(0)}s actual
        {!exact ? (
          <span className="text-muted-foreground ml-1.5 font-normal">
            ({delta > 0 ? "+" : ""}
            {delta.toFixed(0)}s)
          </span>
        ) : null}
      </span>
    )
  }

  const predicted = hit.predicted_storage_mb as number
  const actual = hit.actual_storage_mb as number
  const delta = actual - predicted
  const exact = Math.abs(delta) < 0.5
  const tone = exact
    ? "text-[var(--oracle-verified)]"
    : "text-[var(--oracle-warning)]"
  return (
    <span className={cn("font-mono text-[12px] font-semibold", tone)}>
      {predicted.toFixed(0)}MB predicted → {actual.toFixed(0)}MB actual
      {!exact ? (
        <span className="text-muted-foreground ml-1.5 font-normal">
          ({delta > 0 ? "+" : ""}
          {delta.toFixed(0)}MB)
        </span>
      ) : null}
    </span>
  )
}

function SearchResultCard({ hit }: { hit: MemorySearchHit }) {
  const isCorpus =
    Boolean(hit.not_a_graded_run) || hit.owner_identity === CORPUS_OWNER_IDENTITY
  return (
    <div
      className={cn(
        "border-border/60 space-y-3 rounded-md border p-3",
        isCorpus && "border-dashed bg-muted/10"
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SimilarityBar value={hit.similarity_score} />
        <div className="flex flex-wrap items-center gap-1.5">
          {isCorpus ? (
            <span className="border-border text-muted-foreground inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[10px] tracking-[0.08em] uppercase">
              {hit.ui_label || "Open-source corpus (not a graded run)"}
            </span>
          ) : null}
          <span className="text-muted-foreground font-mono text-[11px] tracking-tight">
            {hit.migration_type}
          </span>
          <span className="text-muted-foreground/40">·</span>
          <span className="text-muted-foreground font-mono text-[11px] tracking-tight">
            {hit.scale_tier}
          </span>
        </div>
      </div>

      <PredictedVsActual hit={hit} />

      <p className="text-foreground/80 text-sm leading-relaxed">
        {hit.migration_summary}
      </p>

      {hit.lessons_learned ? (
        <p className="text-muted-foreground/80 text-xs leading-relaxed">
          {hit.lessons_learned}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3 border-t border-border/50 pt-2">
        <Link
          href={`/dashboard/migrations/${hit.migration_run_id}`}
          className="text-muted-foreground hover:text-foreground font-mono text-[10px] tracking-[0.1em] uppercase transition-colors"
        >
          Source run →
        </Link>
        {hit.source_url ? (
          <a
            href={hit.source_url}
            target="_blank"
            rel="noreferrer"
            className="text-muted-foreground hover:text-foreground font-mono text-[10px] tracking-[0.1em] uppercase transition-colors"
          >
            Source URL →
          </a>
        ) : null}
        {hit.outcome_class ? (
          <span className="text-muted-foreground/60 font-mono text-[10px] tracking-tight">
            {hit.outcome_class}
          </span>
        ) : null}
      </div>
    </div>
  )
}

type SearchScope = "mine" | "corpus" | "all"

const SEARCH_SCOPES: Array<{ value: SearchScope; label: string }> = [
  { value: "mine", label: "My memories" },
  { value: "corpus", label: "Shared corpus" },
  { value: "all", label: "All" },
]

function SemanticSearchSection() {
  const [query, setQuery] = React.useState("")
  const [scope, setScope] = React.useState<SearchScope>("all")
  const [result, setResult] = React.useState<MemorySearchResponse | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const debouncedQuery = useDebounced(query, 300)
  const trimmed = debouncedQuery.trim()

  React.useEffect(() => {
    if (!trimmed) {
      // Empty query: clear search state entirely. The unfiltered memory list
      // below is a separate, always-present section — it never depended on
      // this state, so there is nothing to "restore" beyond dropping ours.
      setResult(null)
      setError(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    async function run() {
      try {
        const owner = getOwnerIdentity()
        const res = await searchMemories(
          {
            query: trimmed,
            scope,
            min_similarity: 0,
            limit: 10,
          },
          owner ? { owner_identity: owner } : undefined
        )
        if (cancelled) return
        setResult(res)
      } catch (err) {
        if (cancelled) return
        setResult(null)
        setError(
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Search failed."
        )
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [trimmed, scope])

  return (
    <Section title="Search memory" className="mb-5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[260px] flex-1 sm:max-w-[420px]">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. adding a column to a large table…"
            aria-label="Semantic search over graded memories"
            className="border-border bg-card placeholder:text-muted-foreground focus:border-primary h-10 w-full rounded-lg border pr-3 pl-9 text-sm outline-none transition-colors"
          />
        </div>
        <div
          role="group"
          aria-label="Search scope"
          className="border-border bg-muted/30 inline-flex w-fit gap-0.5 rounded-lg border p-0.5"
        >
          {SEARCH_SCOPES.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setScope(value)}
              aria-pressed={scope === value}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                scope === value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {!trimmed ? (
        <p className="text-muted-foreground/70 text-[12px] leading-relaxed">
          Search runs a real query against CockroachDB&apos;s distributed
          vector index — type a scenario to find graded runs and documented
          incidents like it.
        </p>
      ) : error ? (
        <ErrorNote>{error}</ErrorNote>
      ) : loading ? (
        <SkeletonLines lines={4} />
      ) : result && result.results.length === 0 ? (
        <EmptyNote>No memories match &quot;{trimmed}&quot; in this scope.</EmptyNote>
      ) : result ? (
        <>
          <div className="space-y-3">
            {result.results.map((hit) => (
              <SearchResultCard key={hit.memory_id} hit={hit} />
            ))}
          </div>
          <p className="text-muted-foreground/60 font-mono text-[10px] tracking-tight">
            CockroachDB distributed vector index · {result.index_used ?? "n/a"}{" "}
            · {result.took_ms.toFixed(0)} ms
          </p>
        </>
      ) : null}
    </Section>
  )
}

const PER_PAGE = 20

export default function AgentMemoryPage() {
  const [items, setItems] = React.useState<MemoryListItem[] | null>(null)
  const [total, setTotal] = React.useState(0)
  const [health, setHealth] = React.useState<CorpusHealth | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [page, setPage] = React.useState(1)
  const [embedding, setEmbedding] = React.useState("all")
  const [reloadKey, setReloadKey] = React.useState(0)

  React.useEffect(() => {
    setPage(1)
  }, [embedding])

  React.useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const owner = getOwnerIdentity()
        const res = await listMemories({
          limit: PER_PAGE,
          offset: (page - 1) * PER_PAGE,
          ...(embedding !== "all" ? { embedding_status: embedding } : {}),
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
  }, [page, embedding, reloadKey])

  const pages = Math.max(1, Math.ceil(total / PER_PAGE))
  const current = Math.min(page, pages)
  const ownMemories = (items ?? []).filter(
    (i) => i.owner_identity !== CORPUS_OWNER_IDENTITY
  ).length

  const problems = health?.problems ?? []
  const loudWarning = Boolean(health && (!health.healthy || problems.length > 0))

  return (
    <div className="mx-auto w-full max-w-[1500px] px-6 pb-10 lg:px-10">
      <PageHeader
        title="Agent Memory"
        subtitle="Every learned outcome in the corpus, and the health of the index behind it."
        action={
          <Link
            href="/dashboard/migrations/current/memory"
            className="border-border bg-secondary text-foreground hover:bg-muted inline-flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm font-semibold transition-colors"
          >
            Why the current run is confident →
          </Link>
        }
      />

      {loudWarning ? (
        <Panel
          aria-label="Corpus health warning"
          className="mb-5 flex w-full flex-col gap-2 border-[var(--tone-fail-border)] bg-[var(--tone-fail-bg)] px-6 py-5"
        >
          <p className="section-label !text-[var(--tone-fail-fg)]">
            Corpus health problem
          </p>
          <ul className="space-y-1">
            {problems.map((problem) => (
              <li
                key={problem}
                className="text-[13px] leading-relaxed text-[var(--tone-fail-fg)]"
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
        </Panel>
      ) : health ? (
        <Panel
          aria-label="Corpus health"
          className="mb-5 flex w-full items-center gap-3 px-6 py-4"
        >
          <ToneDot tone="pass" />
          <p className="text-muted-foreground font-mono text-[11px] tracking-tight">
            Corpus healthy
            <span className="mx-1.5">·</span>
            {health.total_memories ?? 0} total
            <span className="mx-1.5">·</span>
            {health.corpus_ready_count ?? 0} corpus-ready
          </p>
        </Panel>
      ) : null}

      <SemanticSearchSection />

      <Section title={`Memories (${total})`}>
        {/* The backend scopes this to `IN (you, shared corpus)`, so the count
            above is not "your runs" — spell that out rather than leaving it to
            be inferred from the owner label on each card. */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-muted-foreground text-[12px] leading-relaxed">
            Your own graded runs plus the shared open-source corpus that informs
            your predictions
            {items
              ? ` — ${ownMemories} of the ${items.length} shown on this page ${
                  ownMemories === 1 ? "is" : "are"
                } yours`
              : ""}
            .
            {health?.total_memories != null ? (
              <>
                {" "}
                The health strip above counts all {health.total_memories}{" "}
                memories in the database, including other owners&apos;.
              </>
            ) : null}
          </p>
          <select
            value={embedding}
            onChange={(e) => setEmbedding(e.target.value)}
            aria-label="Filter by embedding status"
            className="border-border bg-card text-foreground focus:border-primary h-9 rounded-lg border px-3 text-sm outline-none transition-colors"
          >
            <option value="all">All embedding states</option>
            <option value="ready">Ready</option>
            <option value="pending">Indexing</option>
            <option value="failed">Failed</option>
          </select>
        </div>

        {error ? (
          <div className="space-y-3">
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
          <SkeletonLines lines={6} />
        ) : !items || items.length === 0 ? (
          <div className="space-y-3">
            <EmptyNote>
              {embedding === "all"
                ? "No memories yet. Complete a shadow test to start learning."
                : `No memories with embedding status "${embedding}".`}
            </EmptyNote>
            {embedding === "all" ? (
              <Link
                href="/dashboard/migrations/new"
                className="text-primary font-mono text-[11px] tracking-tight hover:underline"
              >
                Start a migration →
              </Link>
            ) : null}
          </div>
        ) : (
          <>
            <div className="space-y-3">
              {items.map((item) => (
                <MemoryCard key={item.id} item={item} />
              ))}
            </div>
            {pages > 1 ? (
              <div className="border-border flex flex-wrap items-center justify-between gap-3 border-t pt-4">
                <span className="text-muted-foreground text-[13px] tabular-nums">
                  {(current - 1) * PER_PAGE + 1}–
                  {Math.min(current * PER_PAGE, total)} of {total}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={current === 1}
                    className="border-border text-foreground hover:bg-muted rounded-lg border px-3 py-1.5 text-[13px] font-semibold transition-colors disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <span className="text-muted-foreground text-[13px] tabular-nums">
                    {current} / {pages}
                  </span>
                  <button
                    type="button"
                    onClick={() => setPage((p) => Math.min(pages, p + 1))}
                    disabled={current === pages}
                    className="border-border text-foreground hover:bg-muted rounded-lg border px-3 py-1.5 text-[13px] font-semibold transition-colors disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </Section>
    </div>
  )
}
