"use client"

import * as React from "react"
import Link from "next/link"
import { AnimatePresence, motion } from "motion/react"
import { AlertTriangle, CheckCircle2, ChevronDown } from "lucide-react"

import {
  ApiError,
  formatDuration,
  formatPercent,
  getCurrentRunId,
  getMemoriesHealth,
  getRun,
  mapAssessment,
  type AssessmentView,
  type CorpusHealth,
  type MigrationRun,
} from "@/lib/api"
import { buttonVariants } from "@workspace/ui/components/button"
import {
  EmptyNote,
  ErrorNote,
  Label,
  PageHeader,
  Panel,
  SqlBlock,
  ToneDot,
  toneText,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

/**
 * Why the AI is confident about *this* migration.
 *
 * Distinct from the Agent Memory browser in Settings, which browses the
 * whole corpus. This page explains one run's confidence score using the
 * memories that were actually retrieved for it and the clamps that were
 * actually applied.
 *
 * Everything is read from explainability.{confidence,memory}. When a run has
 * not been predicted yet there is nothing to explain, and the page says so
 * rather than showing a ring at some default value.
 */

function ConfidenceRing({ value }: { value: number | null }) {
  const r = 52
  const c = 2 * Math.PI * r
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value))
  return (
    <div className="relative grid place-items-center">
      <svg width="132" height="132" viewBox="0 0 132 132" className="-rotate-90">
        <circle
          cx="66"
          cy="66"
          r={r}
          fill="none"
          strokeWidth="11"
          className="stroke-muted"
        />
        {value != null ? (
          <motion.circle
            cx="66"
            cy="66"
            r={r}
            fill="none"
            strokeWidth="11"
            strokeLinecap="round"
            className="stroke-primary"
            initial={{ strokeDashoffset: c }}
            animate={{ strokeDashoffset: c * (1 - pct) }}
            transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
            strokeDasharray={c}
          />
        ) : null}
      </svg>
      <div className="absolute text-center">
        <div className="text-foreground text-[26px] leading-none font-bold">
          {value == null ? "—" : formatPercent(value)}
        </div>
        <div className="text-muted-foreground mt-1 text-[12px]">confidence</div>
      </div>
    </div>
  )
}

/**
 * "Why the AI is confident" list.
 *
 * Built from real signals rather than prose written for the design: the
 * strength of the historical match, each confidence clamp with its stated
 * reason, and the model's own uncertainty notes.
 */
function reasonsFrom(assessment: AssessmentView): Array<{
  title: string
  detail: string
  tone: "ok" | "warn"
}> {
  const out: Array<{ title: string; detail: string; tone: "ok" | "warn" }> = []
  const { retrieval, confidence, prediction } = assessment
  const agg = retrieval.aggregates

  if (retrieval.emptyVsNeverAttempted === "hits") {
    const graded = agg?.gradedCount ?? 0
    const rate = agg?.successRate
    out.push({
      title:
        graded > 0
          ? `Historical match across ${retrieval.retrievedCount} similar migration${retrieval.retrievedCount === 1 ? "" : "s"}`
          : `Matched ${retrieval.retrievedCount} similar migration${retrieval.retrievedCount === 1 ? "" : "s"}`,
      detail:
        graded > 0
          ? `${graded} of them are graded shadow runs${
              rate != null
                ? `, ${Math.round(rate * 100)}% of which succeeded`
                : ""
            }.${
              (agg?.ungradedCount ?? 0) > 0
                ? ` ${agg!.ungradedCount} are documented incidents or seed rows and are excluded from that rate.`
                : ""
            }`
          : "None of them are graded shadow runs yet, so no success rate can be computed from this set.",
      tone: retrieval.weakRetrieval ? "warn" : "ok",
    })
  } else if (retrieval.emptyVsNeverAttempted === "empty") {
    out.push({
      title: "No similar past runs found",
      detail:
        "Retrieval ran but matched nothing in the corpus. Confidence rests on the policy engine and the model's own reasoning alone.",
      tone: "warn",
    })
  } else if (retrieval.emptyVsNeverAttempted === "never_attempted") {
    out.push({
      title: "Memory retrieval was not attempted",
      detail:
        "This prediction did not consult the memory corpus, so there is no historical grounding behind the score.",
      tone: "warn",
    })
  }

  if (retrieval.weakRetrieval) {
    out.push({
      title: "Weak similarity to retrieved runs",
      detail: `Every match scored below the ${
        retrieval.weakSimilarityThreshold != null
          ? formatPercent(retrieval.weakSimilarityThreshold)
          : "configured"
      } similarity threshold, so the historical evidence is only loosely related.`,
      tone: "warn",
    })
  }

  if (agg?.meanActualDurationSeconds != null) {
    out.push({
      title: "Runtime precedent",
      detail: `Similar migrations averaged ${formatDuration(
        agg.meanActualDurationSeconds
      )} measured across ${agg.durationSampleSize} run${agg.durationSampleSize === 1 ? "" : "s"}${
        prediction?.estimatedDurationSeconds != null
          ? `. This one is predicted at ${formatDuration(prediction.estimatedDurationSeconds)}.`
          : "."
      }`,
      tone: "ok",
    })
  }

  // The backend records each clamp as a positive magnitude subtracted from
  // the model's raw score (confidence.py), so a positive amount always means
  // confidence was reduced — never raised.
  for (const adj of confidence?.adjustments ?? []) {
    out.push({
      title: `Confidence reduced by ${Math.abs(adj.amount)}`,
      detail: adj.reason || adj.reasonCode,
      tone: "warn",
    })
  }

  for (const note of prediction?.uncertaintyNotes ?? []) {
    out.push({ title: "Model-flagged uncertainty", detail: note, tone: "warn" })
  }

  return out
}

export default function CurrentMigrationMemoryPage() {
  const [run, setRun] = React.useState<MigrationRun | null>(null)
  const [corpus, setCorpus] = React.useState<CorpusHealth | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [expanded, setExpanded] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    async function load() {
      const rid = getCurrentRunId()
      if (!rid) {
        setLoading(false)
        return
      }
      try {
        const [runRes, healthRes] = await Promise.allSettled([
          getRun(rid),
          getMemoriesHealth(),
        ])
        if (cancelled) return
        if (runRes.status === "fulfilled") setRun(runRes.value)
        else throw runRes.reason
        if (healthRes.status === "fulfilled") setCorpus(healthRes.value)
      } catch (err) {
        if (cancelled) return
        setError(
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Failed to load this run."
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

  const assessment = run ? mapAssessment(run) : null
  const retrieval = assessment?.retrieval
  const agg = retrieval?.aggregates
  const confidence = assessment?.confidence
  const reasons = assessment ? reasonsFrom(assessment) : []
  const top = retrieval?.memories?.[0]
  const others = retrieval?.memories?.slice(1, 4) ?? []
  const corpusHealthy = corpus ? corpus.healthy !== false : null

  return (
    <div className="mx-auto w-full max-w-[1500px] px-6 pb-10 lg:px-10">
      <nav className="text-muted-foreground mb-4 flex items-center gap-2 font-mono text-[11px]">
        <Link
          href="/dashboard/migrations/current"
          className="hover:text-foreground transition-colors"
        >
          Current Migration
        </Link>
        <span className="text-muted-foreground/40">/</span>
        <span className="text-foreground">Agent Memory</span>
      </nav>

      <PageHeader
        title="Agent Memory"
        subtitle="Why the AI reached this confidence on the current migration."
        action={
          corpusHealthy == null ? null : (
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[13px] font-medium",
                corpusHealthy
                  ? "border-[var(--tone-pass-border)] bg-[var(--tone-pass-bg)] text-[var(--tone-pass-fg)]"
                  : "border-[var(--tone-fail-border)] bg-[var(--tone-fail-bg)] text-[var(--tone-fail-fg)]"
              )}
            >
              <ToneDot tone={corpusHealthy ? "pass" : "fail"} />
              {corpusHealthy ? "Corpus healthy" : "Corpus problem"}
            </span>
          )
        }
      />

      {error ? (
        <Panel className="px-6 py-5">
          <ErrorNote>{error}</ErrorNote>
        </Panel>
      ) : loading ? (
        <Panel className="px-6 py-5">
          <EmptyNote>Loading…</EmptyNote>
        </Panel>
      ) : !run ? (
        <Panel className="flex flex-col gap-3 px-6 py-5">
          <EmptyNote>
            No current run selected. Pick one from the Overview or Past
            Migrations first.
          </EmptyNote>
          <Link
            href="/dashboard/migrations/current"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-fit")}
          >
            ← Current Migration
          </Link>
        </Panel>
      ) : !assessment?.prediction ? (
        <Panel className="flex flex-col gap-3 px-6 py-5">
          <EmptyNote>
            This run has not been predicted yet, so there is no confidence to
            explain. Run the prediction on the workspace first.
          </EmptyNote>
          <Link
            href="/dashboard/migrations/current"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-fit")}
          >
            ← Current Migration
          </Link>
        </Panel>
      ) : (
        <>
          <div className="grid grid-cols-2 items-start gap-5 lg:grid-cols-5">
            <Panel className="col-span-2 flex flex-col items-center px-6 py-6 lg:col-span-1">
              <ConfidenceRing value={confidence?.adjusted ?? null} />
              <div className="mt-4 text-center">
                <div className="text-foreground text-[14px] font-semibold">
                  AI Confidence
                </div>
                <div className="text-muted-foreground text-[12px]">
                  {confidence?.wasReduced
                    ? `clamped from ${confidence.rawPercentLabel}`
                    : "as produced by the model"}
                </div>
              </div>
            </Panel>

            <Panel className="px-5 py-5" delay={0.04}>
              <Label>Similar migrations</Label>
              <div className="text-foreground mt-3 text-[26px] leading-none font-bold tabular-nums">
                {retrieval?.retrievedCount ?? 0}
              </div>
              <div className="text-muted-foreground mt-2 text-[13px]">
                retrieved for this run
              </div>
            </Panel>

            <Panel className="px-5 py-5" delay={0.08}>
              <Label>Success rate</Label>
              <div
                className={cn(
                  "mt-3 text-[26px] leading-none font-bold tabular-nums",
                  agg?.successRate == null
                    ? "text-muted-foreground"
                    : toneText("pass")
                )}
              >
                {agg?.successRate == null
                  ? "—"
                  : `${Math.round(agg.successRate * 100)}%`}
              </div>
              <div className="text-muted-foreground mt-2 text-[13px]">
                {agg?.gradedCount
                  ? `across ${agg.gradedCount} graded run${agg.gradedCount === 1 ? "" : "s"}`
                  : "no graded matches"}
              </div>
            </Panel>

            <Panel className="px-5 py-5" delay={0.12}>
              <Label>Avg runtime</Label>
              <div className="text-foreground mt-3 text-[26px] leading-none font-bold tabular-nums">
                {agg?.meanActualDurationSeconds == null
                  ? "—"
                  : formatDuration(agg.meanActualDurationSeconds)}
              </div>
              <div className="text-muted-foreground mt-2 text-[13px]">
                {agg?.durationSampleSize
                  ? `measured across ${agg.durationSampleSize}`
                  : "no measured runs"}
              </div>
            </Panel>

            <Panel className="px-5 py-5" delay={0.16}>
              <Label>Failures</Label>
              <div
                className={cn(
                  "mt-3 text-[26px] leading-none font-bold tabular-nums",
                  agg?.failedCount ? toneText("warn") : "text-foreground"
                )}
              >
                {agg?.failedCount ?? 0}
              </div>
              <div className="text-muted-foreground mt-2 text-[13px]">
                {agg?.gradedCount ? `of ${agg.gradedCount} graded` : "none graded"}
              </div>
            </Panel>
          </div>

          <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
            <Panel className="px-6 py-5" delay={0.1}>
              <Label className="mb-5">Why the AI reached this confidence</Label>
              {reasons.length === 0 ? (
                <EmptyNote>
                  No confidence adjustments or retrieval signals were recorded
                  for this run.
                </EmptyNote>
              ) : (
                <div className="space-y-5">
                  {reasons.map((r, i) => (
                    <div key={`${r.title}-${i}`} className="flex gap-3">
                      {r.tone === "warn" ? (
                        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-[var(--tone-warn-fg)]" />
                      ) : (
                        <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-[var(--tone-pass-fg)]" />
                      )}
                      <div>
                        <div className="text-foreground text-[13.5px] font-semibold">
                          {r.title}
                        </div>
                        <p className="text-muted-foreground mt-1 text-[13.5px] leading-relaxed">
                          {r.detail}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>

            <Panel className="px-6 py-5" delay={0.12}>
              <Label className="mb-4">Most similar migration</Label>
              {!top ? (
                <EmptyNote>No memories were retrieved for this run.</EmptyNote>
              ) : (
                <>
                  <div className="flex items-center justify-between">
                    <span
                      className={cn(
                        "text-[14px] font-bold",
                        toneText(top.notAGradedRun ? "warn" : "pass")
                      )}
                    >
                      {top.similarityScore == null
                        ? "similarity unavailable"
                        : `${formatPercent(top.similarityScore)} match`}
                    </span>
                    <span
                      className={cn(
                        "rounded px-2 py-0.5 text-[11px] font-semibold",
                        top.notAGradedRun
                          ? "bg-[var(--tone-warn-bg)] text-[var(--tone-warn-fg)]"
                          : "bg-[var(--tone-pass-bg)] text-[var(--tone-pass-fg)]"
                      )}
                    >
                      {top.notAGradedRun ? "not graded" : "graded run"}
                    </span>
                  </div>
                  <div className="bg-muted mt-2 h-1.5 overflow-hidden rounded-full">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{
                        width: `${Math.round((top.similarityScore ?? 0) * 100)}%`,
                      }}
                      transition={{ duration: 0.7 }}
                      className={cn(
                        "h-full rounded-full",
                        top.notAGradedRun
                          ? "bg-[var(--tone-warn-dot)]"
                          : "bg-[var(--tone-pass-dot)]"
                      )}
                    />
                  </div>
                  <div className="bg-muted/60 mt-4 rounded-lg px-3 py-2.5">
                    <SqlBlock className="text-[12px]">
                      {top.migrationSummary || "(no summary recorded)"}
                    </SqlBlock>
                  </div>
                  <div className="text-muted-foreground mt-3 flex items-center justify-between text-[12.5px]">
                    <span>{top.scaleTier ?? "tier unknown"}</span>
                    <span className="font-mono">
                      {top.actualDurationSeconds == null
                        ? "—"
                        : formatDuration(top.actualDurationSeconds)}
                    </span>
                  </div>
                  {top.migrationRunId ? (
                    <Link
                      href={`/dashboard/migrations/${top.migrationRunId}`}
                      className="text-primary mt-3 inline-block text-[12.5px] font-semibold hover:underline"
                    >
                      Open that run →
                    </Link>
                  ) : null}
                </>
              )}

              {others.length > 0 ? (
                <div className="border-border mt-5 border-t pt-4">
                  <Label className="mb-3">Other close matches</Label>
                  <div className="space-y-2.5">
                    {others.map((m) => (
                      <div
                        key={m.rank}
                        className="flex items-center justify-between gap-3"
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          <ToneDot tone={m.notAGradedRun ? "warn" : "pass"} />
                          <span className="text-foreground truncate font-mono text-[12px]">
                            {m.migrationSummary || "(no summary)"}
                          </span>
                        </div>
                        <span className="text-foreground shrink-0 text-[12.5px] font-semibold tabular-nums">
                          {m.similarityScore == null
                            ? "—"
                            : formatPercent(m.similarityScore)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </Panel>
          </div>

          <Panel className="mt-5" delay={0.14}>
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="flex w-full items-center justify-between gap-3 px-6 py-4 text-left"
            >
              <span className="flex items-center gap-3">
                <ChevronDown
                  className={cn(
                    "text-muted-foreground size-4 transition-transform",
                    expanded && "rotate-180"
                  )}
                />
                <span className="text-foreground text-[15px] font-semibold">
                  View More
                </span>
                <span className="text-muted-foreground hidden text-[13px] sm:inline">
                  — retrieval attribution, corpus state, technical details
                </span>
              </span>
              <span className="section-label">
                {expanded ? "Collapse" : "Expand"}
              </span>
            </button>
            <AnimatePresence initial={false}>
              {expanded ? (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
                  className="overflow-hidden"
                >
                  <div className="border-border grid grid-cols-1 gap-6 border-t px-6 py-5 sm:grid-cols-3">
                    <div>
                      <Label className="mb-3">Retrieved set</Label>
                      <div className="text-muted-foreground space-y-2 text-[13px]">
                        <div>
                          {agg?.retrievedCount ?? 0} retrieved ·{" "}
                          {agg?.gradedCount ?? 0} graded
                        </div>
                        <div>
                          {agg?.succeededCount ?? 0} succeeded ·{" "}
                          {agg?.failedCount ?? 0} failed
                        </div>
                        <div>
                          {agg?.ungradedCount ?? 0} excluded (incidents / seeds)
                        </div>
                        <div>
                          top similarity{" "}
                          {agg?.topSimilarity == null
                            ? "—"
                            : formatPercent(agg.topSimilarity)}
                        </div>
                      </div>
                    </div>
                    <div>
                      <Label className="mb-3">Retrieval attribution</Label>
                      <div className="text-muted-foreground space-y-2 text-[13px]">
                        <div>mode: {retrieval?.mode ?? "—"}</div>
                        {retrieval?.attributionSignals.map((s) => (
                          <div key={s.key}>
                            {s.key.replace(/_/g, " ")}: {s.value}
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <Label className="mb-3">Corpus &amp; index</Label>
                      <div className="text-muted-foreground space-y-2 font-mono text-[12px]">
                        <div>total memories = {corpus?.total_memories ?? "—"}</div>
                        <div>
                          corpus ready = {corpus?.corpus_ready_count ?? "—"}
                        </div>
                        <div>
                          missing embeddings ={" "}
                          {corpus?.missing_embeddings ?? "—"}
                        </div>
                      </div>
                      <p className="text-muted-foreground mt-3 text-[12px] leading-relaxed">
                        {retrieval?.vectorIndexNote}
                      </p>
                    </div>
                  </div>
                </motion.div>
              ) : null}
            </AnimatePresence>
          </Panel>

          <div className="mt-5">
            <Link
              href="/dashboard/migrations/current"
              className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "-ml-2")}
            >
              ← Current Migration
            </Link>
          </div>
        </>
      )}
    </div>
  )
}
