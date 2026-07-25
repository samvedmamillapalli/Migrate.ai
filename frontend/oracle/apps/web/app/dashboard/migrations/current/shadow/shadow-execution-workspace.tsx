"use client"

import * as React from "react"
import Link from "next/link"

import { Button, buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

import type { MigrationRun } from "../data"
import { CompletedShadowExecution } from "./completed-shadow-execution"
import {
  ShadowExecutionWindow,
  type ShadowExecutionWindowMode,
} from "./shadow-execution-window"
import type { LiveShadowExecutionData } from "./shadow-execution-state"

export function ShadowExecutionWorkspace({
  migration,
  liveData,
}: {
  migration: MigrationRun
  liveData: LiveShadowExecutionData
}) {
  const [windowMode, setWindowMode] =
    React.useState<ShadowExecutionWindowMode>("closed")

  return (
    <div className="relative flex flex-1 flex-col">
      <div className="flex items-center justify-between gap-3 px-4 pb-3 md:px-6">
        <Link
          href="/dashboard/migrations/current"
          className={cn(
            buttonVariants({ variant: "ghost", size: "sm" }),
            "text-muted-foreground hover:text-foreground -ml-2 font-mono text-[11px] tracking-tight"
          )}
        >
          ← Back to Current Migration
        </Link>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setWindowMode("open")}
        >
          Open Execution Window
        </Button>
      </div>

      <CompletedShadowExecution migration={migration} />

      <ShadowExecutionWindow
        data={liveData}
        mode={windowMode}
        onMinimize={() => setWindowMode("minimized")}
        onRestore={() => setWindowMode("open")}
        onClose={() => setWindowMode("closed")}
      />
    </div>
  )
}
