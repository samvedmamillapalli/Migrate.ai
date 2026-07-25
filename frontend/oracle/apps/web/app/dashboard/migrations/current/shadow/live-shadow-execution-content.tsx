import { cn } from "@workspace/ui/lib/utils"

import type { LiveShadowExecutionData } from "./shadow-execution-state"

function LabeledClusterTopology({
  nodes,
}: {
  nodes: LiveShadowExecutionData["nodes"]
}) {
  const [node1, node2, node3] = nodes

  return (
    <div className="mx-auto w-full max-w-md py-1" aria-hidden>
      <svg
        viewBox="0 0 280 150"
        className="text-muted-foreground/55 h-32 w-full sm:h-36"
      >
        <line
          x1="48"
          y1="36"
          x2="232"
          y2="36"
          stroke="currentColor"
          strokeWidth="1"
        />
        <line
          x1="48"
          y1="36"
          x2="140"
          y2="118"
          stroke="currentColor"
          strokeWidth="1"
        />
        <line
          x1="232"
          y1="36"
          x2="140"
          y2="118"
          stroke="currentColor"
          strokeWidth="1"
        />
        <circle
          cx="48"
          cy="36"
          r="5.5"
          fill="var(--background)"
          stroke="currentColor"
          strokeWidth="1.25"
        />
        <circle
          cx="232"
          cy="36"
          r="5.5"
          fill="var(--background)"
          stroke="currentColor"
          strokeWidth="1.25"
        />
        <circle
          cx="140"
          cy="118"
          r="5.5"
          fill="var(--background)"
          stroke="currentColor"
          strokeWidth="1.25"
        />
        <text
          x="48"
          y="18"
          textAnchor="middle"
          className="fill-muted-foreground font-mono text-[11px]"
        >
          {node1?.label ?? "node-1"}
        </text>
        <text
          x="232"
          y="18"
          textAnchor="middle"
          className="fill-muted-foreground font-mono text-[11px]"
        >
          {node2?.label ?? "node-2"}
        </text>
        <text
          x="140"
          y="142"
          textAnchor="middle"
          className="fill-muted-foreground font-mono text-[11px]"
        >
          {node3?.label ?? "node-3"}
        </text>
      </svg>
    </div>
  )
}

/** Live execution visualization body — reused by ShadowExecutionWindow. */
export function LiveShadowExecutionContent({
  data,
}: {
  data: LiveShadowExecutionData
}) {
  const lastEventIndex = data.events.length - 1

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 md:p-5">
      <LabeledClusterTopology nodes={data.nodes} />

      <ol className="border-border/60 flex flex-wrap items-center gap-x-1.5 gap-y-1 border-y py-3">
        {data.lifecycleStages.map((stage, index) => (
          <li key={stage.id} className="flex items-center gap-1.5">
            {index > 0 ? (
              <span className="text-muted-foreground/35 font-mono text-[10px]">
                →
              </span>
            ) : null}
            <span
              className={cn(
                "font-mono text-[10px] tracking-[0.1em] uppercase",
                stage.state === "complete" && "text-muted-foreground/60",
                stage.state === "current" && "text-foreground",
                stage.state === "pending" && "text-muted-foreground/30"
              )}
            >
              {stage.label}
            </span>
          </li>
        ))}
      </ol>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-2.5">
          <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
            Schema changes
          </p>
          <p className="text-foreground font-mono text-xs tracking-tight">
            {data.schemaChanges.table}
          </p>
          <ul className="space-y-1">
            {data.schemaChanges.mutations.map((mutation) => (
              <li
                key={mutation.name}
                className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-baseline gap-x-3 font-mono text-[11px] tracking-tight"
              >
                <span className="text-[var(--oracle-verified)]">+</span>
                <span className="text-foreground/85 truncate">
                  {mutation.name}
                </span>
                <span className="text-muted-foreground/70 text-right">
                  {mutation.detail}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-2.5">
          <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
            Current operation
          </p>
          <p className="text-foreground font-mono text-sm tracking-tight tabular-nums">
            {String(data.currentOperation.statementsCompleted).padStart(2, "0")}{" "}
            /{" "}
            {String(data.currentOperation.statementsTotal).padStart(2, "0")}
          </p>
          <pre className="text-foreground/85 overflow-x-auto font-mono text-[11px] leading-relaxed tracking-tight whitespace-pre-wrap">
            {data.currentOperation.sql}
          </pre>
        </div>
      </div>

      <div className="space-y-2 border-t border-border/60 pt-4">
        <p className="text-muted-foreground/60 font-mono text-[10px] tracking-[0.12em] uppercase">
          Execution stream
        </p>
        <div className="overflow-hidden rounded-md border border-[#2D2D2D] bg-[#141414] px-3 py-3">
          <ul className="space-y-1.5 font-mono text-[11px] leading-relaxed tracking-tight">
            {data.events.map((event, index) => {
              const isLatest = index === lastEventIndex
              return (
                <li
                  key={`${event.time}-${event.message}`}
                  className="flex gap-3"
                >
                  <span
                    className={cn(
                      "w-14 shrink-0 tabular-nums",
                      isLatest ? "text-[#9A9A9A]" : "text-[#6B6B6B]"
                    )}
                  >
                    {event.time}
                  </span>
                  <span
                    className={cn(
                      isLatest ? "text-[#D4D4D4]" : "text-[#A8A8A8]"
                    )}
                  >
                    {event.message}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      </div>

      <div className="border-border/60 mt-auto grid grid-cols-2 gap-x-6 gap-y-2 border-t pt-4 sm:grid-cols-5">
        {(
          [
            ["runtime", data.telemetry.runtime],
            ["storage", data.telemetry.storage],
            [
              "statements",
              `${String(data.currentOperation.statementsCompleted).padStart(2, "0")} / ${String(data.currentOperation.statementsTotal).padStart(2, "0")}`,
            ],
            ["locks", String(data.telemetry.locks)],
            ["failures", String(data.telemetry.failures)],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="space-y-0.5">
            <p className="text-muted-foreground/55 font-mono text-[10px] tracking-[0.1em] uppercase">
              {label}
            </p>
            <p className="text-foreground/85 font-mono text-xs tracking-tight tabular-nums">
              {value}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
