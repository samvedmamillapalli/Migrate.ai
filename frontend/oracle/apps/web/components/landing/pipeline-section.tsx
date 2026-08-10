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
import { cn } from "@workspace/ui/lib/utils"

const ICONS = {
  shield: ShieldCheck,
  database: Database,
  blocks: Blocks,
  check: Check,
  branch: GitBranch,
} as const

export function PipelineSection({ compact = false }: { compact?: boolean }) {
  return (
    <section
      id="prediction-learning"
      className={cn(
        "mx-auto w-full max-w-[1180px] px-6",
        compact
          ? "scroll-mt-16 flex min-h-0 flex-1 flex-col justify-center py-1"
          : "scroll-mt-24"
      )}
    >
      <div
        className={cn(
          "border-border bg-surface shadow-[0_1px_0_0_rgba(0,0,0,0.02)]",
          compact
            ? "rounded-2xl border px-4 py-4 sm:px-6 sm:py-5"
            : "rounded-3xl border px-6 py-14 sm:px-10"
        )}
      >
        <div className="text-center">
          <p
            className={cn(
              "eyebrow text-accent",
              compact && "text-[10px] tracking-[0.14em]"
            )}
          >
            The migration orchestration pipeline
          </p>
          <h2
            className={cn(
              "font-display text-foreground tracking-[-0.5px]",
              compact
                ? "mt-1 text-[22px] leading-[1.15] sm:text-[26px]"
                : "mt-4 text-[34px] leading-[1.1] sm:text-[40px]"
            )}
          >
            From prediction to learning.
          </h2>
          {!compact ? (
            <p className="text-muted-foreground mx-auto mt-3 max-w-xl text-[13px]">
              Every migration grows more reliable through a deliberate,
              observable loop.
            </p>
          ) : null}
        </div>

        <ol
          className={cn(
            "grid grid-cols-3 lg:grid-cols-6",
            compact
              ? "mt-4 gap-x-2 gap-y-4 sm:mt-5"
              : "mt-12 grid-cols-2 gap-x-4 gap-y-10 sm:grid-cols-3"
          )}
        >
          {PIPELINE_STEPS.map((step, i) => {
            const Icon = ICONS[step.icon]
            return (
              <li
                key={step.title}
                className="relative flex flex-col items-center text-center"
              >
                {i < PIPELINE_STEPS.length - 1 ? (
                  <span
                    className={cn(
                      "dotted-rule absolute left-[calc(50%+28px)] hidden h-px w-[calc(100%-56px)] lg:block",
                      compact ? "top-[14px]" : "top-[23px]"
                    )}
                  />
                ) : null}
                <span
                  className={cn(
                    "border-border bg-background grid place-items-center rounded-full border",
                    compact ? "size-7" : "size-12"
                  )}
                >
                  <Icon
                    className={cn(
                      "text-foreground",
                      compact ? "size-3" : "size-[18px]"
                    )}
                    strokeWidth={1.6}
                  />
                </span>
                <h3
                  className={cn(
                    "text-foreground font-semibold",
                    compact ? "mt-1.5 text-[10px] leading-tight" : "mt-4 text-[12px]"
                  )}
                >
                  {step.title}
                </h3>
                {!compact ? (
                  <p className="text-muted-foreground mt-1 text-[11px]">
                    {step.description}
                  </p>
                ) : null}
              </li>
            )
          })}
        </ol>

        <div
          className={cn(
            "flex items-center gap-3",
            compact ? "mt-3.5 sm:mt-4" : "mt-10"
          )}
        >
          <RotateCcw
            className={cn(
              "text-accent shrink-0",
              compact ? "size-3.5" : "size-4"
            )}
            strokeWidth={1.6}
          />
          <span className="dotted-rule h-px flex-1" />
          <span
            className={cn(
              "border-border bg-background text-muted-foreground inline-flex items-center gap-2 rounded-full border",
              compact
                ? "px-2.5 py-1 text-[10px]"
                : "px-3 py-1.5 text-[11px]"
            )}
          >
            <ArrowLeft className="text-accent size-3" />
            Continuous improvement
            <ArrowRight className="text-accent size-3" />
          </span>
          <span className="dotted-rule h-px flex-1" />
          <RotateCcw
            className={cn(
              "text-accent shrink-0 -scale-x-100",
              compact ? "size-3.5" : "size-4"
            )}
            strokeWidth={1.6}
          />
        </div>
      </div>
    </section>
  )
}
