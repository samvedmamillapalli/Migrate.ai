"use client"

import * as React from "react"

import { ApiError } from "@/lib/api/client"
import { runGrade, type Grade, type MigrationRun } from "@/lib/api/endpoints"
import { useLoadingWord } from "@/lib/loading-words"
import { Button } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

/**
 * "Grade" was previously only a data panel that appeared once the backend had
 * already graded a run — there was no visible action, and nothing told the user
 * what to do after a shadow finished. This is the action, shown in the three
 * places a user could plausibly be looking when the shadow completes: the
 * shadow execution page, the floating watch panel, and the run detail page.
 */
export function GradeRunAction({
  run,
  grade,
  onGraded,
  className,
  compact = false,
}: {
  run: MigrationRun | null
  grade: Grade | null
  onGraded?: (updated: MigrationRun) => void
  className?: string
  compact?: boolean
}) {
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const word = useLoadingWord(busy)

  // Only meaningful once the migration has actually run on the shadow.
  const executed =
    run?.workflow_status === "succeeded" || run?.status === "completed"
  if (!run || !executed) return null

  if (grade) {
    return (
      <p className={cn("text-muted-foreground text-[12.5px]", className)}>
        Graded — <span className="text-foreground">{grade.outcome_class}</span>.
        The result is saved to memory and informs the next prediction.
      </p>
    )
  }

  async function handleGrade() {
    if (!run) return
    setBusy(true)
    setError(null)
    try {
      const updated = await runGrade(run.id)
      onGraded?.(updated)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Grading failed"
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={cn("space-y-2", className)}>
      {!compact ? (
        <p className="text-muted-foreground text-[12.5px] leading-relaxed">
          The shadow run finished. Confirm the result to score the prediction
          against what actually happened and save the lesson for next time.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size={compact ? "sm" : undefined}
          disabled={busy}
          onClick={() => void handleGrade()}
        >
          {busy ? `${word}…` : "Confirm & grade result"}
        </Button>
      </div>
      {error ? (
        <p className="text-[var(--oracle-risk)] text-[12px]">{error}</p>
      ) : null}
    </div>
  )
}
