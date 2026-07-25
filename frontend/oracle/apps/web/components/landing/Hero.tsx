"use client"

import * as React from "react"
import Link from "next/link"
import { motion, useReducedMotion } from "motion/react"

import { TextReveal as RevealText } from "@/components/animations/RevealText"
import { ProductPreview } from "@/components/landing/ProductPreview"
import { buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

const HEADLINE = "Know your migration before your database does."
const SUBTITLE =
  "Migration Oracle predicts, verifies, grades, and continuously improves database migrations using shadow execution and agentic memory."

const easeOut = [0.16, 1, 0.3, 1] as const

/** Original 21st.dev timing: word stagger 0.05s + segment 0.3s. */
function revealDurationMs(text: string) {
  const segments = text.split(/(\s+)/).filter((s) => s.length > 0)
  return Math.round((segments.length - 1) * 50 + 300)
}

const HEADLINE_MS = revealDurationMs(HEADLINE)
const SUBTITLE_MS = revealDurationMs(SUBTITLE)

type Stage = "headline" | "subtitle" | "cta"

export function Hero() {
  const prefersReducedMotion = useReducedMotion()
  const [stage, setStage] = React.useState<Stage>(
    prefersReducedMotion ? "cta" : "headline"
  )

  React.useEffect(() => {
    if (prefersReducedMotion) {
      setStage("cta")
      return
    }

    const subtitleTimer = window.setTimeout(() => {
      setStage("subtitle")
    }, HEADLINE_MS)

    const ctaTimer = window.setTimeout(() => {
      setStage("cta")
    }, HEADLINE_MS + SUBTITLE_MS)

    return () => {
      window.clearTimeout(subtitleTimer)
      window.clearTimeout(ctaTimer)
    }
  }, [prefersReducedMotion])

  return (
    <section
      aria-labelledby="hero-heading"
      className="mx-auto flex w-full max-w-7xl flex-col px-6 pt-40 pb-[120px] md:px-8"
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col items-start text-left">
        <RevealText
          as="h1"
          per="word"
          preset="fade-in-blur"
          trigger
          className="text-foreground text-4xl leading-[1.12] font-semibold tracking-tight sm:text-5xl md:text-6xl"
        >
          {HEADLINE}
        </RevealText>
        <span id="hero-heading" className="sr-only">
          {HEADLINE.replace(/\n/g, " ")}
        </span>

        <RevealText
          as="p"
          per="word"
          preset="fade-in-blur"
          trigger={stage === "subtitle" || stage === "cta"}
          className="text-muted-foreground mt-6 max-w-[700px] text-base leading-relaxed sm:text-lg"
        >
          {SUBTITLE}
        </RevealText>

        <motion.div
          className="mt-10 flex w-full flex-col gap-3 sm:w-auto sm:flex-row sm:items-center sm:gap-4"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 6 }}
          animate={
            stage === "cta" ? { opacity: 1, y: 0 } : { opacity: 0, y: 6 }
          }
          transition={{ duration: 0.35, ease: easeOut }}
        >
          <Link
            href="/get-started"
            className={cn(
              buttonVariants({ variant: "default", size: "lg" }),
              "rounded-full px-6"
            )}
          >
            Get Started
          </Link>
          <Link
            href="/docs"
            className={cn(
              buttonVariants({ variant: "outline", size: "lg" }),
              "rounded-full px-6"
            )}
          >
            View Documentation
          </Link>
        </motion.div>
      </div>

      <ProductPreview className="mt-20" />
    </section>
  )
}
