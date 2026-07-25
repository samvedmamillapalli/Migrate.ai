"use client"

import { MinusIcon, XIcon } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

import { LiveShadowExecutionContent } from "./live-shadow-execution-content"
import type { LiveShadowExecutionData } from "./shadow-execution-state"

export type ShadowExecutionWindowMode = "open" | "minimized" | "closed"

type ShadowExecutionWindowProps = {
  data: LiveShadowExecutionData
  mode: ShadowExecutionWindowMode
  onMinimize: () => void
  onRestore: () => void
  onClose: () => void
}

export function ShadowExecutionWindow({
  data,
  mode,
  onMinimize,
  onRestore,
  onClose,
}: ShadowExecutionWindowProps) {
  if (mode === "closed") {
    return null
  }

  if (mode === "minimized") {
    return (
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex justify-center p-4">
        <div className="pointer-events-auto border-border bg-background flex w-full max-w-md items-center justify-between gap-3 rounded-lg border px-3 py-2 shadow-lg">
          <div className="min-w-0">
            <p className="text-foreground truncate font-mono text-xs tracking-tight">
              {data.clusterId}
            </p>
            <div className="mt-0.5 flex items-center gap-1.5">
              <span
                aria-hidden
                className="size-1.5 rounded-full bg-[var(--oracle-verified)]"
              />
              <span className="font-mono text-[10px] tracking-[0.12em] text-[var(--oracle-verified)] uppercase">
                {data.statusLabel}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onRestore}
              className="font-mono text-[10px] tracking-tight uppercase"
            >
              Restore
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={onClose}
              aria-label="Close execution window"
            >
              <XIcon />
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6">
      <button
        type="button"
        aria-label="Dismiss execution window backdrop"
        className="absolute inset-0 bg-black/55"
        onClick={onMinimize}
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Shadow execution window"
        className={cn(
          "border-border bg-background relative z-10 flex w-[min(92vw,1320px)] flex-col overflow-hidden rounded-lg border shadow-2xl",
          "h-[min(85vh,900px)] max-h-[85vh]"
        )}
      >
        <header className="border-border flex shrink-0 items-start justify-between gap-3 border-b px-4 py-3">
          <div className="min-w-0 space-y-0.5">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
              <p className="text-foreground text-sm font-medium tracking-tight">
                Shadow Execution
              </p>
              <p className="text-foreground/90 font-mono text-xs tracking-tight">
                {data.clusterId}
              </p>
            </div>
            <p className="text-muted-foreground font-mono text-[11px] tracking-tight">
              {data.engine}
              <span className="text-muted-foreground/40 mx-1.5">·</span>
              {data.lifecycle}
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <div className="mr-1 flex items-center gap-1.5">
              <span
                aria-hidden
                className="size-1.5 rounded-full bg-[var(--oracle-verified)]"
              />
              <span className="font-mono text-[10px] tracking-[0.14em] text-[var(--oracle-verified)] uppercase">
                {data.statusLabel}
              </span>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={onMinimize}
              aria-label="Minimize execution window"
            >
              <MinusIcon />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onClick={onClose}
              aria-label="Close execution window"
            >
              <XIcon />
            </Button>
          </div>
        </header>

        <LiveShadowExecutionContent data={data} />
      </div>
    </div>
  )
}
