import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { CheckCircle2, AlertTriangle, ChevronDown } from "lucide-react";
import { PageHeader, Panel, Label, SqlBlock } from "@/components/ui-kit";
import { memoryReasons } from "@/lib/migration-data";

export const Route = createFileRoute("/agent-memory")({
  head: () => ({
    meta: [
      { title: "Agent Memory — Migration Oracle" },
      {
        name: "description",
        content:
          "See the verified historical runs and learned patterns behind the AI's migration confidence score.",
      },
      { property: "og:title", content: "Agent Memory — Migration Oracle" },
      {
        property: "og:description",
        content: "Verified historical runs and learned patterns behind the AI confidence score.",
      },
    ],
  }),
  component: AgentMemory,
});

function ConfidenceRing() {
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative grid place-items-center">
      <svg width="132" height="132" viewBox="0 0 132 132" className="-rotate-90">
        <circle cx="66" cy="66" r={r} fill="none" strokeWidth="11" className="stroke-muted" />
        <motion.circle
          cx="66"
          cy="66"
          r={r}
          fill="none"
          strokeWidth="11"
          strokeLinecap="round"
          className="stroke-primary"
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - 0.94) }}
          transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
          strokeDasharray={c}
        />
      </svg>
      <div className="absolute text-center">
        <div className="text-[26px] font-bold leading-none text-foreground">94%</div>
        <div className="mt-1 text-[12px] text-muted-foreground">confidence</div>
      </div>
    </div>
  );
}

function AgentMemory() {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <PageHeader
        title="Agent Memory"
        subtitle="Why the AI is confident about this migration recommendation."
        action={
          <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[13px] font-medium text-emerald-700">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Corpus healthy
          </span>
        }
      />

      <div className="grid grid-cols-2 items-start gap-5 lg:grid-cols-5">
        <Panel className="col-span-2 flex flex-col items-center px-6 py-6 lg:col-span-1">
          <ConfidenceRing />
          <div className="mt-4 text-center">
            <div className="text-[14px] font-semibold text-foreground">AI Confidence</div>
            <div className="text-[12px] text-muted-foreground">High — safe to approve</div>
          </div>
        </Panel>
        {[
          { k: "Similar migrations", v: "36", s: "in corpus", c: "text-foreground" },
          { k: "Success rate", v: "97.2%", s: "across matches", c: "text-emerald-600" },
          { k: "Avg runtime", v: "1m 58s", s: "similar indexes", c: "text-foreground" },
          { k: "Failures", v: "1", s: "of 36 runs", c: "text-amber-600" },
        ].map((m, i) => (
          <Panel key={m.k} className="px-5 py-5" delay={0.04 * (i + 1)}>
            <Label>{m.k}</Label>
            <div className={"mt-3 text-[26px] font-bold leading-none tabular-nums " + m.c}>{m.v}</div>
            <div className="mt-2 text-[13px] text-muted-foreground">{m.s}</div>
          </Panel>
        ))}
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
        <Panel className="px-6 py-5" delay={0.1}>
          <Label className="mb-5">Why the AI is confident</Label>
          <div className="space-y-5">
            {memoryReasons.map((r) => (
              <div key={r.title} className="flex gap-3">
                {r.tone === "warn" ? (
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                ) : (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                )}
                <div>
                  <div className="text-[13.5px] font-semibold text-foreground">{r.title}</div>
                  <p className="mt-1 text-[13.5px] leading-relaxed text-muted-foreground">
                    {r.detail}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel className="px-6 py-5" delay={0.12}>
          <Label className="mb-4">Most similar migration</Label>
          <div className="flex items-center justify-between">
            <span className="text-[14px] font-bold text-emerald-600">97% match</span>
            <span className="rounded bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
              success
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: "97%" }}
              transition={{ duration: 0.7 }}
              className="h-full rounded-full bg-emerald-500"
            />
          </div>
          <div className="mt-4 rounded-lg bg-muted/60 px-3 py-2.5">
            <SqlBlock>CREATE INDEX idx_orders_user_id ON orders (user_id)</SqlBlock>
          </div>
          <div className="mt-3 flex items-center justify-between text-[12.5px] text-muted-foreground">
            <span>2026-06-14</span>
            <span className="font-mono">1m 52s</span>
          </div>

          <div className="mt-5 border-t border-border pt-4">
            <Label className="mb-3">Other close matches</Label>
            <div className="space-y-2.5">
              {[
                ["CREATE INDEX idx_sessions_token ON …", "91%"],
                ["CREATE INDEX idx_payments_status ON…", "88%"],
              ].map(([sql, pct]) => (
                <div key={sql} className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
                    <span className="truncate font-mono text-[12px] text-foreground">{sql}</span>
                  </div>
                  <span className="text-[12.5px] font-semibold tabular-nums text-foreground">
                    {pct}
                  </span>
                </div>
              ))}
            </div>
          </div>
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
              className={"h-4 w-4 text-muted-foreground transition-transform " + (expanded ? "rotate-180" : "")}
            />
            <span className="text-[15px] font-semibold text-foreground">View More</span>
            <span className="text-[13px] text-muted-foreground">
              — historical runs, learned patterns, technical details
            </span>
          </span>
          <span className="section-label">{expanded ? "Collapse" : "Expand"}</span>
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
              <div className="grid grid-cols-1 gap-6 border-t border-border px-6 py-5 sm:grid-cols-3">
                <div>
                  <Label className="mb-3">Historical runs</Label>
                  <div className="space-y-2 text-[13px] text-muted-foreground">
                    <div>36 verified runs · 35 succeeded</div>
                    <div>Corpus window: 2025-11 → 2026-07</div>
                    <div>Median runtime 1m 51s</div>
                  </div>
                </div>
                <div>
                  <Label className="mb-3">Learned patterns</Label>
                  <div className="space-y-2 text-[13px] text-muted-foreground">
                    <div>B-Tree indexes on NOT NULL columns rarely escalate locks</div>
                    <div>Write rate above 200/s correlates with failures</div>
                  </div>
                </div>
                <div>
                  <Label className="mb-3">Technical details</Label>
                  <div className="space-y-2 font-mono text-[12px] text-muted-foreground">
                    <div>work_mem = 256MB</div>
                    <div>lock_mode = SHARE</div>
                    <div>concurrently = true</div>
                  </div>
                </div>
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </Panel>
    </>
  );
}
