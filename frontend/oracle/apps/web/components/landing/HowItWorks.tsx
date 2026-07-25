"use client"

import { ExecutionFlow } from "@/components/landing/execution-flow"
import { SectionHeader } from "@/components/system/SectionHeader"

/**
 * How It Works — React Flow canvas (minimal verification pass).
 * Heading/copy unchanged; visualization swapped to ExecutionFlow.
 */
export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      aria-label="How It Works"
      className="mx-auto w-full max-w-7xl px-6 py-[120px] md:px-8"
    >
      <SectionHeader
        title="How It Works"
        description="One migration travels the bus — analyzed, predicted, verified in shadow, then remembered."
      />

      <div className="mt-14 overflow-x-auto md:mt-16">
        <ExecutionFlow />
      </div>
    </section>
  )
}
