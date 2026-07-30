"use client"

import {
  ArrowLeft,
  ArrowRight,
  Blocks,
  Check,
  Database,
  GitBranch,
  RotateCcw,
  ShieldCheck,
} from "lucide-react"

import { PIPELINE_STEPS } from "@/components/landing/site-data"

const ICONS = {
  shield: ShieldCheck,
  database: Database,
  blocks: Blocks,
  check: Check,
  branch: GitBranch,
} as const

export function PipelineSection() {
  return (
    <section
      id="prediction-learning"
      className="mx-auto w-full max-w-[1180px] scroll-mt-24 px-6"
    >
      <div className="border-border bg-surface rounded-3xl border px-6 py-14 shadow-[0_1px_0_0_rgba(0,0,0,0.02)] sm:px-10">
        <div className="text-center">
          <p className="eyebrow text-accent">
            The migration orchestration pipeline
          </p>
          <h2 className="font-display text-foreground mt-4 text-[34px] leading-[1.1] tracking-[-0.5px] sm:text-[40px]">
            From prediction to learning.
          </h2>
          <p className="text-muted-foreground mx-auto mt-3 max-w-xl text-[13px]">
            Every migration grows more reliable through a deliberate, observable
            loop.
          </p>
        </div>

        <ol className="mt-12 grid grid-cols-2 gap-x-4 gap-y-10 sm:grid-cols-3 lg:grid-cols-6">
          {PIPELINE_STEPS.map((step, i) => {
            const Icon = ICONS[step.icon]
            return (
              <li
                key={step.title}
                className="relative flex flex-col items-center text-center"
              >
                {i < PIPELINE_STEPS.length - 1 ? (
                  <span className="dotted-rule absolute top-[23px] left-[calc(50%+28px)] hidden h-px w-[calc(100%-56px)] lg:block" />
                ) : null}
                <span className="border-border bg-background grid size-12 place-items-center rounded-full border">
                  <Icon
                    className="text-foreground size-[18px]"
                    strokeWidth={1.6}
                  />
                </span>
                <h3 className="text-foreground mt-4 text-[12px] font-semibold">
                  {step.title}
                </h3>
                <p className="text-muted-foreground mt-1 text-[11px]">
                  {step.description}
                </p>
              </li>
            )
          })}
        </ol>

        <div className="mt-10 flex items-center gap-3">
          <RotateCcw
            className="text-accent size-4 shrink-0"
            strokeWidth={1.6}
          />
          <span className="dotted-rule h-px flex-1" />
          <span className="border-border bg-background text-muted-foreground inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px]">
            <ArrowLeft className="text-accent size-3" />
            Continuous improvement
            <ArrowRight className="text-accent size-3" />
          </span>
          <span className="dotted-rule h-px flex-1" />
          <RotateCcw
            className="text-accent size-4 shrink-0 -scale-x-100"
            strokeWidth={1.6}
          />
        </div>
      </div>
    </section>
  )
}
