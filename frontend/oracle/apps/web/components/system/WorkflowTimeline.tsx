"use client"

import { motion, useReducedMotion } from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

import { AnimatedConnector } from "@/components/system/AnimatedConnector"
import { ExecutionNode } from "@/components/system/ExecutionNode"
import { ThinkingNode } from "@/components/system/ThinkingNode"
import { oracleMotion } from "@/lib/oracle-tokens"

export type WorkflowStepStatus =
  | "pending"
  | "active"
  | "completed"
  | "error"

export type WorkflowStep = {
  id: string
  title: string
  status?: WorkflowStepStatus
}

export type WorkflowTimelineProps = {
  items: WorkflowStep[]
  className?: string
  showConnectors?: boolean
  /** Spacing density — compact is default */
  variant?: "default" | "compact" | "spacious"
}

/**
 * Vertical workflow composed of ThinkingNode / ExecutionNode + AnimatedConnector.
 */
export function WorkflowTimeline({
  items,
  className,
  showConnectors = true,
  variant = "compact",
}: WorkflowTimelineProps) {
  const prefersReducedMotion = useReducedMotion()
  const itemGap = variant === "spacious" ? "pb-5" : "pb-4"

  return (
    <ol className={cn("relative flex flex-col", className)}>
      {items.map((item, index) => {
        const status = item.status ?? "pending"
        const isLast = index === items.length - 1
        const lineProgress =
          status === "completed" ? 1 : status === "active" ? 0.42 : 0
        const lineTone =
          status === "completed"
            ? "verified"
            : status === "active"
              ? "active"
              : "pending"

        return (
          <li key={item.id} className="relative flex gap-3">
            <div className="relative flex w-5 shrink-0 justify-center">
              <div className="relative z-[1]">
                {status === "active" ? (
                  <ThinkingNode active />
                ) : (
                  <ExecutionNode
                    state={
                      status === "completed"
                        ? "verified"
                        : status === "error"
                          ? "risk"
                          : "pending"
                    }
                  />
                )}
              </div>

              {showConnectors && !isLast ? (
                <div className="absolute top-[22px] bottom-0 flex justify-center">
                  <AnimatedConnector
                    progress={lineProgress}
                    tone={lineTone}
                    className="min-h-[20px]"
                  />
                </div>
              ) : null}
            </div>

            <motion.p
              className={cn(
                "text-sm leading-5 tracking-tight",
                isLast ? "pb-0" : itemGap,
                status === "pending" && "text-muted-foreground",
                status === "active" && "text-foreground font-medium",
                status === "completed" && "text-foreground font-medium",
                status === "error" && "text-foreground font-medium"
              )}
              initial={false}
              animate={{ opacity: status === "pending" ? 0.4 : 1 }}
              transition={{
                duration: prefersReducedMotion
                  ? 0
                  : oracleMotion.duration.fast,
                ease: oracleMotion.ease,
              }}
            >
              {item.title}
            </motion.p>
          </li>
        )
      })}
    </ol>
  )
}

/** Back-compat aliases for Animations/WorkflowTimeline */
export const Timeline = WorkflowTimeline
export type TimelineItem = WorkflowStep
export type TimelineItemStatus = WorkflowStepStatus
export type TimelineProps = WorkflowTimelineProps
