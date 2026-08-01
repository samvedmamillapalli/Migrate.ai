"use client"

import { cn } from "@workspace/ui/lib/utils"

import { oracleColor, oracleRadius } from "@/lib/oracle-tokens"

export type FlowLineProps = {
  orientation?: "vertical" | "horizontal"
  /** 0–1 filled length (structure track underneath) */
  className?: string
  /** Thickness in px */
  thickness?: 1 | 2
}

/**
 * Structural track for information flow.
 * Gray only — never decorative.
 */
export function FlowLine({
  orientation = "vertical",
  className,
  thickness = 2,
}: FlowLineProps) {
  const isVertical = orientation === "vertical"

  return (
    <div
      aria-hidden
      className={cn(
        oracleRadius.pill,
        oracleColor.structure.class.track,
        isVertical ? "h-full w-px self-stretch" : "h-px w-full",
        thickness === 2 && (isVertical ? "w-[2px]" : "h-[2px]"),
        className
      )}
    />
  )
}
