import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { motion } from "motion/react";
import { Search, Check, X, AlertTriangle, ChevronLeft, ChevronRight } from "lucide-react";
import { PageHeader, Panel, Label } from "@/components/ui-kit";
import { pastMigrations, dailyVolume, type PastMigration } from "@/lib/migration-data";

export const Route = createFileRoute("/past-migrations")({
  head: () => ({
    meta: [
      { title: "Past Migrations — Migration Oracle" },
      {
        name: "description",
        content:
          "Full audit trail of executed database migrations with risk, confidence, shadow results and approvers.",
      },
      { property: "og:title", content: "Past Migrations — Migration Oracle" },
      {
        property: "og:description",
        content: "Audit trail of executed migrations with risk, confidence and shadow outcomes.",
      },
    ],
  }),
  component: PastMigrations,
});

const riskColor: Record<string, string> = {
  low: "text-emerald-600",
  medium: "text-amber-600",
  high: "text-red-600",
};
const barColor: Record<string, string> = {
  low: "bg-emerald-500",
  medium: "bg-amber-500",
  high: "bg-red-500",
};

function ShadowIcon({ s }: { s: PastMigration["shadow"] }) {
  if (s === "pass") return <Check className="h-4 w-4 text-emerald-600" />;
  if (s === "warn") return <AlertTriangle className="h-4 w-4 text-amber-500" />;
  return <X className="h-4 w-4 text-red-500" />;
}

function OutcomePill({ o }: { o: PastMigration["outcome"] }) {
  const cls =
    o === "CANCELLED"
      ? "border-red-200 bg-red-50 text-red-600"
      : "border-emerald-200 bg-emerald-50 text-emerald-600";
  const dot = o === "CANCELLED" ? "bg-red-500" : "bg-emerald-500";
  return (
    <span
      className={"inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-bold " + cls}
    >
      <span className={"h-1.5 w-1.5 rounded-full " + dot} />
      {o}
    </span>
  );
}

const selectCls =
  "h-10 rounded-lg border border-border bg-card px-3 text-sm text-foreground outline-none transition-colors focus:border-primary";

function PastMigrations() {
  const [query, setQuery] = useState("");
  const [risk, setRisk] = useState("all");
  const [outcome, setOutcome] = useState("all");
  const [approver, setApprover] = useState("all");
  const [perPage, setPerPage] = useState(8);
  const [page, setPage] = useState(1);

  const filtered = useMemo(
    () =>
      pastMigrations.filter(
        (m) =>
          (query === "" ||
            m.sql.toLowerCase().includes(query.toLowerCase()) ||
            m.table.includes(query.toLowerCase())) &&
          (risk === "all" || m.risk === risk) &&
          (outcome === "all" || m.outcome === outcome) &&
          (approver === "all" || m.approver === approver),
      ),
    [query, risk, outcome, approver],
  );

  const pages = Math.max(1, Math.ceil(filtered.length / perPage));
  const current = Math.min(page, pages);
  const rows = filtered.slice((current - 1) * perPage, current * perPage);
  const max = 4;

  return (
    <>
      <PageHeader
        title="Past Migrations"
        subtitle={`Full audit trail — ${pastMigrations.length} migrations on record.`}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
        <Panel className="px-6 py-5">
          <Label className="mb-4">Accuracy Summary</Label>
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            {[
              { v: "10", k: "Total Migrations", s: "all time", c: "text-foreground" },
              { v: "8", k: "Graded", s: "eligible for scoring", c: "text-foreground" },
              { v: "75%", k: "Shadow Pass Rate", s: "6 of 8 graded", c: "text-emerald-600" },
              { v: "2", k: "Cancelled", s: "rejected or deferred", c: "text-red-600" },
            ].map((s) => (
              <div key={s.k}>
                <div className={"text-[26px] font-bold leading-none tabular-nums " + s.c}>{s.v}</div>
                <div className="mt-2 text-[13px] font-semibold text-foreground">{s.k}</div>
                <div className="text-[12px] text-muted-foreground">{s.s}</div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel className="px-6 py-5" delay={0.05}>
          <div className="mb-4 flex items-center justify-between">
            <Label>Daily Migration Volume</Label>
            <span className="text-[12px] text-muted-foreground">Last 7 days</span>
          </div>
          <div className="flex h-[150px] gap-2">
            <div className="flex w-4 flex-col justify-between py-1 text-right text-[11px] text-muted-foreground">
              {[4, 3, 2, 1, 0].map((n) => (
                <span key={n}>{n}</span>
              ))}
            </div>
            <div className="flex flex-1 items-end justify-between gap-3 border-b border-border pb-0">
              {dailyVolume.map((d) => (
                <div key={d.day} className="flex flex-1 flex-col items-center gap-2">
                  <div className="flex h-[120px] w-full items-end justify-center gap-1">
                    <motion.div
                      initial={{ height: 0 }}
                      animate={{ height: `${(d.a / max) * 100}%` }}
                      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                      className="w-3 rounded-t-[2px] bg-primary/25"
                    />
                    <motion.div
                      initial={{ height: 0 }}
                      animate={{ height: `${(d.b / max) * 100}%` }}
                      transition={{ duration: 0.5, delay: 0.06, ease: [0.22, 1, 0.36, 1] }}
                      className="w-3 rounded-t-[2px] bg-primary"
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-2 flex gap-3 pl-6">
            {dailyVolume.map((d) => (
              <div key={d.day} className="flex-1 text-center text-[11px] text-muted-foreground">
                {d.day}
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <div className="relative min-w-[260px] flex-1 sm:max-w-[320px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Search SQL or table…"
            className="h-10 w-full rounded-lg border border-border bg-card pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
          />
        </div>
        <select value={risk} onChange={(e) => setRisk(e.target.value)} className={selectCls}>
          <option value="all">All risk levels</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
        <select value={outcome} onChange={(e) => setOutcome(e.target.value)} className={selectCls}>
          <option value="all">All outcomes</option>
          <option value="COMPLETED">Completed</option>
          <option value="CANCELLED">Cancelled</option>
          <option value="PROCEEDED">Proceeded</option>
        </select>
        <select value={approver} onChange={(e) => setApprover(e.target.value)} className={selectCls}>
          <option value="all">All approvers</option>
          <option>Samved M.</option>
          <option>Priya N.</option>
          <option>Arjun K.</option>
          <option>Leila H.</option>
        </select>
      </div>

      <Panel className="mt-4 overflow-hidden" delay={0.08}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1050px] border-collapse text-left">
            <thead>
              <tr className="border-b border-border bg-muted/50">
                <th className="w-10 py-3 pl-6">
                  <input type="checkbox" className="h-3.5 w-3.5 accent-[oklch(0.5534_0.1739_38.4)]" />
                </th>
                {[
                  "SQL / Table",
                  "Executed ↓",
                  "Duration",
                  "Risk ↓",
                  "Confidence ↓",
                  "Shadow",
                  "Outcome",
                  "Approver",
                  "Graded",
                ].map((h) => (
                  <th key={h} className="section-label py-3 pr-4 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.sql + m.date} className="border-b border-border transition-colors hover:bg-muted/40">
                  <td className="py-4 pl-6">
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 accent-[oklch(0.5534_0.1739_38.4)]"
                    />
                  </td>
                  <td className="max-w-[300px] py-4 pr-4">
                    <div className="truncate font-mono text-[12.5px] text-foreground">{m.sql}</div>
                    <div className="mt-0.5 font-mono text-[11.5px] text-muted-foreground">
                      {m.table}
                    </div>
                  </td>
                  <td className="py-4 pr-4 font-mono text-[12.5px] text-foreground">
                    <div>{m.date}</div>
                    <div className="text-muted-foreground">{m.time}</div>
                  </td>
                  <td className="py-4 pr-4 font-mono text-[12.5px] text-foreground">{m.duration}</td>
                  <td className={"py-4 pr-4 text-[13px] font-semibold capitalize " + riskColor[m.risk]}>
                    {m.risk}
                  </td>
                  <td className="py-4 pr-4">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-[70px] overflow-hidden rounded-full bg-muted">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${m.confidence}%` }}
                          transition={{ duration: 0.5 }}
                          className={"h-full rounded-full " + barColor[m.risk]}
                        />
                      </div>
                      <span className="text-[12.5px] tabular-nums text-foreground">
                        {m.confidence}%
                      </span>
                    </div>
                  </td>
                  <td className="py-4 pr-4">
                    <ShadowIcon s={m.shadow} />
                  </td>
                  <td className="py-4 pr-4">
                    <OutcomePill o={m.outcome} />
                  </td>
                  <td className="py-4 pr-4 text-[13px] text-foreground">{m.approver}</td>
                  <td className="py-4 pr-6">
                    <span
                      className={
                        "rounded-full border px-2.5 py-1 text-[11px] font-semibold " +
                        (m.graded === "Graded"
                          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                          : "border-border bg-muted text-muted-foreground")
                      }
                    >
                      {m.graded}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div className="flex items-center gap-3">
            <span className="text-[13px] text-muted-foreground">Rows per page</span>
            <select
              value={perPage}
              onChange={(e) => {
                setPerPage(Number(e.target.value));
                setPage(1);
              }}
              className="h-8 rounded-md border border-border bg-card px-2 text-[13px] outline-none"
            >
              {[5, 8, 10, 20].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="mr-2 text-[13px] text-muted-foreground tabular-nums">
              {filtered.length === 0
                ? "0 of 0"
                : `${(current - 1) * perPage + 1}–${Math.min(current * perPage, filtered.length)} of ${filtered.length}`}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted disabled:opacity-40"
              disabled={current === 1}
              aria-label="Previous page"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setPage(n)}
                className={
                  "h-8 w-8 rounded-md text-[13px] font-semibold transition-colors " +
                  (n === current
                    ? "bg-primary text-primary-foreground"
                    : "text-foreground hover:bg-muted")
                }
              >
                {n}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted disabled:opacity-40"
              disabled={current === pages}
              aria-label="Next page"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </Panel>
    </>
  );
}
