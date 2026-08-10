"use client"

import { Boxes, Cpu, Database, Radio, Workflow } from "lucide-react"

import { TECHNOLOGIES } from "@/components/landing/site-data"
import { cn } from "@workspace/ui/lib/utils"

const ICONS = [Database, Boxes, Cpu, Workflow, Radio]

export function TechMarquee({ compact = false }: { compact?: boolean }) {
  const items = [...TECHNOLOGIES, ...TECHNOLOGIES]

  return (
    <section
      className={cn(
        "mx-auto w-full max-w-[1180px] px-6",
        compact ? "py-2" : "py-20"
      )}
    >
      {!compact ? (
        <p className="eyebrow text-muted-foreground text-center">
          Built on trusted technologies
        </p>
      ) : null}
      <div
        className={cn(
          "group/marquee relative overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]",
          compact ? "mt-0" : "mt-8"
        )}
      >
        <div
          className={cn(
            "animate-marquee flex w-max items-center",
            compact ? "gap-8" : "gap-16"
          )}
        >
          {items.map((name, i) => {
            const Icon = ICONS[i % ICONS.length]!
            return (
              <div
                key={`${name}-${i}`}
                className="flex shrink-0 items-center gap-2"
              >
                <span
                  className={cn(
                    "border-border grid place-items-center rounded-full border",
                    compact ? "size-5" : "size-6"
                  )}
                >
                  <Icon
                    className={cn(
                      "text-foreground",
                      compact ? "size-2.5" : "size-3"
                    )}
                    strokeWidth={1.6}
                  />
                </span>
                <span
                  className={cn(
                    "text-foreground font-semibold",
                    compact ? "text-[12px]" : "text-[14px]"
                  )}
                >
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
