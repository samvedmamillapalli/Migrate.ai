"use client"

import * as React from "react"
import { Trash2 } from "lucide-react"

import { ApiError } from "@/lib/api/client"
import {
  deleteWorkspace,
  updateWorkspace,
  type Workspace,
} from "@/lib/api/endpoints"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/ui-kit"

/**
 * Centered modal for editing (rename / replace connection) or deleting one
 * workspace — docs/FUTURE_WORKSPACES_PLAN.md. Controlled by the caller (the
 * sidebar workspace switcher) so a successful save/delete can immediately
 * update that switcher's list without a page navigation.
 */
export function EditWorkspaceDialog({
  workspace,
  open,
  onOpenChange,
  onUpdated,
  onDeleted,
}: {
  workspace: Workspace | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onUpdated: (workspace: Workspace) => void
  onDeleted: (workspaceId: string) => void
}) {
  const [name, setName] = React.useState("")
  const [databaseUrl, setDatabaseUrl] = React.useState("")
  const [saving, setSaving] = React.useState(false)
  const [deleting, setDeleting] = React.useState(false)
  const [confirmingDelete, setConfirmingDelete] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (workspace) {
      setName(workspace.name)
      setDatabaseUrl("")
      setError(null)
      setConfirmingDelete(false)
    }
  }, [workspace])

  function handleOpenChange(next: boolean) {
    if (!next) {
      setError(null)
      setConfirmingDelete(false)
    }
    onOpenChange(next)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!workspace) return
    if (!name.trim()) {
      setError("Name is required.")
      return
    }
    setSaving(true)
    setError(null)
    try {
      const updated = await updateWorkspace(workspace.id, {
        name: name.trim() !== workspace.name ? name.trim() : null,
        database_url: databaseUrl.trim() || null,
      })
      onUpdated(updated)
      handleOpenChange(false)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not update workspace."
      )
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!workspace) return
    if (!confirmingDelete) {
      setConfirmingDelete(true)
      return
    }
    setDeleting(true)
    setError(null)
    try {
      await deleteWorkspace(workspace.id)
      onDeleted(workspace.id)
      handleOpenChange(false)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not delete workspace."
      )
      setDeleting(false)
      setConfirmingDelete(false)
    }
  }

  if (!workspace) return null

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md" showCloseButton>
        <form onSubmit={(e) => void handleSubmit(e)}>
          <DialogHeader>
            <DialogTitle>Edit workspace</DialogTitle>
            <DialogDescription>
              Rename this workspace or replace its stored connection.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-4">
            <div>
              <Label className="mb-1.5">Name</Label>
              <Input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="h-10"
                maxLength={256}
              />
            </div>
            <div>
              <Label className="mb-1.5">
                {workspace.connection_label
                  ? "Replace connection"
                  : "Add connection"}
              </Label>
              <Input
                value={databaseUrl}
                onChange={(e) => setDatabaseUrl(e.target.value)}
                placeholder={
                  workspace.connection_label ??
                  "postgresql://user:pass@host:26257/db"
                }
                className="h-10 font-mono text-xs"
                autoComplete="off"
              />
              <p className="text-muted-foreground mt-1.5 text-[11.5px] leading-snug">
                {workspace.connection_label
                  ? `Currently: ${workspace.connection_label}. Verified with a real connectivity check before saving. Leave blank to keep it.`
                  : "Verified with a real connectivity check before saving. Leave blank to skip."}
              </p>
            </div>
            {error ? (
              <p className="text-[12px] leading-snug text-destructive">{error}</p>
            ) : null}
          </div>

          <DialogFooter className="sm:justify-between">
            <Button
              type="button"
              variant="outline"
              onClick={() => void handleDelete()}
              disabled={saving || deleting}
              className={
                confirmingDelete
                  ? "border-destructive text-destructive hover:bg-destructive/10"
                  : "text-destructive hover:bg-destructive/10"
              }
            >
              <Trash2 className="size-3.5" />
              {deleting
                ? "Deleting…"
                : confirmingDelete
                  ? "Click again to confirm"
                  : "Delete"}
            </Button>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => handleOpenChange(false)}
                disabled={saving || deleting}
              >
                Cancel
              </Button>
              <Button type="submit" variant="default" disabled={saving || deleting}>
                {saving ? "Saving…" : "Save"}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
