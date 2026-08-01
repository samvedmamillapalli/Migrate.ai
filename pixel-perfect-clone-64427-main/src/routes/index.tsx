import { createFileRoute, Link } from "@tanstack/react-router";
import { motion } from "motion/react";
import { Plus, ArrowRight } from "lucide-react";
import { PageHeader, Panel, Label, StatusPill, SqlBlock } from "@/components/ui-kit";
import { queueItems, activity, recentMigrations } from "@/lib/migration-data";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Overview — Migration Oracle" },
      {
        name: "description",
        content:
          "Your migration environment: system health, decision queue, recent activity and AI insight at a glance.",
      },
      { property: "og:title", content: "Overview — Migration Oracle" },
      {
        property: "og:description",
        content: "System health, decision queue and AI insight for your database migrations.",
      },
    ],
  }),
  component: Overview,
});

const riskColor: Record<string, string> = {
  low: "text-emerald-600",
  medium: "text-amber-600",
  high: "text-red-600",
};

function Health({ name }: { name: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
      <span className="text-sm font-semibold text-foreground">{name}</span>
      <span className="text-sm text-emerald-600">Ready</span>
    </div>
  );
}

const toneDot: Record<string, string> = {
  emerald: "bg-emerald-500",
  blue: "bg-blue-500",
  violet: "bg-violet-500",
  amber: "bg-amber-500",
};

function Overview() {
  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Your migration environment."
        action={
          <Link
            to="/new-migration"
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition-all duration-150 hover:bg-primary/90 active:scale-[0.98]"
          >
            <Plus className="h-4 w-4" />
            New Migration
          </Link>
        }
      />

      <Panel className="mb-5 px-6 py-5">
        <Label className="mb-3">System Health</Label>
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
          <Health name="API" />
          <Health name="Shadow" />
          <Health name="Predictions" />
          <Health name="Memory" />
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Panel className="px-6 py-5" delay={0.04}>
            <div className="mb-4 flex items-center justify-between">
              <Label>Current Migration</Label>
              <StatusPill status="AWAITING APPROVAL" />
            </div>
            <SqlBlock className="text-[14px] font-semibold">
              CREATE INDEX idx_users_email ON users (email);
            </SqlBlock>
            <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">
              <span>
                Stage: <span className="font-semibold text-foreground">awaiting approval</span>
              </span>
              <span className="text-border">·</span>
              <span>
                Risk: <span className="font-semibold text-emerald-600">low</span>
              </span>
              <span className="text-border">·</span>
              <span>
                Confidence: <span className="font-semibold text-foreground">94%</span>
              </span>
              <span className="text-border">·</span>
              <span>
                Estimated duration: <span className="font-semibold text-foreground">2m 10s</span>
              </span>
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50/60 px-4 py-3">
              <div className="flex items-center gap-3 text-[13px]">
                <span className="text-[11px] font-bold uppercase tracking-[0.08em] text-amber-700">
                  Next Action
                </span>
                <span className="text-border">·</span>
                <span className="text-foreground">
                  Review the shadow evidence, then approve this low-risk index.
                </span>
              </div>
              <Link
                to="/current-migration"
                className="inline-flex items-center gap-1 text-[13px] font-semibold text-primary hover:underline"
              >
                Review <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.08}>
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Label>Decision Queue</Label>
                <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-bold text-amber-600">
                  {queueItems.length}
                </span>
              </div>
              <Link
                to="/past-migrations"
                className="inline-flex items-center gap-1 text-[13px] font-semibold text-primary hover:underline"
              >
                View all decisions <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
            <div className="space-y-2">
              {queueItems.map((q) => (
                <motion.div
                  key={q.sql}
                  whileHover={{ x: 2 }}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/70 px-4 py-3"
                >
                  <SqlBlock>{q.sql}</SqlBlock>
                  <div className="flex items-center gap-3 text-[12px]">
                    <span className={"font-semibold capitalize " + riskColor[q.risk]}>
                      {q.risk} Risk
                    </span>
                    <span className="text-muted-foreground">{q.confidence}</span>
                  </div>
                </motion.div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel className="px-6 py-5" delay={0.06}>
            <Label className="mb-4">Recent Activity</Label>
            <div className="space-y-4">
              {activity.map((a) => (
                <div key={a.time} className="flex gap-3 text-[13px]">
                  <span className="w-9 shrink-0 tabular-nums text-muted-foreground">{a.time}</span>
                  <span className={"mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full " + toneDot[a.tone]} />
                  <p className="flex-1 text-muted-foreground">
                    <span className="font-semibold text-foreground">{a.kind}</span>
                    <span className="px-1.5 text-border">·</span>
                    {a.text}
                  </p>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="border-amber-200 bg-amber-50/50 px-6 py-5" delay={0.1}>
            <Label className="mb-3 !text-primary">AI Insight</Label>
            <p className="text-[14px] leading-relaxed text-foreground">
              Approve in the next deployment window. The recommendation is supported by{" "}
              <span className="font-semibold">36 successful index migrations</span> with matching table
              size and lock profile.
            </p>
            <Link
              to="/agent-memory"
              className="mt-4 inline-flex items-center gap-1 text-[13px] font-semibold text-primary hover:underline"
            >
              Supporting memories <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </Panel>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
        <Panel delay={0.12}>
          <div className="px-6 py-5">
            <div className="mb-4 flex items-center justify-between">
              <Label>Latest Migration</Label>
              <StatusPill status="COMPLETED" />
            </div>
            <div className="rounded-lg bg-muted/70 px-4 py-3">
              <SqlBlock>ALTER TABLE demo_items ADD COLUMN notes STRING;</SqlBlock>
            </div>
            <div className="mt-3 text-[13px] text-muted-foreground">11h ago</div>
            <div className="mt-4 flex items-center gap-4">
              <button
                type="button"
                className="rounded-lg border border-border bg-secondary px-3.5 py-2 text-[13px] font-semibold text-foreground transition-colors hover:bg-muted active:scale-[0.98]"
              >
                Set as current
              </button>
              <Link
                to="/current-migration"
                className="inline-flex items-center gap-1 text-[13px] font-semibold text-primary hover:underline"
              >
                View detail <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
          <div className="border-t border-border px-6 py-5">
            <Label className="mb-3">Recent</Label>
            <div className="space-y-2.5">
              {recentMigrations.map((m) => (
                <div key={m.sql} className="flex items-center justify-between gap-3">
                  <SqlBlock className="text-[12px]">{m.sql}</SqlBlock>
                  <StatusPill status={m.status} />
                </div>
              ))}
            </div>
          </div>
        </Panel>

        <Panel delay={0.14}>
          <div className="grid grid-cols-1 gap-6 px-6 py-5 sm:grid-cols-[1fr_1.6fr]">
            <div>
              <Label className="mb-3">Accuracy</Label>
              <div className="text-[13px] text-muted-foreground">Graded</div>
              <div className="text-[44px] font-bold leading-none tracking-tight text-foreground">
                6
              </div>
            </div>
            <div className="text-right">
              <div className="mb-3 flex items-center justify-end gap-2">
                <Label>Migration Success Rate</Label>
                <Link
                  to="/agent-memory"
                  className="inline-flex items-center gap-1 text-[11px] font-bold uppercase tracking-[0.08em] text-primary hover:underline"
                >
                  Memory <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
              <div className="text-[40px] font-bold leading-none tracking-tight tabular-nums text-foreground">
                6 / 6 · 100%
              </div>
              <p className="mt-3 text-[12px] leading-relaxed text-muted-foreground">
                % of graded runs whose shadow execution actually succeeded.
              </p>
            </div>
          </div>
          <div className="border-t border-border px-6 py-5">
            <Label className="mb-4">Approval Decisions</Label>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {[
                { k: "Proceeded", v: "6", c: "text-foreground" },
                { k: "Accepted Plan", v: "0", c: "text-foreground" },
                { k: "Cancelled", v: "0", c: "text-foreground" },
                { k: "Awaiting Decision", v: "4", c: "text-amber-600" },
              ].map((s) => (
                <div key={s.k}>
                  <div className="section-label">{s.k}</div>
                  <div className={"mt-1.5 text-[26px] font-bold tabular-nums " + s.c}>{s.v}</div>
                </div>
              ))}
            </div>
            <div className="mt-5 flex items-center gap-3 border-t border-border pt-4 text-[12px]">
              <span className="section-label">Memory</span>
              <span className="font-semibold text-primary">36 ready</span>
              <span className="text-muted-foreground">0 pending</span>
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}
