"use client"

import * as React from "react"
import Link from "next/link"
import { ArrowRight } from "lucide-react"
import { motion, useReducedMotion } from "motion/react"

import { TextReveal } from "@/components/landing/text-reveal"
import { cn } from "@workspace/ui/lib/utils"

const EASE_OUT = [0.16, 1, 0.3, 1] as const

const HEADLINE_LINES = [
  { parts: [{ text: "Know your migration" }] },
  {
    parts: [
      { text: "before", italic: true },
      { text: " your database does." },
    ],
  },
]

export function Hero() {
  const prefersReducedMotion = useReducedMotion()
  const [headingDone, setHeadingDone] = React.useState(false)

  React.useEffect(() => {
    if (prefersReducedMotion) setHeadingDone(true)
  }, [prefersReducedMotion])

  const showActions = headingDone || !!prefersReducedMotion

  return (
    <section
      aria-labelledby="hero-heading"
      className="relative mx-auto flex w-full max-w-5xl flex-col items-center px-6 pt-28 pb-16 text-center md:px-8 md:pt-36 md:pb-20"
    >
      <TextReveal
        id="hero-heading"
        as="h1"
        lines={HEADLINE_LINES}
        duration={0.8}
        lineStagger={0.14}
        onComplete={() => setHeadingDone(true)}
        className="font-[family-name:var(--font-display)] text-[clamp(2.5rem,7vw,4rem)] leading-[1.02] font-medium tracking-[-0.04em] text-[#1f1b1a]"
      />

      <motion.p
        className="mt-6 max-w-xl text-base leading-relaxed text-[#716b67] sm:text-lg"
        initial={prefersReducedMotion ? false : { opacity: 0, y: 16 }}
        animate={
          showActions ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }
        }
        transition={{ duration: 0.7, ease: EASE_OUT }}
      >
        Migration Oracle predicts, verifies, grades, and continuously improves
        database migrations using shadow execution and agentic memory.
      </motion.p>

      <div className="mt-10 flex w-full flex-col items-stretch justify-center gap-3 sm:w-auto sm:flex-row sm:items-center sm:gap-3">
        <motion.div
          initial={prefersReducedMotion ? false : { opacity: 0, y: 12 }}
          animate={
            showActions ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }
          }
          transition={{ duration: 0.55, delay: 0, ease: EASE_OUT }}
        >
          <Link
            href="/get-started"
            className={cn(
              "inline-flex h-11 w-full items-center justify-center gap-2 rounded-full bg-[#1f1b1a] px-6 text-sm font-medium text-[#fffcf9] transition-opacity hover:opacity-90 sm:w-auto"
            )}
          >
            Plan a migration
            <ArrowRight className="size-4" strokeWidth={1.75} />
          </Link>
        </motion.div>

        <motion.div
          initial={prefersReducedMotion ? false : { opacity: 0, y: 12 }}
          animate={
            showActions ? { opacity: 1, y: 0 } : { opacity: 0, y: 12 }
          }
          transition={{ duration: 0.55, delay: 0.15, ease: EASE_OUT }}
        >
          <Link
            href="#how-it-works"
            className={cn(
              "inline-flex h-11 w-full items-center justify-center rounded-full border border-[#1f1b1a]/15 bg-transparent px-6 text-sm font-medium text-[#1f1b1a] transition-colors hover:bg-[#1f1b1a]/[0.04] sm:w-auto"
            )}
            onClick={(e) => {
              e.preventDefault()
              document
                .getElementById("how-it-works")
                ?.scrollIntoView({ behavior: "smooth", block: "start" })
            }}
          >
            View the method
          </Link>
        </motion.div>
      </div>
    </section>
  )
}
