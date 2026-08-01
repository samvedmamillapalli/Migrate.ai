import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { PageHeader, Panel, Label } from "@/components/ui-kit";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Migration Oracle" },
      {
        name: "description",
        content:
          "Configure workspace identity, shadow execution, risk thresholds and notifications for Migration Oracle.",
      },
      { property: "og:title", content: "Settings — Migration Oracle" },
      {
        property: "og:description",
        content: "Workspace identity, shadow execution, risk thresholds and notifications.",
      },
    ],
  }),
  component: SettingsPage,
});

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onClick}
      className={
        "relative h-6 w-11 shrink-0 rounded-full transition-colors " +
        (on ? "bg-primary" : "bg-muted border border-border")
      }
    >
      <span
        className={
          "absolute top-0.5 h-5 w-5 rounded-full bg-card shadow-sm transition-all " +
          (on ? "left-[22px]" : "left-0.5")
        }
      />
    </button>
  );
}

function Row({
  title,
  detail,
  children,
}: {
  title: string;
  detail: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-6 border-b border-border py-4 last:border-0">
      <div>
        <div className="text-[13.5px] font-semibold text-foreground">{title}</div>
        <p className="mt-0.5 text-[13px] text-muted-foreground">{detail}</p>
      </div>
      {children}
    </div>
  );
}

const fieldCls =
  "h-11 w-full rounded-lg border border-border bg-card px-3.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary";

function SettingsPage() {
  const [shadow, setShadow] = useState(true);
  const [autoApprove, setAutoApprove] = useState(false);
  const [emailAlerts, setEmailAlerts] = useState(true);
  const [slack, setSlack] = useState(false);
  const [threshold, setThreshold] = useState(85);
  const [saved, setSaved] = useState(false);

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Workspace configuration for shadow execution, risk policy and notifications."
        action={
          <button
            type="button"
            onClick={() => {
              setSaved(true);
              setTimeout(() => setSaved(false), 2000);
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition-all duration-150 hover:bg-primary/90 active:scale-[0.98]"
          >
            {saved ? "Saved" : "Save changes"}
          </button>
        }
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Panel className="px-6 py-5">
            <Label className="mb-1">Workspace</Label>
            <div className="mt-4 space-y-4">
              <div>
                <Label className="mb-2">Workspace name</Label>
                <input className={fieldCls} defaultValue="Migration Oracle" />
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <Label className="mb-2">Owner</Label>
                  <input className={fieldCls} defaultValue="Samved Mamillapalli" />
                </div>
                <div>
                  <Label className="mb-2">Contact email</Label>
                  <input className={fieldCls} defaultValue="samvedmamillapalli@gmail.com" />
                </div>
              </div>
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.05}>
            <Label>Execution policy</Label>
            <div className="mt-2">
              <Row
                title="Shadow execution"
                detail="Run every migration against a replica before approval."
              >
                <Toggle on={shadow} onClick={() => setShadow((v) => !v)} />
              </Row>
              <Row
                title="Auto-approve low risk"
                detail="Skip manual review when confidence is above the threshold."
              >
                <Toggle on={autoApprove} onClick={() => setAutoApprove((v) => !v)} />
              </Row>
              <div className="py-4">
                <div className="flex items-center justify-between">
                  <div className="text-[13.5px] font-semibold text-foreground">
                    Confidence threshold
                  </div>
                  <span className="font-mono text-[13px] font-semibold text-primary">
                    {threshold}%
                  </span>
                </div>
                <input
                  type="range"
                  min={50}
                  max={99}
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                  className="mt-3 w-full accent-[var(--primary)]"
                />
              </div>
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.1}>
            <Label>Notifications</Label>
            <div className="mt-2">
              <Row title="Email alerts" detail="Send a digest when a migration awaits approval.">
                <Toggle on={emailAlerts} onClick={() => setEmailAlerts((v) => !v)} />
              </Row>
              <Row title="Slack alerts" detail="Post shadow results into #db-migrations.">
                <Toggle on={slack} onClick={() => setSlack((v) => !v)} />
              </Row>
            </div>
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel className="px-6 py-5" delay={0.08}>
            <Label className="mb-4">Current policy</Label>
            <div className="space-y-3 text-[13.5px]">
              {[
                ["Shadow execution", shadow ? "Enabled" : "Disabled"],
                ["Auto-approve", autoApprove ? "Enabled" : "Manual review"],
                ["Threshold", `${threshold}% confidence`],
                ["Alerts", [emailAlerts && "Email", slack && "Slack"].filter(Boolean).join(" · ") || "None"],
              ].map(([k, v]) => (
                <div key={k as string} className="flex items-center justify-between">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="font-semibold text-foreground">{v}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.12}>
            <Label className="mb-3">Danger zone</Label>
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Clearing agent memory removes all 36 verified runs used for confidence scoring.
            </p>
            <button
              type="button"
              className="mt-4 h-10 w-full rounded-lg border border-red-200 bg-red-50 text-sm font-semibold text-red-600 transition-colors hover:bg-red-100"
            >
              Clear agent memory
            </button>
          </Panel>
        </div>
      </div>
    </>
  );
}
