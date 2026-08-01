"use client"

import { motion, useReducedMotion } from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

import { oracleIcon, oracleMotion } from "@/lib/oracle-tokens"

export type ThinkingNodeProps = {
  active?: boolean
  className?: string
  label?: string
}

/**
 * Active reasoning node — monochrome emphasis only.
 */
export function ThinkingNode({
  active = true,
  className,
  label,
}: ThinkingNodeProps) {
  const prefersReducedMotion = useReducedMotion()

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <motion.span
        className={cn(
          "relative z-[1] flex size-5 shrink-0 items-center justify-center rounded-full border",
          active
            ? "border-foreground/35 bg-foreground/10 shadow-[0_0_0_3px_rgba(255,255,255,0.06)]"
            : "border-border bg-background text-muted-foreground/40"
        )}
        initial={false}
        animate={
          prefersReducedMotion || !active
            ? { scale: 1 }
            : { scale: [1, 1.06, 1] }
        }
        transition={
          active && !prefersReducedMotion
            ? { duration: 1.6, repeat: Infinity, ease: "easeInOut" }
            : { duration: oracleMotion.duration.fast, ease: oracleMotion.ease }
        }
      >
        <span className="relative flex size-2 items-center justify-center">
          {active && !prefersReducedMotion ? (
            <span className="bg-foreground/35 absolute size-2 animate-ping rounded-full" />
          ) : null}
          <span
            className={cn(
              "relative size-1.5 rounded-full",
              active ? "bg-foreground/80" : "bg-muted-foreground/40"
            )}
          />
        </span>
      </motion.span>

      {label ? (
        <span
          className={cn(
            "text-sm font-medium tracking-tight",
            active ? "text-foreground" : "text-muted-foreground"
          )}
        >
          {label}
        </span>
      ) : null}
    </div>
  )
}

export const thinkingNodeIconSize = oracleIcon.sm
