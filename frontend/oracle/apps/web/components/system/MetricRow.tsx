import { cn } from "@workspace/ui/lib/utils"

import { oracleType } from "@/lib/oracle-tokens"

export type MetricRowProps = {
  label: string
  predicted: string
  actual: string
  delta: string
  className?: string
}

/**
 * One predicted / actual / diff comparison row.
 */
export function MetricRow({
  label,
  predicted,
  actual,
  delta,
  className,
}: MetricRowProps) {
  return (
    <div className={cn("space-y-3", className)}>
      <p className="text-foreground text-sm font-medium tracking-tight">
        {label}
      </p>
      <div className="grid grid-cols-3 gap-4">
        <div className="space-y-1">
          <p className={oracleType.label}>Predicted</p>
          <p className={cn(oracleType.mono, "text-foreground")}>{predicted}</p>
        </div>
        <div className="space-y-1">
          <p className={oracleType.label}>Actual</p>
          <p className={cn(oracleType.mono, "text-foreground")}>{actual}</p>
        </div>
        <div className="space-y-1">
          <p className={oracleType.label}>Diff</p>
          <p className={cn(oracleType.mono, "text-foreground/70")}>{delta}</p>
        </div>
      </div>
    </div>
  )
}
