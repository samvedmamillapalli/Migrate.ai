"use client"

import * as React from "react"

import { ApiError } from "@/lib/api/client"
import { createWorkspace, type Workspace } from "@/lib/api/endpoints"
import { getOwnerIdentity } from "@/lib/api/owner"
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
 * Centered modal (dimmed backdrop via DialogOverlay) for creating a
 * workspace — docs/FUTURE_WORKSPACES_PLAN.md. Controlled by the caller
 * (the sidebar workspace switcher) so a successful create can immediately
 * update that switcher's list without a page navigation.
 */
export function CreateWorkspaceDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (workspace: Workspace) => void
}) {
  const [name, setName] = React.useState("")
  const [databaseUrl, setDatabaseUrl] = React.useState("")
  const [creating, setCreating] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  function reset() {
    setName("")
    setDatabaseUrl("")
    setError(null)
    setCreating(false)
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset()
    onOpenChange(next)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      setError("Name is required.")
      return
    }
    setCreating(true)
    setError(null)
    try {
      const created = await createWorkspace({
        name: name.trim(),
        owner_identity: getOwnerIdentity() || null,
        database_url: databaseUrl.trim() || null,
      })
      onCreated(created)
      handleOpenChange(false)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not create workspace."
      )
      setCreating(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md" showCloseButton>
        <form onSubmit={(e) => void handleSubmit(e)}>
          <DialogHeader>
            <DialogTitle>New workspace</DialogTitle>
            <DialogDescription>
              A workspace stores one target database connection, so runs
              created under it don&apos;t need a connection URL re-entered
              every time.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-4">
            <div>
              <Label className="mb-1.5">Name</Label>
              <Input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Production, Client A"
                className="h-10"
                maxLength={256}
              />
            </div>
            <div>
              <Label className="mb-1.5">Connection (optional)</Label>
              <Input
                value={databaseUrl}
                onChange={(e) => setDatabaseUrl(e.target.value)}
                placeholder="postgresql://user:pass@host:26257/db"
                className="h-10 font-mono text-xs"
                autoComplete="off"
              />
              <p className="text-muted-foreground mt-1.5 text-[11.5px] leading-snug">
                Verified with a real connectivity check before saving. Leave
                blank to add a connection later.
              </p>
            </div>
            {error ? (
              <p className="text-[12px] leading-snug text-destructive">{error}</p>
            ) : null}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={creating}
            >
              Cancel
            </Button>
            <Button type="submit" variant="default" disabled={creating}>
              {creating ? "Creating…" : "Create workspace"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
