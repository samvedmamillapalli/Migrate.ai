"use client"

import * as React from "react"
import { motion, useInView, useReducedMotion } from "motion/react"

import { SystemStatusBlock } from "@/components/Animations/SystemTransition"
import {
  Timeline,
  type TimelineItem,
  type TimelineItemStatus,
} from "@/components/Animations/WorkflowTimeline"
import { ExecutionStatusHeader } from "@/components/landing/ExecutionStatusHeader"
import { Card } from "@workspace/ui/components/card"
import { cn } from "@workspace/ui/lib/utils"

const easeOut = [0.16, 1, 0.3, 1] as const

/* ─── SQL editor ─────────────────────────────────────────────────────────── */

const SQL_KEYWORDS = new Set([
  "CREATE",
  "TABLE",
  "ALTER",
  "ADD",
  "COLUMN",
  "INDEX",
  "ON",
  "IF",
  "NOT",
  "EXISTS",
  "PRIMARY",
  "KEY",
  "FOREIGN",
  "REFERENCES",
  "CONSTRAINT",
  "NULL",
  "UNIQUE",
  "DEFAULT",
  "CASCADE",
  "DROP",
  "AND",
  "OR",
  "USING",
  "WITH",
])

const SQL_TYPES = new Set([
  "UUID",
  "TEXT",
  "TIMESTAMPTZ",
  "TIMESTAMP",
  "INTEGER",
  "BIGINT",
  "BOOLEAN",
  "NUMERIC",
  "JSONB",
  "VARCHAR",
])

const SQL_SOURCE = `-- Migrate orders ownership + lookup path
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS created_by UUID;

ALTER TABLE orders
  ADD CONSTRAINT orders_created_by_fkey
  FOREIGN KEY (created_by) REFERENCES users(id);

CREATE INDEX IF NOT EXISTS idx_orders_created_at
  ON orders(created_at);`

const SQL_LINES = SQL_SOURCE.split("\n")
const ACTIVE_LINE = 14

type SqlTokenKind =
  | "keyword"
  | "type"
  | "ident"
  | "number"
  | "comment"
  | "plain"

const SQL_TOKEN_CLASS: Record<SqlTokenKind, string> = {
  keyword: "text-[#6A9BCF]",
  type: "text-[#5BB8A8]",
  ident: "text-[#C8C28A]",
  number: "text-[#C9956C]",
  comment: "text-[#6B7280]",
  plain: "text-foreground/80",
}

function highlightSqlLine(line: string): React.ReactNode {
  if (line.trimStart().startsWith("--")) {
    return <span className={SQL_TOKEN_CLASS.comment}>{line}</span>
  }
  if (line.length === 0) return " "

  const parts = line.split(/(\s+|[{}(),;.]|::)/g)

  return parts.map((part, i) => {
    if (
      !part ||
      /^\s+$/.test(part) ||
      /^[{}(),;.]$/.test(part) ||
      part === "::"
    ) {
      return (
        <span key={i} className={SQL_TOKEN_CLASS.plain}>
          {part}
        </span>
      )
    }

    const upper = part.toUpperCase()
    let kind: SqlTokenKind = "plain"

    if (SQL_KEYWORDS.has(upper)) kind = "keyword"
    else if (SQL_TYPES.has(upper)) kind = "type"
    else if (/^\d+(\.\d+)?$/.test(part)) kind = "number"
    else if (/^'.*'$/.test(part) || /^".*"$/.test(part)) kind = "number"
    else if (/^[a-zA-Z_][\w$]*$/.test(part)) {
      kind = part === "now" ? "type" : "ident"
    }

    return (
      <span key={i} className={SQL_TOKEN_CLASS[kind]}>
        {part}
      </span>
    )
  })
}

/* ─── Migration story ────────────────────────────────────────────────────── */

type TerminalLine = { kind: "prompt" | "ok"; text: string }

type StageDetail = { label: string; value: string }

type Stage = {
  id: string
  title: string
  operation: string
  details: StageDetail[]
  logs: TerminalLine[]
}

const STAGES: Stage[] = [
  {
    id: "analyze",
    title: "Analyze Schema",
    operation: "Analyze Schema",
    details: [{ label: "Tables Found", value: "14" }],
    logs: [
      { kind: "prompt", text: "analyzing migration..." },
      { kind: "ok", text: "detected CREATE INDEX" },
    ],
  },
  {
    id: "predict",
    title: "Predict Runtime",
    operation: "Predict Runtime",
    details: [{ label: "Estimated Runtime", value: "3.8s" }],
    logs: [{ kind: "ok", text: "estimated runtime: 3.8s" }],
  },
  {
    id: "provision",
    title: "Provision Shadow Cluster",
    operation: "Provision Shadow Cluster",
    details: [{ label: "Region", value: "us-east-1" }],
    logs: [{ kind: "ok", text: "shadow cluster ready" }],
  },
  {
    id: "execute",
    title: "Execute Migration",
    operation: "Execute Migration",
    details: [{ label: "Statements", value: "12 / 12" }],
    logs: [{ kind: "ok", text: "migration applied" }],
  },
  {
    id: "compare",
    title: "Compare Prediction",
    operation: "Compare Prediction",
    details: [{ label: "Deviation", value: "+0.2s" }],
    logs: [{ kind: "ok", text: "prediction accuracy: 97%" }],
  },
  {
    id: "learn",
    title: "Store Learned Outcome",
    operation: "Learn From Execution",
    details: [{ label: "Persisting", value: "outcome…" }],
    logs: [{ kind: "ok", text: "outcome stored in agentic memory" }],
  },
]

const METRICS = [
  {
    label: "Runtime",
    predicted: "3.8 s",
    actual: "4.0 s",
    delta: "+0.2 s",
  },
  {
    label: "Storage",
    predicted: "+142 MB",
    actual: "+138 MB",
    delta: "−4 MB",
  },
] as const

/** Per-stage dwell — ~650ms × 6 ≈ 3.9s core, plus setup/outro → ~5.5–6.5s */
const STAGE_MS = 650
const SETUP_MS = 450
const COMPARE_INDEX = 4

/* ─── Panels ─────────────────────────────────────────────────────────────── */

function TrafficLights() {
  return (
    <div aria-hidden className="flex items-center gap-1.5">
      <span className="size-2.5 rounded-full bg-[#FF5F57]/70" />
      <span className="size-2.5 rounded-full bg-[#FEBC2E]/70" />
      <span className="size-2.5 rounded-full bg-[#28C840]/70" />
    </div>
  )
}

function SqlEditor({ activeLine }: { activeLine: number | null }) {
  return (
    <div className="bg-background flex h-full min-h-[300px] flex-col overflow-hidden md:min-h-[420px]">
      <div
        aria-hidden
        className="font-mono flex-1 overflow-auto py-4 text-[12px] leading-[22px] sm:text-[12.5px]"
      >
        <ol className="m-0 list-none p-0">
          {SQL_LINES.map((line, index) => {
            const isActive = activeLine === index
            return (
              <li
                key={index}
                className={cn(
                  "flex transition-colors duration-300",
                  isActive && "bg-[#264F78]/28"
                )}
              >
                <span
                  className={cn(
                    "w-10 shrink-0 select-none pr-3 text-right tabular-nums",
                    isActive
                      ? "text-muted-foreground"
                      : "text-muted-foreground/40"
                  )}
                >
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1 whitespace-pre pr-5">
                  {highlightSqlLine(line)}
                </span>
              </li>
            )
          })}
        </ol>
      </div>
    </div>
  )
}

function buildTimelineItems(activeIndex: number): TimelineItem[] {
  return STAGES.map((stage, index) => {
    let status: TimelineItemStatus = "pending"
    if (activeIndex < 0) {
      status = "pending"
    } else if (activeIndex >= STAGES.length) {
      status = "completed"
    } else if (index < activeIndex) {
      status = "completed"
    } else if (index === activeIndex) {
      status = "active"
    }

    return {
      id: stage.id,
      title: stage.title,
      status,
    }
  })
}

function ExecutionPanel({
  activeIndex,
  operationId,
  operation,
  statusState,
  details,
  showComparison,
}: {
  activeIndex: number
  operationId: string
  operation: string
  statusState: "idle" | "running" | "complete"
  details: StageDetail[]
  showComparison: boolean
}) {
  const prefersReducedMotion = useReducedMotion()
  const items = buildTimelineItems(activeIndex)

  return (
    <div className="bg-background flex h-full min-h-[300px] flex-col overflow-hidden md:min-h-[420px]">
      <div className="flex flex-1 flex-col gap-6 px-5 py-5 sm:px-6 sm:py-6">
        <SystemStatusBlock
          operationId={operationId}
          operation={operation}
          status={statusState}
          details={details}
        />

        <Timeline items={items} variant="compact" />

        <motion.div
          className="mt-auto flex flex-col gap-7 pt-2"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 8 }}
          animate={
            showComparison || prefersReducedMotion
              ? { opacity: 1, y: 0 }
              : { opacity: 0, y: 8 }
          }
          transition={{ duration: 0.3, ease: easeOut }}
        >
          <p className="text-muted-foreground text-xs">
            Prediction vs Reality
          </p>

          <div className="flex flex-col gap-6">
            {METRICS.map((row) => (
              <div key={row.label} className="space-y-3">
                <p className="text-foreground text-sm font-medium tracking-tight">
                  {row.label}
                </p>
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-1">
                    <p className="text-muted-foreground text-xs">Predicted</p>
                    <p className="text-foreground font-mono text-sm">
                      {row.predicted}
                    </p>
                  </div>
                  <div className="space-y-1">
                    <p className="text-muted-foreground text-xs">Actual</p>
                    <p className="text-foreground font-mono text-sm">
                      {row.actual}
                    </p>
                  </div>
                  <div className="space-y-1">
                    <p className="text-muted-foreground text-xs">Diff</p>
                    <p className="text-foreground/70 font-mono text-sm">
                      {row.delta}
                    </p>
                  </div>
                </div>
              </div>
            ))}

            <div className="grid grid-cols-2 gap-6">
              <div className="space-y-1">
                <p className="text-muted-foreground text-xs">Rollback risk</p>
                <p className="text-foreground text-sm font-medium">Low</p>
              </div>
              <div className="space-y-1">
                <p className="text-muted-foreground text-xs">Confidence</p>
                <p className="text-foreground font-mono text-sm font-medium">
                  97%
                </p>
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  )
}

function TerminalPanel({ lines }: { lines: TerminalLine[] }) {
  const prefersReducedMotion = useReducedMotion()

  return (
    <div className="bg-background overflow-hidden">
      <div className="font-mono min-h-[132px] space-y-1 px-5 py-4 text-[12px] leading-[1.7] sm:px-6 sm:text-[12.5px]">
        {lines.map((line, index) => (
          <motion.div
            key={`${index}-${line.text}`}
            className="flex gap-2.5"
            initial={prefersReducedMotion ? false : { opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: easeOut }}
          >
            {line.kind === "prompt" ? (
              <>
                <span className="text-muted-foreground/60 select-none">
                  &gt;
                </span>
                <span className="text-muted-foreground">{line.text}</span>
              </>
            ) : (
              <>
                <span className="text-foreground/45 select-none">✓</span>
                <span className="text-foreground/75">{line.text}</span>
              </>
            )}
          </motion.div>
        ))}
      </div>
    </div>
  )
}

/* ─── Orchestrator ───────────────────────────────────────────────────────── */

type RunState = {
  activeLine: number | null
  activeIndex: number
  operationId: string
  operation: string
  details: StageDetail[]
  statusState: "idle" | "running" | "complete"
  logs: TerminalLine[]
  showComparison: boolean
  headerBadge: "running" | "completed"
}

const IDLE_DETAILS: StageDetail[] = []

const INITIAL_RUN: RunState = {
  activeLine: null,
  activeIndex: -1,
  operationId: "idle",
  operation: "Waiting",
  details: IDLE_DETAILS,
  statusState: "idle",
  logs: [],
  showComparison: false,
  headerBadge: "running",
}

const LAST_STAGE = STAGES[STAGES.length - 1]!

const COMPLETED_RUN: RunState = {
  activeLine: ACTIVE_LINE,
  activeIndex: STAGES.length,
  operationId: `${LAST_STAGE.id}-done`,
  operation: LAST_STAGE.operation,
  details: [{ label: "Memory Updated", value: "✓" }],
  statusState: "complete",
  logs: STAGES.flatMap((s) => s.logs),
  showComparison: true,
  headerBadge: "completed",
}

export function ProductPreview({ className }: { className?: string }) {
  const prefersReducedMotion = useReducedMotion()
  const ref = React.useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, amount: 0.2 })

  const [run, setRun] = React.useState<RunState>(
    prefersReducedMotion ? COMPLETED_RUN : INITIAL_RUN
  )

  React.useEffect(() => {
    if (prefersReducedMotion) {
      setRun(COMPLETED_RUN)
      return
    }

    if (!inView) return

    const timers: number[] = []
    let logs: TerminalLine[] = []

    // 1–3. Highlight SQL after window entrance.
    timers.push(
      window.setTimeout(() => {
        setRun((prev) => ({ ...prev, activeLine: ACTIVE_LINE }))
      }, SETUP_MS)
    )

    // 4–10. Stage loop: status → timeline → terminal.
    STAGES.forEach((stage, index) => {
      const at = SETUP_MS + 200 + index * STAGE_MS

      timers.push(
        window.setTimeout(() => {
          logs = [...logs, ...stage.logs]
          const nextLogs = logs

          setRun((prev) => ({
            ...prev,
            activeIndex: index,
            operationId: stage.id,
            operation: stage.operation,
            details: stage.details,
            statusState: "running",
            logs: nextLogs,
            headerBadge: "running",
          }))
        }, at)
      )

      // After Compare Prediction settles, reveal metrics.
      if (index === COMPARE_INDEX) {
        timers.push(
          window.setTimeout(() => {
            setRun((prev) => ({ ...prev, showComparison: true }))
          }, at + STAGE_MS * 0.7)
        )
      }
    })

    // 11–12. Complete — flip last operation to Success.
    const doneAt = SETUP_MS + 200 + STAGES.length * STAGE_MS
    timers.push(
      window.setTimeout(() => {
        setRun({
          activeLine: ACTIVE_LINE,
          activeIndex: STAGES.length,
          operationId: `${LAST_STAGE.id}-done`,
          operation: LAST_STAGE.operation,
          details: [{ label: "Memory Updated", value: "✓" }],
          statusState: "complete",
          logs: STAGES.flatMap((s) => s.logs),
          showComparison: true,
          headerBadge: "completed",
        })
      }, doneAt)
    )

    return () => {
      timers.forEach((id) => window.clearTimeout(id))
    }
  }, [inView, prefersReducedMotion])

  return (
    <motion.div
      ref={ref}
      className={cn("w-full", className)}
      initial={prefersReducedMotion ? false : { opacity: 0, y: 24 }}
      animate={
        inView || prefersReducedMotion
          ? { opacity: 1, y: 0 }
          : { opacity: 0, y: 24 }
      }
      transition={{ duration: 0.45, ease: easeOut }}
    >
      <Card
        aria-label="Migration Oracle product preview"
        className="border-border/60 gap-0 overflow-hidden rounded-xl py-0 shadow-none"
      >
        <div className="border-border/60 relative flex h-10 items-center border-b px-4">
          <TrafficLights />
          <span className="text-muted-foreground absolute left-1/2 -translate-x-1/2 text-xs font-medium tracking-tight">
            Migration Oracle
          </span>
        </div>

        <ExecutionStatusHeader badge={run.headerBadge} />

        <div className="grid md:grid-cols-2">
          <div className="border-border/60 md:border-r">
            <SqlEditor activeLine={run.activeLine} />
          </div>
          <ExecutionPanel
            activeIndex={run.activeIndex}
            operationId={run.operationId}
            operation={run.operation}
            statusState={run.statusState}
            details={run.details}
            showComparison={run.showComparison}
          />
        </div>

        <div className="border-border/60 border-t">
          <TerminalPanel lines={run.logs} />
        </div>
      </Card>
    </motion.div>
  )
}
