import type { Metadata } from "next"

import { JournalCard } from "@/components/landing/journal-card"
import { LandingTheme } from "@/components/landing/landing-theme"
import { JOURNAL_ENTRIES } from "@/components/landing/site-data"
import { SiteFooter } from "@/components/landing/site-footer"
import { SiteHeader } from "@/components/landing/site-header"

const description = "Every commit tells part of the story."

export const metadata: Metadata = {
  title: "Our Journey — Migration Oracle Field Notes",
  description,
}

export default function OurJourneyPage() {
  return (
    <LandingTheme>
      <div className="bg-background flex min-h-svh flex-col">
        <SiteHeader wordmarkUppercase />
        <main className="flex-1">
          <section className="mx-auto w-full max-w-[1180px] px-6 pt-24 pb-8 text-center sm:pt-32">
            <p className="eyebrow animate-rise text-accent">Field Notes / 2026</p>
            <h1 className="animate-rise font-display text-foreground mx-auto mt-5 max-w-4xl pb-1 text-[40px] leading-[1.03] tracking-[-1.5px] sm:text-[62px]">
              Shipped, broke, fixed, repeat.
            </h1>
            <p className="animate-rise text-muted-foreground mx-auto mt-5 max-w-lg text-[15px] leading-relaxed [animation-delay:120ms]">
              {description}
            </p>
          </section>

          <section className="mx-auto w-full max-w-[1180px] space-y-6 px-6 py-16">
            {JOURNAL_ENTRIES.map((entry) => (
              <JournalCard key={entry.href} entry={entry} />
            ))}
          </section>
        </main>
        <SiteFooter
          left="Migration Oracle / 2026"
          right="Field notes from Medium"
          bordered
          uppercaseLeft
        />
      </div>
    </LandingTheme>
  )
}
