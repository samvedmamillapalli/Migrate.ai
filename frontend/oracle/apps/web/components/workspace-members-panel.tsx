"use client"

import * as React from "react"
import { UserMinus } from "lucide-react"

import { ApiError } from "@/lib/api/client"
import {
  listWorkspaceMembers,
  removeWorkspaceMember,
  type Workspace,
  type WorkspaceMember,
} from "@/lib/api/endpoints"
import { Button } from "@workspace/ui/components/button"
import { EmptyNote, Label } from "@workspace/ui/components/ui-kit"

/**
 * Accepted members of one workspace, with a remove button per row — the same
 * visual pattern as the workspace rows in WorkspaceSettingsPanel (border
 * rounded-lg px-3 py-2.5 row, trailing icon button). Rendered for the
 * currently active workspace; the parent passes `key={workspace?.id}` so it
 * reloads when the active workspace changes.
 *
 * Backed by real workspace_members rows (docs/backendfix.md 2026-08-07).
 * The owner's row can't be removed (server rejects it); the frontend
 * mirrors that by disabling the button for role === "owner".
 */
export function WorkspaceMembersPanel({
  workspace,
}: {
  workspace: Workspace | null
}) {
  const [members, setMembers] = React.useState<WorkspaceMember[] | null>(null)
  // Only ever set from a *remove* action, never from the initial load — a
  // transient load failure just falls back to the empty state below rather
  // than surfacing raw backend text to the user.
  const [actionError, setActionError] = React.useState<string | null>(null)
  const [removingId, setRemovingId] = React.useState<string | null>(null)

  const refresh = React.useCallback(async () => {
    if (!workspace) {
      setMembers(null)
      return
    }
    try {
      const result = await listWorkspaceMembers(workspace.id)
      setMembers(result.items)
    } catch {
      setMembers([])
    }
  }, [workspace])

  React.useEffect(() => {
    void refresh()
  }, [refresh])

  async function handleRemove(member: WorkspaceMember) {
    if (!workspace) return
    setRemovingId(member.id)
    setActionError(null)
    try {
      await removeWorkspaceMember(workspace.id, member.id)
      setMembers((prev) => (prev ?? []).filter((item) => item.id !== member.id))
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not remove that member."
      )
    } finally {
      setRemovingId(null)
    }
  }

  return (
    <div id="members" className="scroll-mt-24">
      <Label className="mb-4">
        Members{workspace ? ` — ${workspace.name}` : ""}
      </Label>
      {workspace ? null : (
        <p className="text-muted-foreground mb-4 text-[13px] leading-relaxed">
          Create or select a workspace to see who has access to it.
        </p>
      )}

      {actionError ? (
        <p className="mb-3 text-[12px] leading-snug text-destructive">
          {actionError}
        </p>
      ) : null}

      {!workspace ? (
        <EmptyNote>No workspace selected.</EmptyNote>
      ) : members === null ? (
        <p className="text-muted-foreground text-[13px]">Loading…</p>
      ) : members.length === 0 ? (
        <EmptyNote>No members yet — invite someone to this workspace.</EmptyNote>
      ) : (
        <div className="space-y-2">
          {members.map((member) => (
            <div
              key={member.id}
              className="border-border flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5"
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <div className="bg-muted text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold uppercase">
                  {(member.display_name ?? member.user_identity).slice(0, 2)}
                </div>
                <div className="min-w-0">
                  <div className="text-foreground truncate text-[13.5px] font-semibold">
                    {member.display_name ?? member.user_identity}
                  </div>
                  {member.email ? (
                    <p className="text-muted-foreground truncate text-[12px]">
                      {member.email}
                    </p>
                  ) : null}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className="text-muted-foreground text-[10.5px] font-bold tracking-wide uppercase">
                  {member.role}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={removingId === member.id || member.role === "owner"}
                  onClick={() => void handleRemove(member)}
                  aria-label={`Remove ${member.display_name ?? member.user_identity}`}
                >
                  <UserMinus className="size-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
