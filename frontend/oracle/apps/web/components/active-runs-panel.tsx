"use client"

import * as React from "react"
import Link from "next/link"
import { motion } from "motion/react"

import { listRuns } from "@/lib/api/endpoints"
import { mapRunListItem } from "@/lib/api/map-run"
import { getActiveWorkspaceId, getOwnerIdentity } from "@/lib/api/owner"
import { AUTH_READY_EVENT } from "@/lib/api/clerk-token"
import {
  EmptyNote,
  Label,
  Panel,
  SkeletonLines,
  SqlBlock,
  StatusPill,
} from "@workspace/ui/components/ui-kit"

// Non-terminal statuses — docs/FUTURE_CONCURRENT_SHADOW_PLAN.md: the backend
// already lets one owner run several of these concurrently (no per-owner
// admission gate by default); this panel is the missing piece that makes
// that visible, since the Current Migration page otherwise assumes one run
// in focus.
const ACTIVE_STATUSES = "pending,predicting,awaiting_approval,running"

/**
 * "Your active runs" — every non-terminal run for the signed-in owner, with
 * a link into each one's own page. Renders nothing (not even an empty
 * state) when there's at most one active run and it's already the run in
 * focus, so this panel only earns its space when it's telling you something
 * the rest of the page doesn't already show.
 */
export function ActiveRunsPanel({
  currentRunId,
}: {
  currentRunId?: string | null
}) {
  const [items, setItems] = React.useState<
    ReturnType<typeof mapRunListItem>[] | null
  >(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const owner = getOwnerIdentity()
        const workspaceId = getActiveWorkspaceId()
        const res = await listRuns({
          limit: 20,
          status_in: ACTIVE_STATUSES,
          exclude_kinds: "chaos,debug",
          order_by: "created_at",
          order_dir: "desc",
          ...(owner ? { owner_identity: owner } : {}),
          ...(workspaceId ? { workspace_id: workspaceId } : {}),
        })
        if (cancelled) return
        setItems(res.items.map(mapRunListItem))
      } catch {
        if (!cancelled) setItems(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    // See lib/api/clerk-token.ts (AUTH_READY_EVENT) — a ticket/magic-link
    // sign-in can resolve Clerk's auth state after this first load() already
    // lost the race and swallowed a 401 into the empty/null-items state.
    window.addEventListener(AUTH_READY_EVENT, load)
    return () => {
      cancelled = true
      window.removeEventListener(AUTH_READY_EVENT, load)
    }
  }, [])

  if (loading) {
    return (
      <Panel className="px-6 py-5">
        <Label className="mb-4">Active Runs</Label>
        <SkeletonLines lines={2} />
      </Panel>
    )
  }

  if (!items || items.length === 0) return null

  // Only the run in focus, and nothing else is active — the rest of this
  // page already shows it, so the panel would be pure noise.
  if (items.length === 1 && items[0]!.id === currentRunId) return null

  return (
    <Panel className="px-6 py-5">
      <div className="mb-4 flex items-center gap-2">
        <Label>Active Runs</Label>
        <span className="rounded-full border border-[var(--tone-info-border)] bg-[var(--tone-info-bg)] px-2 py-0.5 text-[11px] font-bold text-[var(--tone-info-fg)]">
          {items.length}
        </span>
      </div>
      {items.length === 0 ? (
        <EmptyNote>No other runs in progress right now.</EmptyNote>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <motion.div key={item.id} whileHover={{ x: 2 }}>
              <Link
                href={`/dashboard/migrations/${item.id}`}
                className="bg-muted/70 hover:bg-muted flex flex-wrap items-center justify-between gap-3 rounded-lg px-4 py-3 transition-colors"
              >
                <SqlBlock className="min-w-0 flex-1">
                  {item.sqlSnippet}
                </SqlBlock>
                <div className="flex items-center gap-3 text-[12px]">
                  {item.id === currentRunId ? (
                    <span className="text-muted-foreground font-semibold">
                      current
                    </span>
                  ) : null}
                  <StatusPill status={item.status} />
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      )}
    </Panel>
  )
}
