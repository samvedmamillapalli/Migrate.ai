"use client"

/**
 * Overview "Accuracy" panel — Grafana/Datadog-style interactive charts over
 * the accuracy metrics endpoint, rather than plain counters.
 *
 * Hand-rolled SVG (no charting dependency exists in this app yet). Categorical
 * hues (blue / orange / aqua below) are the validated reference palette from
 * the dataviz skill's palette.md, used as-is rather than derived from this
 * app's own tokens: the app only ships two non-status hues (info blue, model
 * violet) and they fail CVD separation as a pair, so there isn't enough of a
 * native categorical set to build a 3-slot palette from. Status colors
 * (pass/warn/fail/critical) are this app's own tokens, unchanged.
 */

import * as React from "react"

import {
  EmptyNote,
  Label as PanelLabel,
  type Tone,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"
import { formatDuration, formatPercent } from "@/lib/api/map-run"

// --- shared scoped theme --------------------------------------------------

/** Categorical hues borrowed from the dataviz skill's validated default
 * palette (first three all-pairs-safe slots) — see file header. */
function ChartTheme() {
  return (
    <style>{`
      .analytics-charts {
        --viz-cat-1: #2a78d6;
        --viz-cat-2: #eb6834;
        --viz-cat-3: #1baf7a;
        --viz-cat-other: #898781;
      }
      .dark .analytics-charts {
        --viz-cat-1: #3987e5;
        --viz-cat-2: #d95926;
        --viz-cat-3: #199e70;
        --viz-cat-other: #898781;
      }
      /* SVG <text> doesn't reliably inherit the app's sans font across
         browsers (SVG's own UA stylesheet can win) — set it explicitly
         once here instead of on every <text> element. */
      .analytics-charts svg text {
        font-family: var(--font-sans), ui-sans-serif, system-ui, sans-serif;
      }
    `}</style>
  )
}

/**
 * Measures a container's real rendered pixel width so an SVG's viewBox can
 * match it exactly. Without this, a fixed viewBox width (e.g. 560) rendered
 * at CSS width:100% into a wider panel stretches the X axis only —
 * `preserveAspectRatio="none"` allows exactly that non-uniform scale, which
 * is why a circular dot rendered as an ellipse and a rotated axis label
 * ("Actual") came out visibly skewed. Falls back to `fallback` until the
 * first real measurement lands, so there's no 0-width flash.
 *
 * A callback ref, not a plain ref + effect-on-mount: the loading/empty
 * states below return before the measured `<div>` ever renders, so the
 * effect's one-time mount would fire while `ref.current` is still null and
 * never re-fire once data arrives and the div finally exists. A callback
 * ref runs again on every attach, including that later one.
 */
/**
 * Same as useMeasuredWidth but also tracks height, clamped to
 * [fallbackHeight, maxHeight]. Used by the two top charts so they grow to
 * fill whatever vertical space the dashboard grid actually gives them
 * (which varies by viewport height) instead of rendering at a fixed pixel
 * height that leaves dead space below on any taller screen.
 */
function useMeasuredSize(fallbackWidth: number, fallbackHeight: number, maxHeight = 340) {
  const [width, setWidth] = React.useState(fallbackWidth)
  const [height, setHeight] = React.useState(fallbackHeight)
  const observerRef = React.useRef<ResizeObserver | null>(null)

  const containerRef = React.useCallback(
    (el: HTMLDivElement | null) => {
      observerRef.current?.disconnect()
      observerRef.current = null
      if (!el) return
      const measure = () => {
        const w = el.clientWidth
        const h = el.clientHeight
        if (w > 0) setWidth(w)
        if (h > 0) setHeight(Math.min(Math.max(h, fallbackHeight), maxHeight))
      }
      measure()
      const ro = new ResizeObserver(measure)
      ro.observe(el)
      observerRef.current = ro
    },
    [fallbackHeight, maxHeight]
  )

  return [containerRef, width, height] as const
}

const STATUS_DOT: Record<string, Tone> = {
  clean_ok: "pass",
  warned_ok: "warn",
  bad: "fail",
  timeout: "critical",
}
const STATUS_LABEL: Record<string, string> = {
  clean_ok: "Clean",
  warned_ok: "Warned",
  bad: "Bad",
  timeout: "Timeout",
}
const TONE_VAR: Record<Tone, string> = {
  pass: "var(--tone-pass-dot)",
  warn: "var(--tone-warn-dot)",
  fail: "var(--tone-fail-dot)",
  critical: "var(--tone-critical-dot)",
  info: "var(--tone-info-dot)",
  model: "var(--tone-model-dot)",
  neutral: "var(--tone-neutral-dot)",
}
const TONE_TEXT_VAR: Record<Tone, string> = {
  pass: "var(--tone-pass-fg)",
  warn: "var(--tone-warn-fg)",
  fail: "var(--tone-fail-fg)",
  critical: "var(--tone-critical-fg)",
  info: "var(--tone-info-fg)",
  model: "var(--tone-model-fg)",
  neutral: "var(--muted-foreground)",
}

function clockDate(iso: string): string {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return "—"
  return new Date(t).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  })
}

// --- tooltip ---------------------------------------------------------------

type TooltipState = {
  xPct: number
  yPct: number
  content: React.ReactNode
} | null

function ChartSurface({
  width,
  height,
  children,
  tooltip,
  className,
}: {
  width: number
  height: number
  children: React.ReactNode
  tooltip: TooltipState
  className?: string
}) {
  return (
    <div className={cn("relative", className)}>
      {/* viewBox matches the container's real measured width 1:1 (see
          useMeasuredWidth) — no preserveAspectRatio="none" needed, since
          there's no mismatch left for it to paper over. That mismatch was
          exactly what stretched circular dots into ellipses and skewed the
          rotated "Actual" axis label. */}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        className="block max-w-full overflow-visible"
      >
        {children}
      </svg>
      {tooltip ? (
        <div
          className="border-border bg-popover text-popover-foreground pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[calc(100%+10px)] rounded-lg border px-2.5 py-1.5 text-[11.5px] leading-snug whitespace-nowrap shadow-md"
          style={{ left: `${tooltip.xPct}%`, top: `${tooltip.yPct}%` }}
        >
          {tooltip.content}
        </div>
      ) : null}
    </div>
  )
}

// --- empty / skeleton state --------------------------------------------------

function ChartEmpty({
  height,
  icon,
  message,
}: {
  height: number
  icon: React.ReactNode
  message: string
}) {
  return (
    <div
     className="border-border/70 flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed" 
      style={{ height }}
    >
      <div className="text-muted-foreground/50">{icon}</div>
      <EmptyNote className="max-w-[220px] text-center">{message}</EmptyNote>
    </div>
  )
}

function SkeletonWave({ height }: { height: number }) {
  return (
    <svg
      viewBox="0 0 400 120"
      width="100%"
      height={height}
      preserveAspectRatio="none"
      aria-hidden
      className="block"
    >
      <path
        d="M0 80 C 40 60, 60 95, 100 70 S 160 40, 200 65 S 260 90, 300 55 S 360 35, 400 60"
        fill="none"
        stroke="var(--border)"
        strokeWidth={3}
        strokeLinecap="round"
        className="animate-pulse"
      />
    </svg>
  )
}

// --- 1. Line chart: accuracy over time --------------------------------------

export type AccuracyTrendPoint = {
  createdAt: string
  score: number
  scaleTier: string | null
  outcomeClass: string | null
}

export function AccuracyTrendChart({
  points,
  loading,
  height = 220,
}: {
  points: AccuracyTrendPoint[]
  loading: boolean
  height?: number
}) {
  const PAD = { top: 12, right: 8, bottom: 22, left: 30 }
  const [hover, setHover] = React.useState<number | null>(null)
  const [containerRef, W, H] = useMeasuredSize(560, height, 340)

  if (loading) {
    return (
      <div ref={containerRef} className="h-full w-full">
        <SkeletonWave height={H} />
      </div>
    )
  }
  if (points.length === 0) {
    return (
      <div ref={containerRef} className="h-full w-full">
        <ChartEmpty
          height={H}
          message="No graded runs yet. Accuracy will appear after your first migration is graded."
          icon={
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
              <path
                d="M3 17l5-5 4 4 8-9"
                stroke="currentColor"
                strokeWidth={1.6}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          }
        />
      </div>
    )
  }

  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const times = points.map((p) => Date.parse(p.createdAt))
  const tMin = Math.min(...times)
  const tMax = Math.max(...times)
  const tSpan = tMax - tMin || 1
  const x = (t: number) => PAD.left + ((t - tMin) / tSpan) * innerW
  const y = (score: number) => PAD.top + (1 - Math.max(0, Math.min(1, score))) * innerH

  const coords = points.map((p, i) => ({
    x: x(times[i]!),
    y: y(p.score),
    p,
  }))
  const linePath = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ")
  const areaPath = `${linePath} L${coords[coords.length - 1]!.x.toFixed(1)} ${PAD.top + innerH} L${coords[0]!.x.toFixed(1)} ${PAD.top + innerH} Z`

  const gridLines = [0, 0.25, 0.5, 0.75, 1]
  const active = hover != null ? coords[hover] : null
  const tooltip: TooltipState = active
    ? {
        xPct: (active.x / W) * 100,
        yPct: (active.y / H) * 100,
        content: (
          <div className="space-y-0.5">
            <div className="text-foreground font-semibold">
              {formatPercent(active.p.score)} accuracy
            </div>
            <div className="text-muted-foreground">
              {clockDate(active.p.createdAt)}
              {active.p.scaleTier ? ` · ${active.p.scaleTier}` : ""}
            </div>
          </div>
        ),
      }
    : null

  return (
    <div ref={containerRef} className="h-full w-full">
      <ChartSurface width={W} height={H} tooltip={tooltip}>
      {gridLines.map((g) => (
        <line
          key={g}
          x1={PAD.left}
          x2={W - PAD.right}
          y1={y(g)}
          y2={y(g)}
          stroke="var(--border)"
          strokeWidth={1}
        />
      ))}
      {[0, 0.5, 1].map((g) => (
        <text
          key={g}
          x={PAD.left - 6}
          y={y(g) + 3}
          textAnchor="end"
          fontSize={9.5}
          fill="var(--muted-foreground)"
        >
          {Math.round(g * 100)}%
        </text>
      ))}
      <path d={areaPath} fill="var(--viz-cat-1, var(--primary))" opacity={0.08} />
      <path
        d={linePath}
        fill="none"
        stroke="var(--primary)"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {coords.map((c, i) => (
        <circle
          key={i}
          cx={c.x}
          cy={c.y}
          r={hover === i ? 4 : 2.5}
          fill="var(--card)"
          stroke="var(--primary)"
          strokeWidth={1.6}
          className="transition-[r]"
        />
      ))}
      {/* wide invisible hit targets for hover */}
      {coords.map((c, i) => (
        <rect
          key={`hit-${i}`}
          x={i === 0 ? PAD.left : (coords[i - 1]!.x + c.x) / 2}
          y={PAD.top}
          width={
            (i === coords.length - 1
              ? W - PAD.right
              : (c.x + coords[i + 1]!.x) / 2) -
            (i === 0 ? PAD.left : (coords[i - 1]!.x + c.x) / 2)
          }
          height={innerH}
          fill="transparent"
          onMouseEnter={() => setHover(i)}
          onMouseLeave={() => setHover((h) => (h === i ? null : h))}
        />
      ))}
      <text x={PAD.left} y={H - 4} fontSize={9.5} fill="var(--muted-foreground)">
        {clockDate(points[0]!.createdAt)}
      </text>
      <text
        x={W - PAD.right}
        y={H - 4}
        textAnchor="end"
        fontSize={9.5}
        fill="var(--muted-foreground)"
      >
        {clockDate(points[points.length - 1]!.createdAt)}
      </text>
      </ChartSurface>
    </div>
  )
}

// --- 2. Scatter: predicted vs actual runtime --------------------------------

export type RuntimeScatterPoint = {
  runId: string
  predictedSeconds: number
  actualSeconds: number
  outcomeClass: string | null
}

const DURATION_TICKS = [1, 5, 30, 60, 300, 900, 3600, 14400, 86400]

export function RuntimeScatterChart({
  points,
  loading,
  height = 220,
}: {
  points: RuntimeScatterPoint[]
  loading: boolean
  height?: number
}) {
  const [containerRef, W, H] = useMeasuredSize(320, height, 340)
  const PAD = { top: 10, right: 10, bottom: 24, left: 34 }
  const [hover, setHover] = React.useState<number | null>(null)

  if (loading) {
    return (
      <div ref={containerRef} className="h-full w-full">
        <SkeletonWave height={H} />
      </div>
    )
  }
  if (points.length === 0) {
    return (
      <div ref={containerRef} className="h-full w-full">
        <ChartEmpty
          height={H}
          message="No shadow-tested migrations yet. Runtime accuracy will appear after your first shadow run completes."
          icon={
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
              <circle cx="6" cy="17" r="1.6" fill="currentColor" />
              <circle cx="11" cy="11" r="1.6" fill="currentColor" />
              <circle cx="16" cy="14" r="1.6" fill="currentColor" />
              <circle cx="19" cy="6" r="1.6" fill="currentColor" />
              <path d="M3 20L20 3" stroke="currentColor" strokeWidth={1.2} strokeDasharray="2 2" />
            </svg>
          }
        />
      </div>
    )
  }

  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const values = points.flatMap((p) => [p.predictedSeconds, p.actualSeconds]).filter((v) => v > 0)
  const vMin = Math.max(0.5, Math.min(...values) * 0.7)
  const vMax = Math.max(...values) * 1.4
  const logMin = Math.log10(vMin)
  const logMax = Math.log10(vMax)
  const logSpan = logMax - logMin || 1
  const sx = (v: number) => PAD.left + ((Math.log10(Math.max(v, 0.5)) - logMin) / logSpan) * innerW
  const sy = (v: number) => PAD.top + innerH - ((Math.log10(Math.max(v, 0.5)) - logMin) / logSpan) * innerH

  const ticks = DURATION_TICKS.filter((t) => t >= vMin && t <= vMax)
  const diagStart = Math.max(vMin, 0.5)
  const active = hover != null ? points[hover] : null
  const tooltip: TooltipState = active
    ? {
        xPct: (sx(active.predictedSeconds) / W) * 100,
        yPct: (sy(active.actualSeconds) / H) * 100,
        content: (
          <div className="space-y-0.5">
            <div className="text-foreground font-semibold">
              Predicted {formatDuration(active.predictedSeconds)}
            </div>
            <div className="text-muted-foreground">
              Actual {formatDuration(active.actualSeconds)}
              {active.outcomeClass
                ? ` · ${STATUS_LABEL[active.outcomeClass] ?? active.outcomeClass}`
                : ""}
            </div>
          </div>
        ),
      }
    : null

  return (
    <div ref={containerRef} className="h-full w-full">
      <ChartSurface width={W} height={H} tooltip={tooltip}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={sx(t)} x2={sx(t)} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--border)" strokeWidth={1} />
          <line x1={PAD.left} x2={W - PAD.right} y1={sy(t)} y2={sy(t)} stroke="var(--border)" strokeWidth={1} />
          <text x={sx(t)} y={H - PAD.bottom + 12} textAnchor="middle" fontSize={9} fill="var(--muted-foreground)">
            {formatDuration(t)}
          </text>
        </g>
      ))}
      <text
        transform={`translate(${PAD.left - 24} ${PAD.top + innerH / 2}) rotate(-90)`}
        textAnchor="middle"
        fontSize={9}
        letterSpacing="0.08em"
        fill="var(--muted-foreground)"
        style={{ textTransform: "uppercase" }}
      >
        Actual
      </text>
      <line
        x1={sx(diagStart)}
        y1={sy(diagStart)}
        x2={sx(vMax)}
        y2={sy(vMax)}
        stroke="var(--muted-foreground)"
        strokeWidth={1.4}
        strokeDasharray="3 3"
        opacity={0.6}
      />
      {points.map((p, i) => {
        const tone = p.outcomeClass ? (STATUS_DOT[p.outcomeClass] ?? "neutral") : "neutral"
        return (
          <circle
            key={p.runId}
            cx={sx(p.predictedSeconds)}
            cy={sy(p.actualSeconds)}
            r={hover === i ? 6 : 4.5}
            fill={TONE_VAR[tone]}
            fillOpacity={0.85}
            stroke="var(--card)"
            strokeWidth={1.5}
            className="cursor-pointer transition-[r]"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover((h) => (h === i ? null : h))}
          />
        )
      })}
      </ChartSurface>
    </div>
  )
}

const SCATTER_LEGEND: (keyof typeof STATUS_DOT)[] = [
  "clean_ok",
  "warned_ok",
  "bad",
  "timeout",
]

export function RuntimeScatterLegend() {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
      {SCATTER_LEGEND.map((key) => (
        <span key={key} className="flex items-center gap-1.5 text-[11px]">
          <span
            className="size-1.5 shrink-0 rounded-full"
            style={{ backgroundColor: TONE_VAR[STATUS_DOT[key] ?? "neutral"] }}
            aria-hidden
          />
          <span className="text-muted-foreground">{STATUS_LABEL[key]}</span>
        </span>
      ))}
    </div>
  )
}

// --- 3. Horizontal bar: risk level distribution ------------------------------

export type RiskLevelBucket = { level: "low" | "medium" | "high" | "critical"; count: number }

const RISK_ORDER: RiskLevelBucket["level"][] = ["low", "medium", "high", "critical"]
const RISK_TONE: Record<RiskLevelBucket["level"], Tone> = {
  low: "pass",
  medium: "warn",
  high: "fail",
  critical: "critical",
}
const RISK_LABEL: Record<RiskLevelBucket["level"], string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
}

export function RiskLevelBarChart({
  buckets,
  loading,
  compact = false,
}: {
  buckets: RiskLevelBucket[]
  loading: boolean
  compact?: boolean
}) {
  const rowH = compact ? 18 : 30
  const H = rowH * 4 + 8
  const barH = compact ? "h-3" : "h-6"
  const [hover, setHover] = React.useState<number | null>(null)

  if (loading) {
    return (
      <div className="space-y-2.5" style={{ minHeight: H }}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className={cn("bg-muted animate-pulse rounded", barH)} style={{ width: `${70 - i * 12}%` }} />
        ))}
      </div>
    )
  }

  const byLevel = new Map(buckets.map((b) => [b.level, b.count]))
  const total = buckets.reduce((sum, b) => sum + b.count, 0)
  if (total === 0) {
    return (
      <ChartEmpty
        height={H}
        message="No risk assessments yet. Low/Medium/High/Critical severities will appear here once migrations are analyzed."
        icon={
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
            <path d="M4 20h4v-6H4v6zm6 0h4V9h-4v11zm6 0h4V4h-4v16z" stroke="currentColor" strokeWidth={1.4} strokeLinejoin="round" />
          </svg>
        }
      />
    )
  }
  const max = Math.max(...RISK_ORDER.map((l) => byLevel.get(l) ?? 0), 1)

  return (
    <div className={cn(compact ? "space-y-1" : "space-y-2.5")}>
      {RISK_ORDER.map((level, i) => {
        const count = byLevel.get(level) ?? 0
        const pct = count / max
        const share = total > 0 ? count / total : 0
        const tone = RISK_TONE[level]
        return (
          <div
            key={level}
            className="group flex items-center gap-3"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover((h) => (h === i ? null : h))}
          >
            <div className="flex w-16 shrink-0 items-center gap-1.5">
              <span
                className="size-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: TONE_VAR[tone] }}
                aria-hidden
              />
              <span className="text-foreground text-[12px] font-semibold">{RISK_LABEL[level]}</span>
            </div>
            <div className={cn("bg-muted relative min-w-0 flex-1 overflow-hidden rounded-md", barH)}>
              <div
                className={cn(
                  "h-full rounded-md transition-[width] duration-300",
                  hover === i ? "opacity-100" : "opacity-90"
                )}
                style={{
                  width: `${Math.max(pct * 100, count > 0 ? 3 : 0)}%`,
                  backgroundColor: TONE_VAR[tone],
                }}
              />
            </div>
            <div className="w-16 shrink-0 text-right">
              <span className="text-foreground text-[12.5px] font-bold tabular-nums">{count}</span>
              {hover === i && total > 0 ? (
                <span
                  className="ml-1.5 text-[11px] tabular-nums"
                  style={{ color: TONE_TEXT_VAR[tone] }}
                >
                  {formatPercent(share)}
                </span>
              ) : null}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// --- 4. Horizontal bar: approval decisions -----------------------------------

export type ApprovalDecisionBucket = {
  decision: "proceed" | "accept_recommended" | "cancel" | "awaiting_decision"
  count: number
}

const APPROVAL_ORDER: ApprovalDecisionBucket["decision"][] = [
  "proceed",
  "accept_recommended",
  "cancel",
  "awaiting_decision",
]
const APPROVAL_TONE: Record<ApprovalDecisionBucket["decision"], Tone> = {
  proceed: "pass",
  accept_recommended: "info",
  cancel: "fail",
  awaiting_decision: "warn",
}
const APPROVAL_LABEL: Record<ApprovalDecisionBucket["decision"], string> = {
  proceed: "Proceeded",
  accept_recommended: "Accepted Plan",
  cancel: "Cancelled",
  awaiting_decision: "No Decision Yet",
}
// Same wording as the counter card this chart replaces — "No Decision Yet"
// is deliberately not called "Awaiting Decision": it counts every run
// without an approval row, including ones still being set up or predicted.
const APPROVAL_HELP: Record<ApprovalDecisionBucket["decision"], string> = {
  proceed: "Approved and sent to a shadow test.",
  accept_recommended: "Plan accepted without running a shadow test.",
  cancel: "Rejected by a reviewer.",
  awaiting_decision:
    "Every run with no decision recorded, including ones still being set up or predicted.",
}

export function ApprovalDecisionChart({
  buckets,
  loading,
  compact = false,
}: {
  buckets: ApprovalDecisionBucket[]
  loading: boolean
  compact?: boolean
}) {
  const rowH = compact ? 18 : 30
  const H = rowH * 4 + 8
  const labelW = compact ? 118 : 140
  const barH = compact ? "h-3" : "h-6"
  const [hover, setHover] = React.useState<number | null>(null)

  if (loading) {
    return (
      <div className="space-y-2.5" style={{ minHeight: H }}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className={cn("bg-muted animate-pulse rounded", barH)} style={{ width: `${70 - i * 12}%` }} />
        ))}
      </div>
    )
  }

  const byDecision = new Map(buckets.map((b) => [b.decision, b.count]))
  const total = buckets.reduce((sum, b) => sum + b.count, 0)
  if (total === 0) {
    return (
      <ChartEmpty
        height={H}
        message="No approval decisions recorded yet. Proceed, accept-plan, and cancel outcomes will appear here."
        icon={
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
            <rect x="3.5" y="3.5" width="17" height="17" rx="3" stroke="currentColor" strokeWidth={1.4} />
            <path d="M8 12l2.5 2.5L16 9" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        }
      />
    )
  }
  const max = Math.max(...APPROVAL_ORDER.map((d) => byDecision.get(d) ?? 0), 1)

  return (
    <div className={cn(compact ? "space-y-1" : "space-y-2.5")}>
      {APPROVAL_ORDER.map((decision, i) => {
        const count = byDecision.get(decision) ?? 0
        const pct = count / max
        const share = total > 0 ? count / total : 0
        const tone = APPROVAL_TONE[decision]
        return (
          <div
            key={decision}
            className="group relative flex items-center gap-3"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover((h) => (h === i ? null : h))}
          >
            <div
              className="flex shrink-0 items-center gap-1.5"
              style={{ width: labelW }}
            >
              <span
                className="size-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: TONE_VAR[tone] }}
                aria-hidden
              />
              <span className="text-foreground text-[12px] font-semibold whitespace-nowrap">
                {APPROVAL_LABEL[decision]}
              </span>
            </div>
            <div className={cn("bg-muted relative min-w-0 flex-1 overflow-hidden rounded-md", barH)}>
              <div
                className={cn(
                  "h-full rounded-md transition-[width] duration-300",
                  hover === i ? "opacity-100" : "opacity-90"
                )}
                style={{
                  width: `${Math.max(pct * 100, count > 0 ? 3 : 0)}%`,
                  backgroundColor: TONE_VAR[tone],
                }}
              />
            </div>
            <div className="w-8 shrink-0 text-right">
              <span className="text-foreground text-[12.5px] font-bold tabular-nums">{count}</span>
            </div>
            {hover === i ? (
              <div
                className="border-border bg-popover text-popover-foreground pointer-events-none absolute top-0 z-10 max-w-[240px] -translate-y-[calc(100%+8px)] rounded-lg border px-2.5 py-1.5 text-[11.5px] leading-snug shadow-md"
                style={{ left: labelW }}
              >
                <div className="font-semibold" style={{ color: TONE_TEXT_VAR[tone] }}>
                  {count} · {formatPercent(share)}
                </div>
                <div className="text-muted-foreground mt-0.5">{APPROVAL_HELP[decision]}</div>
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

// --- panel wrapper -----------------------------------------------------------

export function AnalyticsChartHeader({ children }: { children: React.ReactNode }) {
  return <PanelLabel className="mb-1.5">{children}</PanelLabel>
}

export { ChartTheme }
