"use client"

import * as React from "react"
import Link from "next/link"
import { motion, useReducedMotion } from "motion/react"

import { ProductPreview } from "@/components/landing/ProductPreview"
import { buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

const HEADLINE = "Migration Oracle"
const SUBTITLE =
  "Predict → verify → grade → remember. Forecast blast radius, run it on a disposable CockroachDB shadow cluster, score the forecast, and retrieve graded memories with Distributed Vector Indexing so the next guess is smarter."

const easeOut = [0.16, 1, 0.3, 1] as const

export function Hero() {
  const prefersReducedMotion = useReducedMotion()

  return (
    <section
      aria-labelledby="hero-heading"
      className="mx-auto flex w-full max-w-7xl flex-col px-6 pt-40 pb-[120px] md:px-8"
    >
      <div className="mx-auto flex w-full max-w-3xl flex-col items-start text-left">
        <motion.h1
          id="hero-heading"
          className="text-foreground text-4xl leading-[1.12] font-semibold tracking-tight sm:text-5xl md:text-6xl"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: easeOut }}
        >
          {HEADLINE}
        </motion.h1>

        <motion.p
          className="text-muted-foreground mt-6 max-w-[700px] text-base leading-relaxed sm:text-lg"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.08, ease: easeOut }}
        >
          {SUBTITLE}
        </motion.p>

        <motion.div
          className="mt-10 flex w-full flex-col gap-3 sm:w-auto sm:flex-row sm:items-center sm:gap-4"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.16, ease: easeOut }}
        >
          <Link
            href="/dashboard"
            className={cn(
              buttonVariants({ variant: "default", size: "lg" }),
              "rounded-full px-6"
            )}
          >
            Open console
          </Link>
          <Link
            href="/dashboard/migrations/current"
            className={cn(
              buttonVariants({ variant: "outline", size: "lg" }),
              "rounded-full px-6"
            )}
          >
            Start a migration
          </Link>
        </motion.div>
      </div>

      <ProductPreview className="mt-20" />
    </section>
  )
}
