import type { ReactNode } from "react"

import { cn } from "@workspace/ui/lib/utils"

import { oracleRadius } from "@/lib/oracle-tokens"

export type DeveloperPanelProps = {
  children: ReactNode
  className?: string
  /** Optional chrome slot (traffic lights, title) */
  chrome?: ReactNode
  /** Optional app header below chrome */
  header?: ReactNode
  /** Optional footer / terminal region */
  footer?: ReactNode
}

/**
 * Single outer application surface — one border, no nested glass.
 */
export function DeveloperPanel({
  children,
  className,
  chrome,
  header,
  footer,
}: DeveloperPanelProps) {
  return (
    <div
      className={cn(
        "border-border/60 bg-card overflow-hidden border",
        oracleRadius.panel,
        className
      )}
    >
      {chrome ? (
        <div className="border-border/60 relative flex h-10 items-center border-b px-4">
          {chrome}
        </div>
      ) : null}
      {header ? (
        <div className="border-border/60 border-b px-5 py-3.5">{header}</div>
      ) : null}
      <div>{children}</div>
      {footer ? (
        <div className="border-border/60 border-t">{footer}</div>
      ) : null}
    </div>
  )
}
