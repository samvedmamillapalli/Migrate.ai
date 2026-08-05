"use client"

import * as React from "react"
import { Trash2 } from "lucide-react"

import {
  createWorkspace,
  deleteWorkspace,
  listWorkspaces,
  type Workspace,
} from "@/lib/api/endpoints"
import { ApiError } from "@/lib/api/client"
import { getActiveWorkspaceId, getOwnerIdentity, setActiveWorkspaceId } from "@/lib/api/owner"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { EmptyNote, Label } from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

/**
 * Workspace management — docs/FUTURE_WORKSPACES_PLAN.md. A workspace scopes
 * runs to one target database; this panel is the create/list/delete surface
 * (linked from the sidebar switcher's "Manage workspaces").
 */
export function WorkspaceSettingsPanel() {
  const [workspaces, setWorkspaces] = React.useState<Workspace[] | null>(null)
  const [loadError, setLoadError] = React.useState<string | null>(null)

  const [name, setName] = React.useState("")
  const [databaseUrl, setDatabaseUrl] = React.useState("")
  const [creating, setCreating] = React.useState(false)
  const [createError, setCreateError] = React.useState<string | null>(null)

  const [deletingId, setDeletingId] = React.useState<string | null>(null)

  const refresh = React.useCallback(async () => {
    const owner = getOwnerIdentity()
    try {
      const result = await listWorkspaces(owner || undefined)
      setWorkspaces(result.items)
      setLoadError(null)
    } catch (err) {
      setLoadError(
        err instanceof ApiError ? err.message : "Could not load workspaces."
      )
      setWorkspaces([])
    }
  }, [])

  React.useEffect(() => {
    void refresh()
  }, [refresh])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      setCreateError("Name is required.")
      return
    }
    setCreating(true)
    setCreateError(null)
    try {
      const owner = getOwnerIdentity()
      const created = await createWorkspace({
        name: name.trim(),
        owner_identity: owner || null,
        database_url: databaseUrl.trim() || null,
      })
      setName("")
      setDatabaseUrl("")
      await refresh()
      // A first workspace becomes the obvious default to switch to; the
      // sidebar switcher itself already falls back to is_default/first on
      // its own next load, but setting it here means a same-tab user sees
      // it selected immediately without needing a reload first.
      if (!getActiveWorkspaceId()) {
        setActiveWorkspaceId(created.id)
      }
    } catch (err) {
      setCreateError(
        err instanceof ApiError ? err.message : "Could not create workspace."
      )
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(workspace: Workspace) {
    setDeletingId(workspace.id)
    try {
      await deleteWorkspace(workspace.id)
      if (getActiveWorkspaceId() === workspace.id) {
        setActiveWorkspaceId(null)
      }
      await refresh()
    } catch {
      // Best-effort — leaves the row in place so the user can retry;
      // deletion failing here (e.g. a transient network error) shouldn't
      // silently drop the row from view.
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div id="workspaces" className="scroll-mt-24">
      <Label className="mb-4">Workspaces</Label>
      <p className="text-muted-foreground mb-4 text-[13px] leading-relaxed">
        Each workspace stores one target database connection, so migrations
        against different databases don&apos;t require re-entering a
        connection URL every time. Runs created without a workspace still
        work exactly as before.
      </p>

      {loadError ? (
        <p className="mb-3 text-[12px] leading-snug text-destructive">{loadError}</p>
      ) : null}

      {workspaces === null ? (
        <p className="text-muted-foreground text-[13px]">Loading…</p>
      ) : workspaces.length === 0 ? (
        <EmptyNote>No workspaces yet — create one below.</EmptyNote>
      ) : (
        <div className="mb-4 space-y-2">
          {workspaces.map((workspace) => (
            <div
              key={workspace.id}
              className={cn(
                "border-border flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5"
              )}
            >
              <div className="min-w-0">
                <div className="text-foreground flex items-center gap-2 text-[13.5px] font-semibold">
                  <span className="truncate">{workspace.name}</span>
                  {workspace.is_default ? (
                    <span className="bg-muted text-muted-foreground rounded-full px-2 py-0.5 text-[10px] font-bold">
                      DEFAULT
                    </span>
                  ) : null}
                </div>
                <p className="text-muted-foreground truncate text-[12px]">
                  {workspace.connection_label ?? "No connection configured"}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={deletingId === workspace.id}
                onClick={() => void handleDelete(workspace)}
                aria-label={`Delete ${workspace.name}`}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}

      <form onSubmit={(e) => void handleCreate(e)} className="space-y-3 border-t border-border pt-4">
        <div>
          <Label className="mb-1.5">New workspace</Label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Production, Client A"
            className="h-10"
            maxLength={256}
          />
        </div>
        <div>
          <Input
            value={databaseUrl}
            onChange={(e) => setDatabaseUrl(e.target.value)}
            placeholder="postgresql://user:pass@host:26257/db (optional — can add later)"
            className="h-10 font-mono text-xs"
            autoComplete="off"
          />
          <p className="text-muted-foreground mt-1 text-[11.5px] leading-snug">
            Verified with a real connectivity check before saving. Leave blank
            to create the workspace without a connection yet.
          </p>
        </div>
        {createError ? (
          <p className="text-[12px] leading-snug text-destructive">{createError}</p>
        ) : null}
        <Button type="submit" variant="default" size="sm" disabled={creating}>
          {creating ? "Creating…" : "Create workspace"}
        </Button>
      </form>
    </div>
  )
}
