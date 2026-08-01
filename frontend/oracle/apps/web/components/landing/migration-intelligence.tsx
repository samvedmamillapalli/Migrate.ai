"use client"

import * as React from "react"
import { motion, useInView, useReducedMotion } from "motion/react"

import { cn } from "@workspace/ui/lib/utils"

const EASE_OUT = [0.16, 1, 0.3, 1] as const

/**
 * Calm product frame matching the Framer “Migration Intelligence” slot.
 */
export function MigrationIntelligence({ className }: { className?: string }) {
  const ref = React.useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, amount: 0.35 })
  const prefersReducedMotion = useReducedMotion()
  const active = inView || !!prefersReducedMotion

  return (
    <div
      ref={ref}
      className={cn("mx-auto w-full max-w-5xl px-6 md:px-8", className)}
    >
      <motion.div
        className="overflow-hidden rounded-[1.25rem] border border-[#1f1b1a]/10 bg-[#fffcf9] shadow-[0_24px_80px_-40px_rgba(31,27,26,0.35)]"
        initial={prefersReducedMotion ? false : { opacity: 0, y: 28 }}
        animate={active ? { opacity: 1, y: 0 } : { opacity: 0, y: 28 }}
        transition={{ duration: 0.85, ease: EASE_OUT }}
      >
        <div className="flex items-center gap-2 border-b border-[#1f1b1a]/8 px-4 py-3">
          <span className="size-2.5 rounded-full bg-[#e8a0a0]/90" />
          <span className="size-2.5 rounded-full bg-[#f1dec3]" />
          <span className="size-2.5 rounded-full bg-[#c8d5c0]" />
          <span className="ml-3 font-mono text-[11px] tracking-tight text-[#716b67]">
            migration-intelligence
          </span>
        </div>

        <div className="grid gap-0 md:grid-cols-[1.1fr_0.9fr]">
          <div className="border-b border-[#1f1b1a]/8 p-5 md:border-r md:border-b-0 md:p-6">
            <p className="font-mono text-[10px] tracking-[0.16em] text-[#716b67] uppercase">
              Prediction
            </p>
            <p className="mt-3 font-[family-name:var(--font-display)] text-2xl leading-tight font-medium tracking-[-0.02em] text-[#1f1b1a]">
              Low rollback risk · 3.8s estimate
            </p>
            <p className="mt-3 text-sm leading-relaxed text-[#716b67]">
              Shadow cluster will verify duration, storage delta, and schema
              job pressure before anything touches production.
            </p>
            <div className="mt-6 space-y-2">
              {[
                { label: "Duration band", value: "2.1 – 5.4s" },
                { label: "Storage delta", value: "+12 MB" },
                { label: "Memory hits", value: "2 graded runs" },
              ].map((row) => (
                <div
                  key={row.label}
                  className="flex items-center justify-between rounded-lg bg-[#f8f5f1] px-3 py-2 text-sm"
                >
                  <span className="text-[#716b67]">{row.label}</span>
                  <span className="font-medium text-[#1f1b1a]">{row.value}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-[#1f1b1a] p-5 text-[#fffcf9] md:p-6">
            <p className="font-mono text-[10px] tracking-[0.16em] text-[#f1dec3]/80 uppercase">
              Shadow log
            </p>
            <div className="mt-4 space-y-2 font-mono text-[12px] leading-relaxed text-[#fffcf9]/75">
              <p>
                <span className="text-[#f1dec3]">✓</span> schema analyzed
              </p>
              <p>
                <span className="text-[#f1dec3]">✓</span> shadow cluster ready
              </p>
              <p>
                <span className="text-[#f1dec3]">✓</span> migration executed
              </p>
              <p>
                <span className="text-[#f1dec3]">✓</span> grade written to memory
              </p>
              <p className="pt-2 text-[#fffcf9]/45">
                waiting for next migration…
              </p>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
