"use client"

import { motion, useReducedMotion } from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

import { oracleMotion, oracleType } from "@/lib/oracle-tokens"

export type TerminalLine = {
  kind: "prompt" | "ok" | "warn" | "error"
  text: string
}

export type TerminalStreamProps = {
  lines: TerminalLine[]
  className?: string
}

/**
 * Append-only log stream — GitHub Actions / Docker style.
 * Lines appear as state advances; no fake typing glitter.
 */
export function TerminalStream({ lines, className }: TerminalStreamProps) {
  const prefersReducedMotion = useReducedMotion()

  return (
    <div
      className={cn(
        "font-mono min-h-[7.5rem] space-y-1 px-5 py-4 text-[12px] leading-[1.7] sm:px-6 sm:text-[12.5px]",
        className
      )}
    >
      {lines.map((line, index) => (
        <motion.div
          key={`${index}-${line.kind}-${line.text}`}
          className="flex gap-2.5"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 3 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: oracleMotion.duration.fast,
            ease: oracleMotion.ease,
          }}
        >
          <Prefix kind={line.kind} />
          <span
            className={cn(
              line.kind === "prompt" && "text-muted-foreground",
              line.kind === "ok" && "text-foreground/75",
              line.kind === "warn" && "text-foreground/80",
              line.kind === "error" && "text-red-400/90"
            )}
          >
            {line.text}
          </span>
        </motion.div>
      ))}
    </div>
  )
}

function Prefix({ kind }: { kind: TerminalLine["kind"] }) {
  if (kind === "prompt") {
    return (
      <span className="text-muted-foreground/60 select-none">&gt;</span>
    )
  }
  if (kind === "error") {
    return <span className="text-red-400/80 select-none">×</span>
  }
  if (kind === "warn") {
    return <span className="text-muted-foreground select-none">!</span>
  }
  return <span className="text-foreground/45 select-none">✓</span>
}

export const terminalMonoClass = oracleType.monoSm
