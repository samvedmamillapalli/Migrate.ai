import { ShieldCheck, Database, Blocks, Check, GitBranch, ArrowLeft, ArrowRight, RotateCcw } from "lucide-react";
import { PIPELINE_STEPS } from "./site-data";

const ICONS = {
  shield: ShieldCheck,
  database: Database,
  blocks: Blocks,
  check: Check,
  branch: GitBranch,
} as const;

export function PipelineSection() {
  return (
    <section
      id="prediction-learning"
      className="mx-auto w-full max-w-[1180px] scroll-mt-24 px-6"
    >
      <div className="rounded-3xl border border-border bg-surface px-6 py-14 shadow-[0_1px_0_0_rgba(0,0,0,0.02)] sm:px-10">
        <div className="text-center">
          <p className="eyebrow text-accent">The migration orchestration pipeline</p>
          <h2 className="font-display mt-4 text-[34px] leading-[1.1] tracking-[-0.5px] text-foreground sm:text-[40px]">
            From prediction to learning.
          </h2>
          <p className="mx-auto mt-3 max-w-xl text-[13px] text-muted-foreground">
            Every migration grows more reliable through a deliberate, observable loop.
          </p>
        </div>

        <ol className="mt-12 grid grid-cols-2 gap-x-4 gap-y-10 sm:grid-cols-3 lg:grid-cols-6">
          {PIPELINE_STEPS.map((step, i) => {
            const Icon = ICONS[step.icon];
            return (
              <li key={step.title} className="relative flex flex-col items-center text-center">
                {i < PIPELINE_STEPS.length - 1 && (
                  <span className="dotted-rule absolute left-[calc(50%+28px)] top-[23px] hidden h-px w-[calc(100%-56px)] lg:block" />
                )}
                <span className="grid size-12 place-items-center rounded-full border border-border bg-background">
                  <Icon className="size-[18px] text-foreground" strokeWidth={1.6} />
                </span>
                <h3 className="mt-4 text-[12px] font-semibold text-foreground">{step.title}</h3>
                <p className="mt-1 text-[11px] text-muted-foreground">{step.description}</p>
              </li>
            );
          })}
        </ol>

        <div className="mt-10 flex items-center gap-3">
          <RotateCcw className="size-4 shrink-0 text-accent" strokeWidth={1.6} />
          <span className="dotted-rule h-px flex-1" />
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-[11px] text-muted-foreground">
            <ArrowLeft className="size-3 text-accent" />
            Continuous improvement
            <ArrowRight className="size-3 text-accent" />
          </span>
          <span className="dotted-rule h-px flex-1" />
          <RotateCcw className="size-4 shrink-0 -scale-x-100 text-accent" strokeWidth={1.6} />
        </div>
      </div>
    </section>
  );
}