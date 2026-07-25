"use client"

import * as React from "react"
import { motion } from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

type LinePart = {
  text: string
  tone: "command" | "check" | "secondary" | "value" | "file"
}

type TerminalLine = {
  time: string
  parts: LinePart[]
}

const BOOT_LINES: TerminalLine[] = [
  {
    time: "09:42:11.241",
    parts: [
      { text: "> ", tone: "command" },
      { text: "loading ", tone: "secondary" },
      { text: "migration.sql", tone: "file" },
    ],
  },
  {
    time: "09:42:11.698",
    parts: [
      { text: "✓ ", tone: "check" },
      { text: "schema analyzed", tone: "secondary" },
    ],
  },
  {
    time: "09:42:12.044",
    parts: [
      { text: "✓ ", tone: "check" },
      { text: "estimated runtime: ", tone: "secondary" },
      { text: "3.8s", tone: "value" },
    ],
  },
  {
    time: "09:42:12.971",
    parts: [
      { text: "✓ ", tone: "check" },
      { text: "rollback risk: low", tone: "secondary" },
    ],
  },
  {
    time: "09:42:13.418",
    parts: [
      { text: "✓ ", tone: "check" },
      { text: "provisioning shadow cluster", tone: "secondary" },
    ],
  },
  {
    time: "09:42:16.882",
    parts: [
      { text: "✓ ", tone: "check" },
      { text: "shadow execution completed", tone: "secondary" },
    ],
  },
  {
    time: "09:42:17.156",
    parts: [
      { text: "✓ ", tone: "check" },
      { text: "prediction accuracy: ", tone: "secondary" },
      { text: "98%", tone: "value" },
    ],
  },
  {
    time: "09:42:17.603",
    parts: [
      { text: "✓ ", tone: "check" },
      { text: "learned outcome stored", tone: "secondary" },
    ],
  },
]

const WAITING_LINE: TerminalLine = {
  time: "09:42:18.091",
  parts: [
    { text: "> ", tone: "command" },
    { text: "waiting for next migration...", tone: "secondary" },
  ],
}

const LINE_DELAYS_MS = [95, 75, 100, 70, 90, 95, 80, 85] as const
const INITIAL_DELAY_MS = 120
const IDLE_GAP_MIN_MS = 5500
const IDLE_GAP_MAX_MS = 8000

const TONE_CLASS: Record<LinePart["tone"], string> = {
  command: "text-zinc-50",
  check: "text-emerald-500/60",
  secondary: "text-zinc-400",
  value: "text-zinc-50",
  file: "text-violet-400/65",
}

function formatClock(totalSeconds: number, ms: number) {
  const minutes = 42 + Math.floor(totalSeconds / 60)
  const secs = totalSeconds % 60
  return `09:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(ms).padStart(3, "0")}`
}

function buildIdleLines(cycle: number): TerminalLine[] {
  const base = 28 + cycle * 10
  return [
    {
      time: formatClock(base, 12),
      parts: [
        { text: "> ", tone: "command" },
        { text: "monitoring cluster...", tone: "secondary" },
      ],
    },
    {
      time: formatClock(base, 331),
      parts: [
        { text: "✓ ", tone: "check" },
        { text: "no pending migrations", tone: "secondary" },
      ],
    },
  ]
}

function waitingLineForCycle(cycle: number): TerminalLine {
  if (cycle === 0) return WAITING_LINE
  return {
    time: formatClock(29 + (cycle - 1) * 10, 104),
    parts: WAITING_LINE.parts,
  }
}

function TerminalRow({
  line,
  animate,
}: {
  line: TerminalLine
  animate?: boolean
}) {
  const content = (
    <>
      <span className="w-[7.5rem] shrink-0 text-zinc-500 tabular-nums">
        {line.time}
      </span>
      <span className="min-w-0">
        {line.parts.map((part, partIndex) => (
          <span key={partIndex} className={TONE_CLASS[part.tone]}>
            {part.text}
          </span>
        ))}
      </span>
    </>
  )

  if (!animate) {
    return <p className="m-0 flex gap-3">{content}</p>
  }

  return (
    <motion.p
      initial={{ opacity: 0, y: 1 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="m-0 flex gap-3"
    >
      {content}
    </motion.p>
  )
}

function WaitingRow({ line }: { line: TerminalLine }) {
  return (
    <motion.p
      initial={{ opacity: 0, y: 1 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15, ease: "easeOut" }}
      className="m-0 flex gap-3"
    >
      <span className="w-[7.5rem] shrink-0 text-zinc-500 tabular-nums">
        {line.time}
      </span>
      <span className="min-w-0">
        <span className={TONE_CLASS.command}>{"> "}</span>
        <motion.span
          className="text-zinc-400"
          animate={{ opacity: [1, 0.35, 0.85, 0.4, 1] }}
          transition={{
            duration: 2.4,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        >
          waiting for next migration...
        </motion.span>
      </span>
    </motion.p>
  )
}

function BlinkingCursor() {
  return (
    <p className="m-0 flex gap-3">
      <span className="w-[7.5rem] shrink-0" />
      <motion.span
        className="inline-block text-[12px] leading-none text-zinc-400"
        animate={{ opacity: [1, 1, 0, 0] }}
        transition={{
          duration: 1.05,
          repeat: Infinity,
          ease: "linear",
          times: [0, 0.46, 0.54, 1],
        }}
      >
        ▌
      </motion.span>
    </p>
  )
}

type Phase = "boot" | "waiting" | "idle"

export function AuthTerminalPreview({
  className,
}: {
  className?: string
}) {
  const [bootCount, setBootCount] = React.useState(0)
  const [phase, setPhase] = React.useState<Phase>("boot")
  const [idleCount, setIdleCount] = React.useState(0)
  const [idleCycle, setIdleCycle] = React.useState(0)
  const idleLines = React.useMemo(() => buildIdleLines(idleCycle), [idleCycle])

  React.useEffect(() => {
    if (phase !== "boot") return
    if (bootCount >= BOOT_LINES.length) {
      const timer = window.setTimeout(() => setPhase("waiting"), 80)
      return () => window.clearTimeout(timer)
    }

    const delay =
      bootCount === 0 ? INITIAL_DELAY_MS : LINE_DELAYS_MS[bootCount - 1] ?? 80
    const timer = window.setTimeout(() => {
      setBootCount((count) => count + 1)
    }, delay)

    return () => window.clearTimeout(timer)
  }, [phase, bootCount])

  React.useEffect(() => {
    if (phase !== "waiting") return

    const gap =
      IDLE_GAP_MIN_MS +
      Math.floor(Math.random() * (IDLE_GAP_MAX_MS - IDLE_GAP_MIN_MS))
    const timer = window.setTimeout(() => {
      setIdleCount(0)
      setPhase("idle")
    }, gap)

    return () => window.clearTimeout(timer)
  }, [phase, idleCycle])

  React.useEffect(() => {
    if (phase !== "idle") return

    if (idleCount >= idleLines.length) {
      const timer = window.setTimeout(() => {
        setIdleCycle((cycle) => cycle + 1)
        setPhase("waiting")
      }, 700)
      return () => window.clearTimeout(timer)
    }

    const delay = idleCount === 0 ? 60 : 110
    const timer = window.setTimeout(() => {
      setIdleCount((count) => count + 1)
    }, delay)

    return () => window.clearTimeout(timer)
  }, [phase, idleCount, idleLines.length])

  const showWaiting = phase === "waiting"
  const showIdle = phase === "idle"
  const showCursor =
    phase === "waiting" || (phase === "idle" && idleCount >= idleLines.length)
  const waitingLine = waitingLineForCycle(idleCycle)

  return (
    <div
      aria-hidden
      className={cn(
        "flex h-full w-full items-center justify-start py-8 pl-3 pr-10 md:pl-4 md:pr-12",
        className
      )}
    >
      <div
        className={cn(
          "w-full max-w-[540px] overflow-hidden rounded-xl",
          "border border-white/[0.08] bg-zinc-950"
        )}
      >
        <div className="grid grid-cols-[6.75rem_1fr_6.75rem] items-center border-b border-white/[0.06] px-3.5 py-3">
          <div className="flex items-center gap-[5px]">
            <span className="size-2.5 rounded-full bg-[#FF5F57]/85" />
            <span className="size-2.5 rounded-full bg-[#FEBC2E]/85" />
            <span className="size-2.5 rounded-full bg-[#28C840]/85" />
          </div>

          <span className="truncate text-center font-mono text-[11px] tracking-tight text-zinc-500">
            shadow-execution.log
          </span>

          <div className="flex items-center justify-end gap-1.5">
            <span className="size-1.5 rounded-full bg-emerald-500/65" />
            <span className="font-mono text-[10px] tracking-tight text-zinc-500">
              Shadow Ready
            </span>
          </div>
        </div>

        <div className="min-h-[320px] space-y-1.5 p-4 font-mono text-[12px] leading-[1.72] tracking-tight">
          {BOOT_LINES.slice(0, bootCount).map((line, index) => (
            <TerminalRow
              key={`boot-${index}`}
              line={line}
              animate={index === bootCount - 1 && phase === "boot"}
            />
          ))}

          {showWaiting ? (
            <>
              <WaitingRow line={waitingLine} />
              <BlinkingCursor />
            </>
          ) : null}

          {showIdle ? (
            <>
              {idleLines.slice(0, idleCount).map((line, index) => (
                <TerminalRow
                  key={`idle-${idleCycle}-${index}`}
                  line={line}
                  animate={index === idleCount - 1}
                />
              ))}
              {showCursor ? <BlinkingCursor /> : null}
            </>
          ) : null}
        </div>
      </div>
    </div>
  )
}
