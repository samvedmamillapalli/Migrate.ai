"use client"

import { memo } from "react"
import {
  Handle,
  Position,
  type Node,
  type NodeProps,
} from "@xyflow/react"

export type MigrationNodeVariant =
  | "sql"
  | "analyze"
  | "prediction"
  | "shadow"
  | "verify"
  | "memory"

export type MigrationNodeData = {
  variant: MigrationNodeVariant
  /** Right-side feedback handles (Memory → Prediction) */
  feedbackSource?: boolean
  feedbackTarget?: boolean
}

export type MigrationNode = Node<MigrationNodeData, "migration">

const handleClass =
  "!h-1 !w-1 !min-h-0 !min-w-0 !border-transparent !bg-transparent opacity-0"

function MigrationNodeComponent({ data }: NodeProps<MigrationNode>) {
  const handles = (
    <>
      <Handle type="target" position={Position.Left} className={handleClass} />
      {data.feedbackTarget ? (
        <Handle
          type="target"
          position={Position.Bottom}
          id="fb"
          className={handleClass}
        />
      ) : null}
      <Handle type="source" position={Position.Right} className={handleClass} />
      {data.feedbackSource ? (
        <Handle
          type="source"
          position={Position.Bottom}
          id="fb"
          className={handleClass}
        />
      ) : null}
    </>
  )

  switch (data.variant) {
    case "sql":
      return (
        <div className="relative w-[132px]">
          {handles}
          <div className="text-muted-foreground font-mono text-[9px] tracking-[0.14em] uppercase">
            Input
          </div>
          <div className="text-foreground mt-1.5 text-[13px] font-medium tracking-tight">
            Migration SQL
          </div>
          <div className="text-foreground/70 mt-1 font-mono text-[11px] tracking-tight">
            migration.sql
          </div>
        </div>
      )

    case "analyze":
      return (
        <div className="relative w-[168px]">
          {handles}
          <div className="text-foreground text-[13px] font-medium tracking-tight">
            Analyze
          </div>
          <div className="text-muted-foreground mt-1 font-mono text-[10px] tracking-tight">
            14 tables · 3 indexes
          </div>
          <div className="border-border/40 mt-3 space-y-1.5 border-l pl-2.5">
            <TelemetryRow k="Runtime" v="3.6s" />
            <TelemetryRow k="Risk" v="Low" />
            <TelemetryRow k="Storage" v="+18 MB" />
          </div>
        </div>
      )

    case "prediction":
      return (
        <div className="relative w-[148px]">
          {handles}
          <div className="text-[#C4B5FD]/90 font-mono text-[9px] tracking-[0.14em] uppercase">
            Prediction
          </div>
          <div className="text-foreground mt-2 font-mono text-[22px] leading-none tracking-tight">
            3.6s
          </div>
          <div className="text-[#C4B5FD]/80 mt-2 font-mono text-[11px] tracking-tight">
            97% confidence
          </div>
          <div className="text-muted-foreground mt-1 font-mono text-[10px] tracking-tight">
            Low risk
          </div>
        </div>
      )

    case "shadow":
      return (
        <div className="relative w-[200px]">
          {handles}
          <ClusterTopology />
          <div className="text-foreground mt-3 text-center text-[13px] font-medium tracking-tight">
            Shadow Execution
          </div>
          <div className="text-muted-foreground mt-1 text-center font-mono text-[10px] tracking-tight">
            CockroachDB
          </div>
          <div className="text-muted-foreground/70 mt-0.5 text-center font-mono text-[10px] tracking-tight">
            ephemeral · 12 / 12 · 3.8s
          </div>
        </div>
      )

    case "verify":
      return (
        <div className="relative w-[180px]">
          {handles}
          <div className="text-muted-foreground font-mono text-[9px] tracking-[0.14em] uppercase">
            Verification
          </div>
          <div className="mt-2.5 grid grid-cols-[1fr_auto_1fr] items-end gap-2">
            <div>
              <div className="text-muted-foreground font-mono text-[9px] tracking-tight">
                Predicted
              </div>
              <div className="text-foreground mt-0.5 font-mono text-[15px] tracking-tight">
                3.6s
              </div>
            </div>
            <div className="text-muted-foreground/50 pb-0.5 font-mono text-[11px]">
              →
            </div>
            <div className="text-right">
              <div className="text-muted-foreground font-mono text-[9px] tracking-tight">
                Actual
              </div>
              <div className="text-foreground mt-0.5 font-mono text-[15px] tracking-tight">
                3.8s
              </div>
            </div>
          </div>
          <div className="text-emerald-400/85 mt-2.5 font-mono text-[11px] tracking-tight">
            Δ +0.2s · within band
          </div>
        </div>
      )

    case "memory":
      return (
        <div className="relative w-[120px]">
          {handles}
          <div className="text-muted-foreground font-mono text-[9px] tracking-[0.14em] uppercase">
            Memory
          </div>
          <div className="mt-2 flex items-center gap-2">
            <span
              aria-hidden
              className="border-border/60 bg-background size-2 rounded-full border"
            />
            <span className="text-foreground text-[12px] font-medium tracking-tight">
              Learned
            </span>
          </div>
          <div className="text-muted-foreground mt-1 font-mono text-[10px] tracking-tight">
            outcome stored
          </div>
        </div>
      )

    default:
      return null
  }
}

function TelemetryRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-muted-foreground/80 text-[10px] tracking-tight">
        {k}
      </span>
      <span className="text-foreground/75 font-mono text-[10px] tracking-tight">
        {v}
      </span>
    </div>
  )
}

function ClusterTopology() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 72 48"
      className="mx-auto h-12 w-[72px] overflow-visible"
    >
      <line
        x1="18"
        y1="14"
        x2="54"
        y2="14"
        stroke="currentColor"
        strokeWidth="1"
        className="text-border"
      />
      <line
        x1="18"
        y1="14"
        x2="36"
        y2="36"
        stroke="currentColor"
        strokeWidth="1"
        className="text-border"
      />
      <line
        x1="54"
        y1="14"
        x2="36"
        y2="36"
        stroke="currentColor"
        strokeWidth="1"
        className="text-border"
      />
      <circle
        cx="18"
        cy="14"
        r="4.5"
        className="fill-[#0A0A0A] stroke-border"
        strokeWidth="1.25"
      />
      <circle
        cx="54"
        cy="14"
        r="4.5"
        className="fill-[#0A0A0A] stroke-border"
        strokeWidth="1.25"
      />
      <circle
        cx="36"
        cy="36"
        r="5"
        className="fill-[#0A0A0A] stroke-foreground/50"
        strokeWidth="1.25"
      />
    </svg>
  )
}

export default memo(MigrationNodeComponent)

export const NODE_WIDTH: Record<MigrationNodeVariant, number> = {
  sql: 132,
  analyze: 168,
  prediction: 148,
  shadow: 200,
  verify: 180,
  memory: 120,
}

export const NODE_HEIGHT: Record<MigrationNodeVariant, number> = {
  sql: 64,
  analyze: 118,
  prediction: 96,
  shadow: 128,
  verify: 100,
  memory: 72,
}
