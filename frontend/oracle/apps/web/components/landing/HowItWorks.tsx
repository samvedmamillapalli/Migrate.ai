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
        description="Predict on Bedrock, verify on a real disposable CockroachDB cluster (Step Functions), grade pred→actual, remember with VECTOR search."
      />

      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="space-y-1">
          <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
            CockroachDB
          </p>
          <p className="text-sm text-foreground/85">
            Distributed Vector Indexing on graded migration memories.
          </p>
        </div>
        <div className="space-y-1">
          <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
            CockroachDB
          </p>
          <p className="text-sm text-foreground/85">
            Managed MCP / SHOW JOBS watch during shadow ExecuteMigration.
          </p>
        </div>
        <div className="space-y-1">
          <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
            AWS
          </p>
          <p className="text-sm text-foreground/85">
            Bedrock + Step Functions + Lambda + S3 + Secrets Manager +
            CloudWatch.
          </p>
        </div>
      </div>
      <div className="mt-14 overflow-x-auto md:mt-16">
        <ExecutionFlow />
      </div>
    </section>
  )
}
