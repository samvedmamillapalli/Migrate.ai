"use client"

import {
  BedrockLogo,
  CockroachDBLogo,
  EventBridgeLogo,
  ModelContextProtocolLogo,
  StepFunctionsLogo,
  TitanIcon,
  VectorIndexIcon,
} from "@/components/landing/tech-logos"
import { cn } from "@workspace/ui/lib/utils"

/**
 * The 3 CockroachDB features actually shipped and fully integrated (see
 * docs/HACKATHON_TOOLS.md — CockroachDB Cloud itself, plus the two tool
 * integrations judging checks for) alongside the AWS services in the same
 * pipeline. Real brand marks where one exists; a themed icon where it
 * doesn't (Titan has no public logo of its own, and "Distributed Vector
 * Index" isn't a product with a logo at all).
 */
const TECH_ITEMS = [
  { name: "CockroachDB", Icon: CockroachDBLogo },
  { name: "Distributed Vector Index", Icon: VectorIndexIcon },
  { name: "Managed MCP Server", Icon: ModelContextProtocolLogo },
  { name: "Amazon Bedrock", Icon: BedrockLogo },
  { name: "Amazon Titan", Icon: TitanIcon },
  { name: "AWS Step Functions", Icon: StepFunctionsLogo },
  { name: "Amazon EventBridge", Icon: EventBridgeLogo },
] as const

export function TechMarquee({ compact = false }: { compact?: boolean }) {
  const items = [...TECH_ITEMS, ...TECH_ITEMS]

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
          {items.map(({ name, Icon }, i) => (
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
          ))}
        </div>
      </div>
    </section>
  )
}
