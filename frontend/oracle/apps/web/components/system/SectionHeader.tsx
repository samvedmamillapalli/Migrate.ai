import { cn } from "@workspace/ui/lib/utils"

import { oracleType } from "@/lib/oracle-tokens"

export type SectionHeaderProps = {
  title: string
  description?: string
  className?: string
  /** Constrain copy width (landing sections) */
  narrow?: boolean
}

/**
 * One job per section: title + optional supporting sentence.
 */
export function SectionHeader({
  title,
  description,
  className,
  narrow = true,
}: SectionHeaderProps) {
  return (
    <header className={cn(narrow && "max-w-3xl", className)}>
      <h2 className={cn(oracleType.title, "text-foreground")}>{title}</h2>
      {description ? (
        <p className={cn(oracleType.subtitle, "mt-3")}>{description}</p>
      ) : null}
    </header>
  )
}
