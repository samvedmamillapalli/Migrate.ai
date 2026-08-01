"use client"

import { motion, useReducedMotion } from "motion/react"
import { Check } from "lucide-react"

import { cn } from "@workspace/ui/lib/utils"

import {
  oracleIcon,
  oracleMotion,
  type OracleNodeState,
} from "@/lib/oracle-tokens"

export type ExecutionNodeProps = {
  state?: Extract<OracleNodeState, "pending" | "verified" | "risk" | "idle">
  className?: string
  label?: string
}

/**
 * Execution node — monochrome verified / pending / risk.
 */
export function ExecutionNode({
  state = "pending",
  className,
  label,
}: ExecutionNodeProps) {
  const prefersReducedMotion = useReducedMotion()
  const verified = state === "verified"
  const risk = state === "risk"

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <motion.span
        className={cn(
          "relative z-[1] flex size-5 shrink-0 items-center justify-center rounded-full border",
          verified &&
            "border-foreground/25 bg-foreground text-background",
          risk && "border-foreground/30 bg-foreground/10 text-foreground",
          !verified &&
            !risk &&
            "border-border bg-background text-muted-foreground/40"
        )}
        initial={false}
        animate={
          prefersReducedMotion
            ? { scale: 1 }
            : verified
              ? { scale: [1.08, 1] }
              : { scale: 1 }
        }
        transition={{
          duration: oracleMotion.duration.base,
          ease: oracleMotion.ease,
        }}
      >
        {verified ? (
          <Check className="size-3" strokeWidth={2.5} />
        ) : (
          <span className="bg-muted-foreground/35 size-1.5 rounded-full" />
        )}
      </motion.span>

      {label ? (
        <span
          className={cn(
            "text-sm tracking-tight",
            verified && "text-foreground font-medium",
            risk && "text-foreground font-medium",
            !verified && !risk && "text-muted-foreground"
          )}
        >
          {label}
        </span>
      ) : null}
    </div>
  )
}

export const executionNodeIconSize = oracleIcon.sm
