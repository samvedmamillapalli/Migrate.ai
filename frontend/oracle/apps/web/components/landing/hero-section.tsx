"use client"

import Link from "next/link"
import { ArrowRight } from "lucide-react"

import { buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

export function HeroSection({ compact = false }: { compact?: boolean }) {
  return (
    <section
      className={cn(
        "mx-auto w-full max-w-[1180px] shrink-0 px-6 text-center",
        compact
          ? "pt-3 pb-2 sm:pt-4 lg:pt-5"
          : "pt-8 pb-8 sm:pt-10 lg:pt-12"
      )}
    >
      <h1
        className={cn(
          "animate-text-reveal font-display text-foreground mx-auto max-w-[1000px] pb-0.5 tracking-[-1.2px] text-balance",
          compact
            ? "text-[28px] leading-[1.08] sm:text-[36px] lg:text-[42px] xl:text-[48px]"
            : "text-[38px] leading-[1.03] sm:text-[56px] lg:text-[68px]"
        )}
      >
        Know your migration{" "}
        <span className="block sm:inline">
          <em className="font-display text-primary italic">before</em> your
          database does.
        </span>
      </h1>
      <p
        className={cn(
          "animate-text-reveal text-muted-foreground mx-auto max-w-xl leading-snug [animation-delay:250ms]",
          compact
            ? "mt-2 text-[13px] sm:mt-2.5"
            : "mt-6 text-[15px] leading-relaxed"
        )}
      >
        Migration Oracle predicts, verifies, grades, and learns from every
        database migration using shadow execution and agentic memory.
      </p>
      <div
        className={cn(
          "animate-rise flex flex-wrap items-center justify-center gap-2.5 [animation-delay:220ms]",
          compact ? "mt-3.5" : "mt-8 gap-3"
        )}
      >
        <Link
          href="/get-started"
          className={cn(
            buttonVariants({ size: compact ? "sm" : "lg" }),
            "group rounded-full px-5 text-[13px]",
            !compact && "px-6 text-[14px]"
          )}
        >
          Plan a migration
          <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
        </Link>
        <Link
          href="/#prediction-learning"
          className={cn(
            buttonVariants({
              variant: "outline",
              size: compact ? "sm" : "lg",
            }),
            "bg-surface rounded-full border-border px-5 text-[13px]",
            !compact && "px-6 text-[14px]"
          )}
        >
          View the method
        </Link>
      </div>
    </section>
  )
}
