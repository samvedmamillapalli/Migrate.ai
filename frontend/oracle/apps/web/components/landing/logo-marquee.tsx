"use client"

import * as React from "react"
import {
  motion,
  useAnimationFrame,
  useMotionValue,
  useReducedMotion,
} from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

const TECH = [
  { name: "CockroachDB", mark: "CRDB" },
  { name: "Amazon Bedrock", mark: "BRK" },
  { name: "Amazon Titan", mark: "TTN" },
  { name: "AWS Step Functions", mark: "SFN" },
  { name: "Amazon EventBridge", mark: "EVB" },
] as const

const SPEED_PX_PER_SEC = 42

function LogoChip({ name, mark }: { name: string; mark: string }) {
  return (
    <li className="flex shrink-0 items-center gap-3">
      <span
        aria-hidden
        className="flex size-9 items-center justify-center rounded-full border border-[#1f1b1a]/10 bg-[#fffcf9] font-mono text-[10px] font-medium tracking-wide text-[#1f1b1a]/70"
      >
        {mark}
      </span>
      <span className="text-[15px] font-medium tracking-[-0.01em] text-[#1f1b1a]/80 whitespace-nowrap">
        {name}
      </span>
    </li>
  )
}

export function LogoMarquee({ className }: { className?: string }) {
  const prefersReducedMotion = useReducedMotion()
  const [paused, setPaused] = React.useState(false)
  const x = useMotionValue(0)
  const trackRef = React.useRef<HTMLUListElement>(null)
  const halfWidthRef = React.useRef(0)

  React.useEffect(() => {
    const el = trackRef.current
    if (!el) return

    const measure = () => {
      halfWidthRef.current = el.scrollWidth / 2
    }
    measure()

    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useAnimationFrame((_, delta) => {
    if (prefersReducedMotion || paused) return
    const half = halfWidthRef.current
    if (half <= 0) return
    let next = x.get() - (delta / 1000) * SPEED_PX_PER_SEC
    if (next <= -half) next += half
    x.set(next)
  })

  const row = (
    <>
      {TECH.map((item) => (
        <LogoChip key={item.name} {...item} />
      ))}
    </>
  )

  return (
    <section
      aria-label="Built on trusted technologies"
      className={cn("w-full py-16 md:py-20", className)}
    >
      <p className="mb-8 text-center font-mono text-[11px] font-medium tracking-[0.18em] text-[#716b67] uppercase">
        Built on Trusted Technologies
      </p>

      <div
        className="relative mx-auto max-w-6xl overflow-hidden"
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
      >
        {/* Edge fades */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 z-10 w-16 bg-gradient-to-r from-[#f8f5f1] to-transparent sm:w-24"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 right-0 z-10 w-16 bg-gradient-to-l from-[#f8f5f1] to-transparent sm:w-24"
        />

        <motion.ul
          ref={trackRef}
          style={{ x: prefersReducedMotion ? 0 : x }}
          className="flex w-max list-none items-center gap-14 py-2 pr-14"
        >
          {row}
          {/* Duplicate for seamless loop */}
          {TECH.map((item) => (
            <LogoChip key={`dup-${item.name}`} {...item} />
          ))}
        </motion.ul>
      </div>
    </section>
  )
}
