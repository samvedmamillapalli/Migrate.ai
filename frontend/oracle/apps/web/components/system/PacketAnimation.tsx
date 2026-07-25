"use client"

import { motion, useReducedMotion } from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

import { oracleColor, oracleRadius } from "@/lib/oracle-tokens"

export type PacketAnimationProps = {
  /** When true, packet travels along the track */
  active?: boolean
  orientation?: "vertical" | "horizontal"
  className?: string
  /** Loop while active (default true for continuous flow) */
  loop?: boolean
}

/**
 * Single information packet moving along a flow track.
 * Represents data in transit — not decoration.
 */
export function PacketAnimation({
  active = true,
  orientation = "vertical",
  className,
  loop = true,
}: PacketAnimationProps) {
  const prefersReducedMotion = useReducedMotion()
  const isVertical = orientation === "vertical"

  if (!active || prefersReducedMotion) {
    return (
      <div
        aria-hidden
        className={cn(
          "relative",
          isVertical ? "h-16 w-[2px]" : "h-[2px] w-16",
          oracleColor.structure.class.track,
          oracleRadius.pill,
          className
        )}
      />
    )
  }

  return (
    <div
      aria-hidden
      className={cn(
        "relative overflow-hidden",
        isVertical ? "h-16 w-[2px]" : "h-[2px] w-16",
        oracleColor.structure.class.track,
        oracleRadius.pill,
        className
      )}
    >
      <motion.span
        className={cn(
          "absolute rounded-full",
          isVertical
            ? "left-1/2 h-2 w-2 -translate-x-1/2"
            : "top-1/2 h-2 w-2 -translate-y-1/2",
          "bg-foreground/55"
        )}
        initial={isVertical ? { top: "0%" } : { left: "0%" }}
        animate={
          isVertical ? { top: ["0%", "100%"] } : { left: ["0%", "100%"] }
        }
        transition={{
          duration: 1.8,
          ease: "linear",
          repeat: loop ? Infinity : 0,
          repeatDelay: 0.35,
        }}
      />
    </div>
  )
}
