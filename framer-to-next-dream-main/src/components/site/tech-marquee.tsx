import { Database, Cpu, Workflow, Radio, Boxes } from "lucide-react";
import { TECHNOLOGIES } from "./site-data";

const ICONS = [Database, Boxes, Cpu, Workflow, Radio];

export function TechMarquee() {
  const items = [...TECHNOLOGIES, ...TECHNOLOGIES];

  return (
    <section className="mx-auto w-full max-w-[1180px] px-6 py-20">
      <p className="eyebrow text-center text-muted-foreground">Built on trusted technologies</p>
      <div className="relative mt-8 overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]">
        <div className="animate-marquee flex w-max items-center gap-16">
          {items.map((name, i) => {
            const Icon = ICONS[i % ICONS.length];
            return (
              <div key={`${name}-${i}`} className="flex shrink-0 items-center gap-2.5">
                <span className="grid size-6 place-items-center rounded-full border border-border">
                  <Icon className="size-3 text-foreground" strokeWidth={1.6} />
                </span>
                <span className="text-[14px] font-semibold text-foreground">{name}</span>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}