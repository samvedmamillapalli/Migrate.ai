"use client"

/**
 * Workspace design primitives, ported from the pixel-perfect design source
 * (pixel-perfect-clone-64427-main/src/components/ui-kit.tsx).
 *
 * Two deliberate departures from the source:
 *  - Colours route through the semantic --tone-* tokens instead of raw
 *    Tailwind palette classes, so every one of these renders correctly in
 *    both light and dark.
 *  - StatusPill maps the backend's real MigrationRunStatus / decision values
 *    rather than the design's invented display strings.
 */

import * as React from "react"
import { motion } from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string
  subtitle?: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="mb-6 flex flex-col items-start justify-between gap-4 sm:flex-row">
      <div className="min-w-0">
        <h1 className="text-foreground text-[28px] leading-tight font-bold tracking-[-0.02em]">
          {title}
        </h1>
        {subtitle ? (
          <p className="text-muted-foreground mt-1 text-sm">{subtitle}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}

export function Panel({
  children,
  className,
  delay = 0,
  ...rest
}: {
  children: React.ReactNode
  className?: string
  delay?: number
} & Omit<
  React.ComponentPropsWithoutRef<typeof motion.section>,
  "children" | "initial" | "animate" | "transition"
>) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, delay, ease: [0.22, 1, 0.36, 1] }}
      className={cn("border-border bg-card rounded-xl border", className)}
      {...rest}
    >
      {children}
    </motion.section>
  )
}

export function Label({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return <div className={cn("section-label", className)}>{children}</div>
}

/** Semantic tone names shared by pills, dots and callouts. */
export type Tone = "pass" | "warn" | "fail" | "info" | "model" | "neutral"

const TONE_FG: Record<Tone, string> = {
  pass: "text-[var(--tone-pass-fg)]",
  warn: "text-[var(--tone-warn-fg)]",
  fail: "text-[var(--tone-fail-fg)]",
  info: "text-[var(--tone-info-fg)]",
  model: "text-[var(--tone-model-fg)]",
  neutral: "text-muted-foreground",
}

const TONE_SURFACE: Record<Tone, string> = {
  pass: "bg-[var(--tone-pass-bg)] border-[var(--tone-pass-border)]",
  warn: "bg-[var(--tone-warn-bg)] border-[var(--tone-warn-border)]",
  fail: "bg-[var(--tone-fail-bg)] border-[var(--tone-fail-border)]",
  info: "bg-[var(--tone-info-bg)] border-[var(--tone-info-border)]",
  model: "bg-[var(--tone-model-bg)] border-[var(--tone-model-border)]",
  neutral: "bg-muted border-border",
}

const TONE_DOT: Record<Tone, string> = {
  pass: "bg-[var(--tone-pass-dot)]",
  warn: "bg-[var(--tone-warn-dot)]",
  fail: "bg-[var(--tone-fail-dot)]",
  info: "bg-[var(--tone-info-dot)]",
  model: "bg-[var(--tone-model-dot)]",
  neutral: "bg-[var(--tone-neutral-dot)]",
}

export function toneText(tone: Tone): string {
  return TONE_FG[tone]
}

export function toneSurface(tone: Tone): string {
  return TONE_SURFACE[tone]
}

export function ToneDot({
  tone,
  className,
}: {
  tone: Tone
  className?: string
}) {
  return (
    <span
      aria-hidden
      className={cn("size-1.5 shrink-0 rounded-full", TONE_DOT[tone], className)}
    />
  )
}

/**
 * Maps a real backend status to its display label + tone.
 *
 * Accepts MigrationRunStatus (pending | predicting | awaiting_approval |
 * running | completed | failed) and the approval decisions surfaced as
 * outcomes in the history table (proceed | accept_recommended | cancel).
 * Unknown values fall through to a neutral pill showing the raw value rather
 * than silently rendering something inaccurate.
 */
const STATUS_META: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "PENDING", tone: "neutral" },
  predicting: { label: "PREDICTING", tone: "model" },
  awaiting_approval: { label: "AWAITING APPROVAL", tone: "warn" },
  running: { label: "RUNNING SHADOW", tone: "info" },
  completed: { label: "COMPLETED", tone: "pass" },
  failed: { label: "FAILED", tone: "fail" },
  // Approval decisions (outcome column)
  proceed: { label: "PROCEEDED", tone: "pass" },
  accept_recommended: { label: "ACCEPTED PLAN", tone: "pass" },
  cancel: { label: "CANCELLED", tone: "fail" },
  awaiting_decision: { label: "AWAITING DECISION", tone: "warn" },
  // Shadow cluster lifecycle
  provisioning: { label: "PROVISIONING", tone: "info" },
  ready: { label: "READY", tone: "info" },
  holding: { label: "HOLDING", tone: "warn" },
  destroyed: { label: "DESTROYED", tone: "neutral" },
}

export function statusMeta(status: string | null | undefined): {
  label: string
  tone: Tone
} {
  if (!status) return { label: "—", tone: "neutral" }
  return (
    STATUS_META[status] ?? {
      label: status.replace(/_/g, " ").toUpperCase(),
      tone: "neutral",
    }
  )
}

export function StatusPill({
  status,
  className,
}: {
  status: string | null | undefined
  className?: string
}) {
  const { label, tone } = statusMeta(status)
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-bold tracking-wide",
        TONE_SURFACE[tone],
        TONE_FG[tone],
        className
      )}
    >
      <ToneDot tone={tone} />
      {label}
    </span>
  )
}

export function SqlBlock({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <pre
      className={cn(
        "text-foreground overflow-x-auto font-mono text-[13px] leading-relaxed break-words whitespace-pre-wrap",
        className
      )}
    >
      {children}
    </pre>
  )
}

/** Small labelled figure used in stat rows across the workspace. */
export function Stat({
  label,
  value,
  sub,
  valueClassName,
  className,
}: {
  label: React.ReactNode
  value: React.ReactNode
  sub?: React.ReactNode
  valueClassName?: string
  className?: string
}) {
  return (
    <div className={className}>
      <div className="section-label">{label}</div>
      <div
        className={cn(
          "text-foreground mt-1.5 text-[26px] leading-none font-bold tabular-nums",
          valueClassName
        )}
      >
        {value}
      </div>
      {sub ? (
        <div className="text-muted-foreground mt-1 text-[12px]">{sub}</div>
      ) : null}
    </div>
  )
}

/** Empty / not-yet-available state. Used instead of inventing a placeholder. */
export function EmptyNote({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <p
      className={cn(
        "text-muted-foreground text-[13px] leading-relaxed",
        className
      )}
    >
      {children}
    </p>
  )
}

export function ErrorNote({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <p
      className={cn(
        "font-mono text-[12px] leading-relaxed text-[var(--tone-fail-fg)]",
        className
      )}
    >
      {children}
    </p>
  )
}

/** A single shimmering placeholder bar. */
export function SkeletonBar({
  className,
  width,
}: {
  className?: string
  width?: string
}) {
  return (
    <span
      aria-hidden
      className={cn("bg-muted block h-3 animate-pulse rounded", className)}
      style={width ? { width } : undefined}
    />
  )
}

/**
 * Loading placeholder that keeps a panel's height while data arrives, instead
 * of collapsing to a one-line "Loading…" and then jumping.
 */
export function SkeletonLines({
  lines = 3,
  className,
}: {
  lines?: number
  className?: string
}) {
  const widths = ["82%", "64%", "73%", "55%", "78%", "60%"]
  return (
    <div className={cn("space-y-2.5", className)} role="status" aria-busy>
      <span className="sr-only">Loading…</span>
      {Array.from({ length: lines }, (_, i) => (
        <SkeletonBar key={i} width={widths[i % widths.length]} />
      ))}
    </div>
  )
}

/** Skeleton shaped like a stat tile row. */
export function SkeletonStats({
  count = 4,
  className,
}: {
  count?: number
  className?: string
}) {
  return (
    <div
      className={cn("grid grid-cols-2 gap-5 sm:grid-cols-4", className)}
      role="status"
      aria-busy
    >
      <span className="sr-only">Loading…</span>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="space-y-2">
          <SkeletonBar className="h-6" width="48%" />
          <SkeletonBar width="76%" />
          <SkeletonBar className="h-2" width="56%" />
        </div>
      ))}
    </div>
  )
}
