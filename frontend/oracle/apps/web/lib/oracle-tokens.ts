/**
 * Migration Oracle — design tokens
 *
 * Semantic colors only. Motion only for state transitions.
 * Prefer removing an element over decorating one.
 */

export const oracleColor = {
  /** Structure — borders, tracks, chrome, idle nodes */
  structure: {
    hex: "#262626",
    soft: "rgba(255,255,255,0.08)",
    muted: "rgba(255,255,255,0.45)",
    class: {
      border: "border-border",
      track: "bg-border",
      text: "text-muted-foreground",
      fill: "bg-muted",
    },
  },
  /** Content — primary readable text and values */
  content: {
    hex: "#FAFAFA",
    class: {
      text: "text-foreground",
      soft: "text-foreground/80",
    },
  },
  /** Active reasoning — AI / analysis in progress ONLY */
  reasoning: {
    hex: "#8B7EC8",
    soft: "rgba(139,126,200,0.15)",
    bright: "#C4B5FD",
    class: {
      text: "text-[#C4B5FD]",
      border: "border-[#8B7EC8]/50",
      bg: "bg-[#8B7EC8]/12",
      fill: "bg-[#8B7EC8]",
      ring: "shadow-[0_0_0_3px_rgba(139,126,200,0.16)]",
      ping: "bg-[#8B7EC8]/40",
    },
  },
  /** Verified — successful completion ONLY */
  verified: {
    hex: "#34D399",
    soft: "rgba(52,211,153,0.14)",
    class: {
      text: "text-emerald-400",
      border: "border-emerald-500/40",
      bg: "bg-emerald-500/12",
      fill: "bg-emerald-500/75",
    },
  },
  /** Rollback risk — warnings / destructive ONLY */
  risk: {
    hex: "#F87171",
    class: {
      text: "text-red-400",
      border: "border-red-500/40",
      bg: "bg-red-500/10",
      fill: "bg-red-500/70",
    },
  },
} as const

/** Spacing scale (px). Prefer these over ad-hoc values. */
export const oracleSpace = {
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  8: 32,
  10: 40,
  12: 48,
  16: 64,
  /** Section vertical rhythm */
  section: 120,
  /** Hero top padding */
  hero: 160,
} as const

/** Border radii — keep the set small. */
export const oracleRadius = {
  /** Controls, inputs, nodes */
  control: "rounded-md",
  /** Status strips, nested surfaces */
  surface: "rounded-lg",
  /** Panels, cards, app windows */
  panel: "rounded-xl",
  /** Pills / primary buttons only */
  pill: "rounded-full",
} as const

/** Typography roles */
export const oracleType = {
  display: "text-4xl sm:text-5xl md:text-6xl font-semibold tracking-tight leading-[1.1]",
  title: "text-lg font-medium tracking-tight",
  subtitle: "text-base sm:text-lg text-muted-foreground leading-relaxed",
  body: "text-sm leading-relaxed",
  label: "text-xs text-muted-foreground tracking-tight",
  mono: "font-mono text-sm tracking-tight",
  monoSm: "font-mono text-xs tracking-tight",
} as const

/** Icon sizes (px) */
export const oracleIcon = {
  xs: 12,
  sm: 14,
  md: 16,
  lg: 20,
} as const

/**
 * Motion — durations in seconds.
 * Only use when communicating a state change.
 */
export const oracleMotion = {
  duration: {
    /** Micro feedback */
    instant: 0.12,
    /** Crossfades, node settles */
    fast: 0.2,
    /** Default state transition */
    base: 0.28,
    /** Connector growth, panel entrance */
    slow: 0.45,
    /** Workflow step dwell (orchestration) */
    step: 0.65,
  },
  /** Ease-out — deliberate settle, no bounce */
  ease: [0.16, 1, 0.3, 1] as [number, number, number, number],
  easeCss: "cubic-bezier(0.16, 1, 0.3, 1)",
} as const

export type OracleNodeState = "idle" | "pending" | "active" | "verified" | "risk"
