"use client"

import { motion, useReducedMotion } from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

import { MetricRow } from "@/components/system/MetricRow"
import { oracleMotion, oracleType } from "@/lib/oracle-tokens"

export type ComparisonMetric = {
  label: string
  predicted: string
  actual: string
  delta: string
}

export type PredictionComparisonProps = {
  metrics: ComparisonMetric[]
  /** Extra facts (rollback risk, confidence) — not forced into predicted/actual */
  facts?: { label: string; value: string }[]
  visible?: boolean
  className?: string
  title?: string
}

/**
 * Prediction vs Reality block — whitespace over borders.
 */
export function PredictionComparison({
  metrics,
  facts = [],
  visible = true,
  className,
  title = "Prediction vs Reality",
}: PredictionComparisonProps) {
  const prefersReducedMotion = useReducedMotion()

  return (
    <motion.div
      className={cn("flex flex-col gap-7", className)}
      initial={prefersReducedMotion ? false : { opacity: 0, y: 8 }}
      animate={
        visible || prefersReducedMotion
          ? { opacity: 1, y: 0 }
          : { opacity: 0, y: 8 }
      }
      transition={{
        duration: oracleMotion.duration.base,
        ease: oracleMotion.ease,
      }}
    >
      <p className={oracleType.label}>{title}</p>

      <div className="flex flex-col gap-6">
        {metrics.map((row) => (
          <MetricRow
            key={row.label}
            label={row.label}
            predicted={row.predicted}
            actual={row.actual}
            delta={row.delta}
          />
        ))}

        {facts.length > 0 ? (
          <div className="grid grid-cols-2 gap-6">
            {facts.map((fact) => (
              <div key={fact.label} className="space-y-1">
                <p className={oracleType.label}>{fact.label}</p>
                <p className="text-foreground text-sm font-medium tracking-tight">
                  {fact.value}
                </p>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </motion.div>
  )
}
