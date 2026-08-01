"use client"

import * as React from "react"
import { motion, useReducedMotion } from "motion/react"

import { AnimatedBeam } from "@/components/ui/animated-beam"
import { Badge } from "@workspace/ui/components/badge"
import { cn } from "@workspace/ui/lib/utils"

/**
 * In-dashboard execution ribbon — lives inside the app chrome.
 * Feels like a live deployment header, not a landing-page diagram.
 */
export function ExecutionStatusHeader({
  badge,
}: {
  badge: "running" | "completed"
}) {
  const prefersReducedMotion = useReducedMotion()
  const containerRef = React.useRef<HTMLDivElement>(null)
  const fromRef = React.useRef<HTMLSpanElement>(null)
  const midRef = React.useRef<HTMLSpanElement>(null)
  const toRef = React.useRef<HTMLSpanElement>(null)
  const [shadowLit, setShadowLit] = React.useState(false)

  React.useEffect(() => {
    if (prefersReducedMotion) {
      setShadowLit(badge === "completed")
      return
    }

    let cancelled = false
    let timers: number[] = []

    const runCycle = () => {
      if (cancelled) return
      timers.forEach((id) => window.clearTimeout(id))
      timers = []
      setShadowLit(false)

      // Beam segment ~3.5s; light Shadow as the packet arrives.
      timers.push(
        window.setTimeout(() => {
          if (!cancelled) setShadowLit(true)
        }, 3200)
      )
      timers.push(
        window.setTimeout(() => {
          if (!cancelled) setShadowLit(false)
        }, 5200)
      )
      timers.push(window.setTimeout(runCycle, 7800))
    }

    runCycle()

    return () => {
      cancelled = true
      timers.forEach((id) => window.clearTimeout(id))
    }
  }, [prefersReducedMotion, badge])

  return (
    <div className="border-border/60 border-b px-5 py-3.5 sm:px-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-foreground min-w-0 truncate font-mono text-sm font-medium tracking-tight">
          migration_2026_07_22.sql
        </p>
        <div className="flex shrink-0 items-center gap-2.5">
          <Badge variant="secondary">
            {badge === "completed" ? "Completed" : "Running"}
          </Badge>
          <span className="text-muted-foreground text-xs">2 min ago</span>
        </div>
      </div>

      <div
        ref={containerRef}
        className="relative mt-3 flex h-5 items-center justify-between"
      >
        {/* Quiet baseline track — reads as one ribbon, not discrete steps */}
        <div
          aria-hidden
          className="bg-border/50 absolute top-1/2 right-[4.75rem] left-[4.25rem] h-px -translate-y-1/2 sm:right-[5.5rem] sm:left-[5rem]"
        />

        <span
          ref={fromRef}
          className="text-muted-foreground relative z-[1] bg-card pr-2 text-[11px] tracking-tight"
        >
          PostgreSQL
        </span>

        <span
          ref={midRef}
          className={cn(
            "relative z-[1] bg-card px-2 text-[11px] tracking-tight transition-colors duration-500",
            shadowLit ? "text-violet-300" : "text-muted-foreground"
          )}
        >
          Shadow
          {shadowLit && !prefersReducedMotion ? (
            <motion.span
              aria-hidden
              className="absolute -top-0.5 -right-0.5 size-1 rounded-full bg-violet-400/80"
              initial={{ opacity: 0, scale: 0.6 }}
              animate={{ opacity: [0.4, 1, 0.4], scale: 1 }}
              transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
            />
          ) : null}
        </span>

        <span
          ref={toRef}
          className="text-muted-foreground relative z-[1] bg-card pl-2 text-[11px] tracking-tight"
        >
          CockroachDB
        </span>

        {!prefersReducedMotion ? (
          <>
            <AnimatedBeam
              containerRef={containerRef}
              fromRef={fromRef}
              toRef={midRef}
              curvature={0}
              pathWidth={1}
              pathOpacity={0.12}
              pathColor="rgb(82 82 91)"
              gradientStartColor="#ddd6fe"
              gradientStopColor="#8b5cf6"
              duration={3.5}
              delay={0}
              startXOffset={18}
              endXOffset={-14}
            />
            <AnimatedBeam
              containerRef={containerRef}
              fromRef={midRef}
              toRef={toRef}
              curvature={0}
              pathWidth={1}
              pathOpacity={0.12}
              pathColor="rgb(82 82 91)"
              gradientStartColor="#ddd6fe"
              gradientStopColor="#8b5cf6"
              duration={3.5}
              delay={3.6}
              startXOffset={14}
              endXOffset={-18}
            />
          </>
        ) : null}
      </div>
    </div>
  )
}
