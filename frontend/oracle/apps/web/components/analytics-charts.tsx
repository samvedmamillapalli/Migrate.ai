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
    `}</style>
  )
}

const CAT_COLORS = ["var(--viz-cat-1)", "var(--viz-cat-2)", "var(--viz-cat-3)"]
const CAT_OTHER = "var(--viz-cat-other)"

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

function formatMigrationType(raw: string): string {
  const spaced = raw
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .trim()
  if (!spaced) return "Unknown"
  return spaced
    .split(" ")
    .filter(Boolean)
    .map((w) => w[0]!.toUpperCase() + w.slice(1).toLowerCase())
    .join(" ")
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
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        className="block overflow-visible"
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
}: {
  points: AccuracyTrendPoint[]
  loading: boolean
}) {
  const W = 560
  const H = 160
  const PAD = { top: 12, right: 8, bottom: 22, left: 30 }
  const [hover, setHover] = React.useState<number | null>(null)

  if (loading) {
    return <SkeletonWave height={H} />
  }
  if (points.length === 0) {
    return (
      <ChartEmpty
        height={H}
        message="No graded runs yet. Accuracy plots here once a shadow run is graded."
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
}: {
  points: RuntimeScatterPoint[]
  loading: boolean
}) {
  const W = 320
  const H = 220
  const PAD = { top: 10, right: 10, bottom: 24, left: 34 }
  const [hover, setHover] = React.useState<number | null>(null)

  if (loading) return <SkeletonWave height={H} />
  if (points.length === 0) {
    return (
      <ChartEmpty
        height={H}
        message="No shadow-tested migrations yet. Predicted vs. actual runtime appears here after the first one completes."
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
        fill="var(--muted-foreground)"
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
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
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

// --- 3. Donut: migration type distribution ----------------------------------

export type MigrationTypeSlice = { type: string; count: number }

export function MigrationTypeDonut({
  slices,
  loading,
}: {
  slices: MigrationTypeSlice[]
  loading: boolean
}) {
  const size = 176
  const cx = size / 2
  const cy = size / 2
  const rOuter = size / 2 - 6
  const rInner = rOuter * 0.62
  const [hover, setHover] = React.useState<number | null>(null)

  if (loading) {
    return (
      <div className="flex items-center justify-center" style={{ height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
          <circle
            cx={cx}
            cy={cy}
            r={(rOuter + rInner) / 2}
            fill="none"
            stroke="var(--muted)"
            strokeWidth={rOuter - rInner}
            className="animate-pulse"
          />
        </svg>
      </div>
    )
  }
  if (slices.length === 0) {
    return (
      <ChartEmpty
        height={size}
        message="No migrations recorded yet. Statement types (ALTER TABLE, CREATE INDEX, …) will appear here."
        icon={
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth={1.6} strokeDasharray="3 3" />
          </svg>
        }
      />
    )
  }

  const sorted = [...slices].sort((a, b) => b.count - a.count)
  const top = sorted.slice(0, 3)
  const rest = sorted.slice(3)
  const otherCount = rest.reduce((sum, s) => sum + s.count, 0)
  const entries: { label: string; count: number; color: string }[] = top.map((s, i) => ({
    label: formatMigrationType(s.type),
    count: s.count,
    color: CAT_COLORS[i]!,
  }))
  if (otherCount > 0) {
    entries.push({ label: "Other", count: otherCount, color: CAT_OTHER })
  }
  const total = entries.reduce((sum, e) => sum + e.count, 0) || 1

  const arcs = entries.reduce<
    { label: string; count: number; color: string; start: number; end: number; frac: number }[]
  >((acc, e) => {
    const prevEnd = acc.length > 0 ? acc[acc.length - 1]!.end : -Math.PI / 2
    const frac = e.count / total
    acc.push({ ...e, start: prevEnd, end: prevEnd + frac * Math.PI * 2, frac })
    return acc
  }, [])

  function arcPath(r0: number, r1: number, start: number, end: number) {
    const large = end - start > Math.PI ? 1 : 0
    const p = (r: number, a: number) => [cx + r * Math.cos(a), cy + r * Math.sin(a)]
    const [x0, y0] = p(r1, start)
    const [x1, y1] = p(r1, end)
    const [x2, y2] = p(r0, end)
    const [x3, y3] = p(r0, start)
    return `M${x0} ${y0} A${r1} ${r1} 0 ${large} 1 ${x1} ${y1} L${x2} ${y2} A${r0} ${r0} 0 ${large} 0 ${x3} ${y3} Z`
  }

  const active = hover != null ? arcs[hover] : null

  return (
    <div className="flex items-center gap-5">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
          {arcs.map((a, i) => (
            <path
              key={a.label}
              d={arcPath(rInner, hover === i ? rOuter + 3 : rOuter, a.start, a.end)}
              fill={a.color}
              stroke="var(--card)"
              strokeWidth={2}
              className="cursor-pointer transition-[d]"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover((h) => (h === i ? null : h))}
            />
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-foreground text-[22px] leading-none font-bold tabular-nums">
            {active ? active.count : total}
          </span>
          <span className="text-muted-foreground mt-1 text-[10px] leading-none">
            {active ? formatPercent(active.frac) : "total"}
          </span>
        </div>
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        {arcs.map((a, i) => (
          <div
            key={a.label}
            className={cn(
              "flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-[12px] transition-colors",
              hover === i ? "bg-muted" : ""
            )}
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover((h) => (h === i ? null : h))}
          >
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ backgroundColor: a.color }}
              aria-hidden
            />
            <span className="text-foreground min-w-0 flex-1 truncate font-medium">{a.label}</span>
            <span className="text-muted-foreground shrink-0 tabular-nums">{a.count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// --- 4. Horizontal bar: risk level distribution ------------------------------

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
}: {
  buckets: RiskLevelBucket[]
  loading: boolean
}) {
  const rowH = 30
  const H = rowH * 4 + 8
  const [hover, setHover] = React.useState<number | null>(null)

  if (loading) {
    return (
      <div className="space-y-2.5" style={{ minHeight: H }}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="bg-muted h-6 animate-pulse rounded" style={{ width: `${70 - i * 12}%` }} />
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
    <div className="space-y-2.5">
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
            <div className="bg-muted relative h-6 min-w-0 flex-1 overflow-hidden rounded-md">
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

// --- panel wrapper -----------------------------------------------------------

export function AnalyticsChartHeader({ children }: { children: React.ReactNode }) {
  return <PanelLabel className="mb-3">{children}</PanelLabel>
}

export { ChartTheme }
