"use client"

import { Boxes, Cpu, Database, Radio, Workflow } from "lucide-react"

import { TECHNOLOGIES } from "@/components/landing/site-data"

const ICONS = [Database, Boxes, Cpu, Workflow, Radio]

export function TechMarquee() {
  const items = [...TECHNOLOGIES, ...TECHNOLOGIES]

  return (
    <section className="mx-auto w-full max-w-[1180px] px-6 py-20">
      <p className="eyebrow text-muted-foreground text-center">
        Built on trusted technologies
      </p>
      <div className="group/marquee relative mt-8 overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]">
        <div className="animate-marquee flex w-max items-center gap-16">
          {items.map((name, i) => {
            const Icon = ICONS[i % ICONS.length]!
            return (
              <div
                key={`${name}-${i}`}
                className="flex shrink-0 items-center gap-2.5"
              >
                <span className="border-border grid size-6 place-items-center rounded-full border">
                  <Icon
                    className="text-foreground size-3"
                    strokeWidth={1.6}
                  />
                </span>
                <span className="text-foreground text-[14px] font-semibold">
                  {name}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
