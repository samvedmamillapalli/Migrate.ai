"use client"

import Link from "next/link"
import { ArrowRight } from "lucide-react"

import { buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

export function HeroSection() {
  return (
    <section className="mx-auto w-full max-w-[1180px] px-6 pt-16 pb-8 text-center sm:pt-24">
      <h1 className="animate-text-reveal font-display text-foreground mx-auto max-w-[1000px] pb-1 text-[38px] leading-[1.03] tracking-[-1.5px] text-balance sm:text-[56px] lg:text-[68px]">
        Know your migration{" "}
        <span className="block sm:inline">
          <em className="font-display text-primary italic">before</em>{" "}
          your database does.
        </span>
      </h1>
      <p className="animate-text-reveal text-muted-foreground mx-auto mt-6 max-w-xl text-[15px] leading-relaxed [animation-delay:250ms]">
      Migration Oracle predicts, verifies, grades, and learns from every database migration using shadow execution and agentic memory.
      </p>
      <div className="animate-rise mt-8 flex flex-wrap items-center justify-center gap-3 [animation-delay:220ms]">
        <Link
          href="/get-started"
          className={cn(
            buttonVariants({ size: "lg" }),
            "group rounded-full px-6 text-[14px]"
          )}
        >
          Plan a migration
          <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
        </Link>
        <Link
          href="/#prediction-learning"
          className={cn(
            buttonVariants({ variant: "outline", size: "lg" }),
            "bg-surface rounded-full border-border px-6 text-[14px]"
          )}
        >
          View the method
        </Link>
      </div>
    </section>
  )
}
