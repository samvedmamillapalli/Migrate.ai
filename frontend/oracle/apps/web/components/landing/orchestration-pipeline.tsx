"use client"

import * as React from "react"
import {
  motion,
  useInView,
  useReducedMotion,
} from "motion/react"
import {
  Brain,
  Eye,
  GitBranch,
  ShieldCheck,
  Sparkles,
  ThumbsUp,
} from "lucide-react"

import { TextReveal } from "@/components/landing/text-reveal"
import { cn } from "@workspace/ui/lib/utils"

const EASE_OUT = [0.16, 1, 0.3, 1] as const

const STEPS = [
  {
    title: "Policy Checks",
    description: "Validate controls and guardrails.",
    icon: ShieldCheck,
  },
  {
    title: "Memory Retrieval",
    description: "Recall similar migrations.",
    icon: Brain,
  },
  {
    title: "AI Prediction",
    description: "Forecast risks and paths.",
    icon: Sparkles,
  },
  {
    title: "Human Approval",
    description: "Review with context.",
    icon: ThumbsUp,
  },
  {
    title: "Shadow Execution",
    description: "Run safely in parallel.",
    icon: GitBranch,
  },
  {
    title: "Grade and Learn",
    description: "Improve every run.",
    icon: Eye,
  },
] as const

export function OrchestrationPipeline({ className }: { className?: string }) {
  const ref = React.useRef<HTMLElement | null>(null)
  const inView = useInView(ref, { once: true, amount: 0.25 })
  const prefersReducedMotion = useReducedMotion()
  const active = inView || !!prefersReducedMotion

  return (
    <section
      ref={ref}
      id="how-it-works"
      aria-labelledby="pipeline-heading"
      className={cn("mx-auto w-full max-w-6xl px-6 py-24 md:px-8 md:py-32", className)}
    >
      <div className="mx-auto max-w-2xl text-center">
        <motion.p
          className="mb-5 font-mono text-[11px] font-medium tracking-[0.18em] text-[#716b67] uppercase"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 12 }}
          animate={active ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }}
          transition={{ duration: 0.6, ease: EASE_OUT }}
        >
          The Migration Orchestration Pipeline
        </motion.p>

        <TextReveal
          as="h2"
          id="pipeline-heading"
          lines={[
            { parts: [{ text: "From prediction" }] },
            { parts: [{ text: "to learning." }] },
          ]}
          className="font-[family-name:var(--font-display)] text-[clamp(2.25rem,5vw,3.5rem)] leading-[1.05] font-medium tracking-[-0.03em] text-[#1f1b1a]"
          duration={0.8}
        />

        <motion.p
          className="mt-5 text-base leading-relaxed text-[#716b67] sm:text-lg"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 14 }}
          animate={active ? { opacity: 1, y: 0 } : { opacity: 0, y: 14 }}
          transition={{ duration: 0.7, delay: 0.25, ease: EASE_OUT }}
        >
          Every migration grows more reliable through a deliberate, observable
          loop.
        </motion.p>
      </div>

      <div className="relative mt-16 md:mt-20">
        {/* Connecting line — draws left → right */}
        <div
          aria-hidden
          className="pointer-events-none absolute top-[28px] right-4 left-4 hidden h-px md:block lg:left-8 lg:right-8"
        >
          <motion.div
            className="h-full origin-left"
            style={{
              backgroundImage:
                "repeating-linear-gradient(90deg, rgba(31,27,26,0.35) 0 4px, transparent 4px 10px)",
            }}
            initial={prefersReducedMotion ? false : { scaleX: 0, opacity: 0 }}
            animate={
              active
                ? { scaleX: 1, opacity: 1 }
                : { scaleX: 0, opacity: 0 }
            }
            transition={{
              duration: prefersReducedMotion ? 0 : 1.4,
              delay: prefersReducedMotion ? 0 : 0.15,
              ease: EASE_OUT,
            }}
          />
        </div>

        <ol className="grid grid-cols-1 gap-8 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 lg:gap-4">
          {STEPS.map((step, index) => {
            const Icon = step.icon
            const delay = prefersReducedMotion ? 0 : 0.2 + index * 0.12
            return (
              <motion.li
                key={step.title}
                className="relative flex flex-col items-center text-center"
                initial={
                  prefersReducedMotion
                    ? false
                    : { opacity: 0, y: 28, scale: 0.96 }
                }
                animate={
                  active
                    ? { opacity: 1, y: 0, scale: 1 }
                    : { opacity: 0, y: 28, scale: 0.96 }
                }
                transition={{ duration: 0.7, delay, ease: EASE_OUT }}
              >
                <motion.span
                  className="relative z-[1] mb-4 flex size-14 items-center justify-center rounded-full border border-[#1f1b1a]/10 bg-[#fffcf9] text-[#1f1b1a] shadow-[0_1px_0_rgba(31,27,26,0.04)]"
                  initial={
                    prefersReducedMotion ? false : { opacity: 0, scale: 0.8 }
                  }
                  animate={
                    active
                      ? { opacity: 1, scale: 1 }
                      : { opacity: 0, scale: 0.8 }
                  }
                  transition={{
                    duration: 0.55,
                    delay: delay + 0.08,
                    ease: EASE_OUT,
                  }}
                >
                  <Icon className="size-5" strokeWidth={1.6} />
                </motion.span>
                <h3 className="text-[15px] font-medium tracking-[-0.01em] text-[#1f1b1a]">
                  {step.title}
                </h3>
                <p className="mt-1.5 max-w-[11rem] text-sm leading-snug text-[#716b67]">
                  {step.description}
                </p>
              </motion.li>
            )
          })}
        </ol>

        <motion.div
          className="mt-14 flex justify-center"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 10 }}
          animate={active ? { opacity: 1, y: 0 } : { opacity: 0, y: 10 }}
          transition={{
            duration: 0.6,
            delay: prefersReducedMotion ? 0 : 1.1,
            ease: EASE_OUT,
          }}
        >
          <span className="inline-flex items-center gap-2 rounded-full border border-[#1f1b1a]/10 bg-[#f1dec3]/45 px-4 py-1.5 text-[12px] font-medium tracking-wide text-[#1f1b1a]/80">
            <span className="size-1.5 rounded-full bg-[#1f1b1a]/55" />
            Continuous improvement
          </span>
        </motion.div>
      </div>
    </section>
  )
}
