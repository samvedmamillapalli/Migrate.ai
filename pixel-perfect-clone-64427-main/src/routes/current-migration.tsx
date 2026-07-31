import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { motion } from "motion/react";
import { Copy, Check, X, Clock, AlertTriangle } from "lucide-react";
import { PageHeader, Panel, Label, StatusPill, SqlBlock } from "@/components/ui-kit";
import { shadowChecks, timeline, riskFactors } from "@/lib/migration-data";

export const Route = createFileRoute("/current-migration")({
  head: () => ({
    meta: [
      { title: "Current Migration — Migration Oracle" },
      {
        name: "description",
        content:
          "Review shadow execution evidence, AI risk analysis and approve or reject the pending migration.",
      },
      { property: "og:title", content: "Current Migration — Migration Oracle" },
      {
        property: "og:description",
        content:
          "Shadow evidence, risk analysis and the approval decision for the pending migration.",
      },
    ],
  }),
  component: CurrentMigration,
});

const SQL = "CREATE INDEX idx_users_email ON users (email);";

const details: [string, string][] = [
  ["Stage", "Awaiting Approval"],
  ["Risk Level", "Low"],
  ["AI Confidence", "94%"],
  ["Est. Duration", "2m 10s"],
  ["Target Table", "users"],
  ["Estimated Rows", "2,847,391"],
  ["Index Type", "B-Tree"],
  ["Lock Mode", "SHARE"],
];

const toneDot: Record<string, string> = { blue: "bg-blue-500", violet: "bg-violet-500" };

function CurrentMigration() {
  const [copied, setCopied] = useState(false);
  const [decision, setDecision] = useState<string | null>(null);

  return (
    <>
      <PageHeader
        title="Current Migration"
        subtitle="Review shadow evidence and make an approval decision."
        action={<StatusPill status="AWAITING APPROVAL" />}
      />

      <Panel className="mb-5 px-6 py-5">
        <div className="mb-3 flex items-center justify-between">
          <Label>Migration SQL</Label>
          <button
            type="button"
            onClick={() => {
              navigator.clipboard?.writeText(SQL);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
            className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:text-foreground active:scale-95"
          >
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <SqlBlock className="text-[14px]">{SQL}</SqlBlock>
      </Panel>

      <Panel className="mb-5 px-6 py-5" delay={0.04}>
        <Label className="mb-3">Next Action</Label>
        <p className="text-[14px] leading-relaxed text-foreground">
          Review the shadow evidence above, then approve this low-risk index. The AI model has 94%
          confidence based on 36 matching verified runs with identical table size and lock profile.
          Shadow execution completed with no lock escalation on replica-03.
        </p>
      </Panel>

      <Panel className="mb-5 px-6 py-5" delay={0.06}>
        <Label className="mb-4">Approval Decision</Label>
        <div className="flex flex-wrap items-center gap-3">
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={() => setDecision("approve")}
            className={
              "inline-flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-semibold transition-colors " +
              (decision === "approve"
                ? "bg-primary text-primary-foreground ring-2 ring-primary/30"
                : "bg-primary text-primary-foreground hover:bg-primary/90")
            }
          >
            <Check className="h-4 w-4" /> Approve
          </motion.button>
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={() => setDecision("reject")}
            className={
              "inline-flex items-center gap-2 rounded-lg border border-border px-5 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted " +
              (decision === "reject" ? "bg-muted" : "bg-secondary")
            }
          >
            <X className="h-4 w-4 text-muted-foreground" /> Reject
          </motion.button>
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={() => setDecision("defer")}
            className={
              "inline-flex items-center gap-2 rounded-lg border border-border px-5 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted " +
              (decision === "defer" ? "bg-muted" : "bg-card")
            }
          >
            <Clock className="h-4 w-4 text-muted-foreground" /> Defer
          </motion.button>
        </div>
        <p className="mt-4 text-[13px] text-muted-foreground">
          This action will be logged and attributed to your account.
        </p>
      </Panel>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Panel className="px-6 py-5" delay={0.08}>
            <div className="mb-4 flex items-center justify-between">
              <Label>Shadow Execution Evidence</Label>
              <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-emerald-600">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                All checks passed
              </span>
            </div>
            <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
              {[
                ["Replica", "replica-03"],
                ["Duration", "1m 47s"],
                ["Shadow Runs", "3"],
              ].map(([k, v]) => (
                <div key={k} className="rounded-lg border border-border bg-muted/60 px-4 py-3">
                  <div className="section-label">{k}</div>
                  <div className="mt-1.5 text-[15px] font-semibold text-foreground">{v}</div>
                </div>
              ))}
            </div>
            <div className="space-y-2">
              {shadowChecks.map((c) => (
                <div
                  key={c.name}
                  className={
                    "flex items-start justify-between gap-3 rounded-lg border px-4 py-3 " +
                    (c.state === "warn"
                      ? "border-amber-200 bg-amber-50/50"
                      : "border-border bg-card")
                  }
                >
                  <div className="flex gap-3">
                    {c.state === "warn" ? (
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                    ) : (
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                    )}
                    <div>
                      <div className="text-[13px] font-semibold text-foreground">{c.name}</div>
                      <div className="mt-0.5 text-[13px] text-muted-foreground">{c.detail}</div>
                    </div>
                  </div>
                  <span
                    className={
                      "rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide " +
                      (c.state === "warn"
                        ? "bg-amber-100 text-amber-700"
                        : "bg-emerald-50 text-emerald-700")
                    }
                  >
                    {c.state}
                  </span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.1}>
            <div className="mb-4 flex items-center justify-between">
              <Label>AI Risk Analysis</Label>
              <span className="text-[13px]">
                <span className="font-bold text-foreground">94%</span>{" "}
                <span className="text-muted-foreground">confidence</span>
              </span>
            </div>
            <div className="space-y-3">
              {riskFactors.map((r) => (
                <div key={r.name} className="border-b border-border pb-3 last:border-0 last:pb-0">
                  <div className="text-[13px] font-semibold text-foreground">{r.name}</div>
                  <div className="mt-0.5 text-[13px] text-muted-foreground">{r.detail}</div>
                </div>
              ))}
            </div>
            <p className="mt-4 text-[13px] text-muted-foreground">
              Based on <span className="font-semibold text-foreground">36 verified memory runs</span>{" "}
              with matching table size, column type, and lock profile.
            </p>
          </Panel>

          <Panel className="px-6 py-5" delay={0.12}>
            <div className="mb-4 flex items-center justify-between">
              <Label>Prediction vs Actual</Label>
              <span className="text-[13px]">
                <span className="font-bold text-foreground">97%</span>{" "}
                <span className="text-muted-foreground">avg accuracy</span>
              </span>
            </div>
            <div className="space-y-3">
              {[
                ["Runtime", "2m 10s", "1m 47s"],
                ["Lock time", "< 1s", "0.4s"],
                ["Replica lag", "< 500ms", "340ms"],
              ].map(([k, p, a]) => (
                <div
                  key={k}
                  className="flex items-center justify-between border-b border-border pb-3 text-[13px] last:border-0 last:pb-0"
                >
                  <span className="font-semibold text-foreground">{k}</span>
                  <span className="text-muted-foreground">
                    predicted <span className="font-mono text-foreground">{p}</span>
                    <span className="px-2 text-border">·</span>
                    actual <span className="font-mono text-emerald-600">{a}</span>
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel className="px-6 py-5" delay={0.09}>
            <Label className="mb-4">Migration Details</Label>
            <div className="grid grid-cols-2 gap-x-4 gap-y-4">
              {details.map(([k, v]) => (
                <div key={k}>
                  <div className="section-label">{k}</div>
                  <div className="mt-1 text-[14px] font-semibold text-foreground">{v}</div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.11}>
            <Label className="mb-4">Activity Timeline</Label>
            <div className="space-y-4">
              {timeline.map((t) => (
                <div key={t.title} className="flex gap-3">
                  <span
                    className={
                      "mt-1.5 h-2 w-2 shrink-0 rounded-full ring-4 ring-muted " + toneDot[t.tone]
                    }
                  />
                  <div className="text-[13px]">
                    <div>
                      <span className="font-semibold text-foreground">{t.title}</span>{" "}
                      <span className="text-muted-foreground">{t.by}</span>
                    </div>
                    <div className="mt-0.5 text-muted-foreground">{t.detail}</div>
                    <div className="mt-0.5 text-[12px] text-muted-foreground">{t.at}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
