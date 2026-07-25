"use client"

import { motion, useReducedMotion } from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

import {
  oracleColor,
  oracleMotion,
  oracleRadius,
  type OracleNodeState,
} from "@/lib/oracle-tokens"

export type AnimatedConnectorProps = {
  progress: number
  tone?: Extract<OracleNodeState, "pending" | "active" | "verified" | "risk">
  orientation?: "vertical" | "horizontal"
  className?: string
}

/** Monochrome fills — structure for pending, foreground for progress. */
const FILL: Record<NonNullable<AnimatedConnectorProps["tone"]>, string> = {
  pending: oracleColor.structure.class.track,
  active: "bg-foreground/45",
  verified: "bg-foreground/35",
  risk: "bg-foreground/35",
}

/**
 * Growing connector — fill length = real progress between nodes.
 */
export function AnimatedConnector({
  progress,
  tone = "verified",
  orientation = "vertical",
  className,
}: AnimatedConnectorProps) {
  const prefersReducedMotion = useReducedMotion()
  const clamped = Math.max(0, Math.min(1, progress))
  const isVertical = orientation === "vertical"

  return (
    <div
      aria-hidden
      className={cn(
        "relative overflow-hidden",
        oracleRadius.pill,
        oracleColor.structure.class.track,
        isVertical ? "h-full w-[2px]" : "h-[2px] w-full",
        className
      )}
    >
      <motion.span
        className={cn(
          "absolute",
          isVertical
            ? "inset-x-0 top-0 h-full w-[2px] origin-top"
            : "inset-y-0 left-0 h-[2px] w-full origin-left",
          FILL[tone]
        )}
        initial={false}
        animate={isVertical ? { scaleY: clamped } : { scaleX: clamped }}
        transition={{
          duration: prefersReducedMotion ? 0 : oracleMotion.duration.slow,
          ease: oracleMotion.ease,
        }}
      />
    </div>
  )
}
