"use client"

import * as React from "react"

import {
  formatRelativeTime,
  mapShadowHold,
  teardownShadowClusterNow,
  type ShadowCluster,
} from "@/lib/api"
import { toneText } from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

/**
 * The shadow cluster's remaining lifetime, and the button that ends it early.
 *
 * After execute + measure finish, the cluster is deliberately kept alive for
 * `settings.shadow_hold_minutes` (default 5) instead of being torn down
 * immediately, so the comparison and row samples have a live cluster behind
 * them — see ShadowClusterStatus.HOLDING. This renders that countdown and
 * calls POST /runs/{id}/shadow-cluster/teardown-now to end it on demand.
 *
 * Deletion is offered for any status that still holds real cloud resources,
 * not just HOLDING: the endpoint is idempotent and safe to call mid-run, and
 * "stop paying for this now" should never be gated on reaching a particular
 * stage.
 */

const DELETABLE_STATUSES = new Set([
  "provisioning",
  "ready",
  "seeding",
  "migrating",
  "holding",
])

function formatRemaining(seconds: number | null): string {
  if (seconds == null) return "any moment now"
  if (seconds >= 60) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  return `${seconds}s`
}

export function ShadowTeardownControl({
  shadow,
  className,
}: {
  shadow: ShadowCluster | null
  className?: string
}) {
  const [now, setNow] = React.useState(() => Date.now())
  const [deleting, setDeleting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const status = (shadow?.status || "").toLowerCase()
  const isHolding = status === "holding"

  React.useEffect(() => {
    if (!isHolding) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [isHolding])

  if (!shadow) return null

  if (status === "destroyed") {
    return (
      <div className={cn("space-y-1.5 text-[13px]", className)}>
        <p className="text-foreground">
          Cluster destroyed — your shadow cluster no
          longer exists.
        </p>
        {shadow.destroyed_at ? (
          <p className="text-muted-foreground">
            torn down {formatRelativeTime(shadow.destroyed_at)} — no ongoing cost.
          </p>
        ) : null}
      </div>
    )
  }

  if (status === "destroying") {
    return (
      <p className={cn("text-muted-foreground text-[13px]", className)}>
        Tearing down your shadow cluster…
      </p>
    )
  }

  if (!DELETABLE_STATUSES.has(status)) return null

  const hold = mapShadowHold(shadow, now)

  const handleDelete = async () => {
    setDeleting(true)
    setError(null)
    try {
      await teardownShadowClusterNow(shadow.migration_run_id)
      // Deliberately leave `deleting` true — the next stream/poll tick flips
      // status to destroying/destroyed and re-renders this as terminal.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete shadow cluster")
      setDeleting(false)
    }
  }

  return (
    <div className={cn("space-y-2.5 text-[13px]", className)}>
      <p className="text-foreground">
        Your shadow cluster is live
        {isHolding ? " — held for inspection." : "."}
      </p>
      <p className="text-muted-foreground">
        {isHolding
          ? `Auto-deletes in ${formatRemaining(hold.secondsRemaining)}. Look over the comparison and row samples, then delete it early if you're done — no need to wait.`
          : "It is torn down automatically when the run finishes. Delete it now to stop immediately."}
      </p>
      <button
        type="button"
        onClick={() => void handleDelete()}
        disabled={deleting}
        className={cn(
          "rounded-md border px-2.5 py-1.5 text-[12px] font-semibold transition-colors",
          "border-[var(--tone-fail-border)]",
          toneText("fail"),
          "hover:bg-[var(--tone-fail-bg)] disabled:opacity-50"
        )}
      >
        {deleting ? "Deleting…" : "Delete shadow cluster now"}
      </button>
      {error ? <p className={toneText("fail")}>{error}</p> : null}
    </div>
  )
}
