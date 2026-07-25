"use client"

import { AnimatePresence, motion, useReducedMotion } from "motion/react"
import { Check } from "lucide-react"

import { cn } from "@workspace/ui/lib/utils"

import { oracleMotion, oracleRadius, oracleType } from "@/lib/oracle-tokens"

export type StatusTransitionState = "idle" | "running" | "complete"

export type StatusDetail = {
  label: string
  value: string
}

export type StatusTransitionProps = {
  operationId: string
  operation: string
  status: StatusTransitionState
  details?: StatusDetail[]
  className?: string
}

const STATUS_LABEL: Record<StatusTransitionState, string> = {
  idle: "Idle",
  running: "Running",
  complete: "Success",
}

/**
 * Crossfading status surface — monochrome state emphasis.
 */
export function StatusTransition({
  operationId,
  operation,
  status,
  details = [],
  className,
}: StatusTransitionProps) {
  const prefersReducedMotion = useReducedMotion()

  return (
    <motion.div
      layout
      className={cn(
        "overflow-hidden border transition-colors duration-300",
        oracleRadius.surface,
        status === "running" && "border-foreground/20 bg-foreground/5",
        status === "complete" && "border-foreground/15 bg-muted/20",
        status === "idle" && "border-border/50 bg-muted/15",
        className
      )}
      transition={{
        layout: {
          duration: oracleMotion.duration.base,
          ease: oracleMotion.ease,
        },
      }}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={operationId}
          className="px-3.5 py-3"
          initial={
            prefersReducedMotion
              ? false
              : { opacity: 0, y: 8, filter: "blur(4px)" }
          }
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          exit={
            prefersReducedMotion
              ? undefined
              : { opacity: 0, y: -6, filter: "blur(4px)" }
          }
          transition={{
            duration: oracleMotion.duration.base,
            ease: oracleMotion.ease,
          }}
        >
          <p className="text-foreground text-sm font-medium tracking-tight">
            {operation}
          </p>

          <p
            className={cn(
              "mt-1.5 flex items-center gap-2",
              oracleType.label
            )}
          >
            <StatusDot status={status} />
            <span>
              Status:{" "}
              <span
                className={cn(
                  "font-medium",
                  status === "idle"
                    ? "text-muted-foreground"
                    : "text-foreground/85"
                )}
              >
                {STATUS_LABEL[status]}
              </span>
            </span>
          </p>

          <ProgressTrack status={status} reduced={!!prefersReducedMotion} />

          {details.length > 0 ? (
            <motion.dl
              className="mt-3 grid gap-1.5"
              initial={prefersReducedMotion ? false : { opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                delay: 0.06,
                duration: oracleMotion.duration.fast,
                ease: oracleMotion.ease,
              }}
            >
              {details.map((detail) => (
                <div
                  key={detail.label}
                  className="flex items-baseline justify-between gap-3 text-xs"
                >
                  <dt className="text-muted-foreground shrink-0">
                    {detail.label}
                  </dt>
                  <dd className="text-foreground/90 font-mono text-right tracking-tight">
                    {detail.value}
                  </dd>
                </div>
              ))}
            </motion.dl>
          ) : null}
        </motion.div>
      </AnimatePresence>
    </motion.div>
  )
}

function StatusDot({ status }: { status: StatusTransitionState }) {
  if (status === "complete") {
    return (
      <span className="bg-foreground/10 text-foreground inline-flex size-3.5 items-center justify-center rounded-full">
        <Check className="size-2.5" strokeWidth={3} />
      </span>
    )
  }

  if (status === "running") {
    return (
      <span className="relative flex size-3.5 items-center justify-center">
        <span className="bg-foreground/30 absolute size-3.5 animate-ping rounded-full opacity-40" />
        <span className="bg-foreground/70 relative size-1.5 rounded-full" />
      </span>
    )
  }

  return <span className="bg-muted-foreground/40 size-1.5 rounded-full" />
}

function ProgressTrack({
  status,
  reduced,
}: {
  status: StatusTransitionState
  reduced: boolean
}) {
  return (
    <div className="bg-border/60 mt-3 h-1 overflow-hidden rounded-full">
      {status === "running" ? (
        reduced ? (
          <div className="bg-foreground/45 h-full w-1/2 rounded-full" />
        ) : (
          <motion.div
            className="bg-foreground/50 h-full w-1/3 rounded-full"
            animate={{ x: ["-120%", "320%"] }}
            transition={{
              duration: 1.4,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          />
        )
      ) : (
        <motion.div
          className={cn(
            "h-full rounded-full",
            status === "complete" ? "bg-foreground/40" : "bg-muted-foreground/25"
          )}
          initial={false}
          animate={{
            width: status === "complete" ? "100%" : "0%",
            opacity: status === "idle" ? 0.35 : 1,
          }}
          transition={{
            duration: oracleMotion.duration.slow,
            ease: oracleMotion.ease,
          }}
        />
      )}
    </div>
  )
}

export default StatusTransition

export const SystemStatusBlock = StatusTransition
export type SystemStatusBlockProps = StatusTransitionProps
export type SystemStatusState = StatusTransitionState
export type SystemStatusDetail = StatusDetail
