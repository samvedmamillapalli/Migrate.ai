"use client"

import * as React from "react"
import { Trash2, UserPlus } from "lucide-react"

import { InviteMembersDialog } from "@/components/invite-members-dialog"
import { WorkspaceMembersPanel } from "@/components/workspace-members-panel"
import {
  createWorkspace,
  deleteWorkspace,
  getGithubIntegrationStatus,
  listWorkspaces,
  updateWorkspace,
  type GithubIntegrationStatus,
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
 * (linked from the sidebar switcher's "Manage workspaces"). Each row also
 * opens the invite dialog (UserPlus) and the panel below lists the active
 * workspace's accepted members.
 */
export function WorkspaceSettingsPanel() {
  const [workspaces, setWorkspaces] = React.useState<Workspace[] | null>(null)
  const [loadError, setLoadError] = React.useState<string | null>(null)

  const [name, setName] = React.useState("")
  const [databaseUrl, setDatabaseUrl] = React.useState("")
  const [creating, setCreating] = React.useState(false)
  const [createError, setCreateError] = React.useState<string | null>(null)

  const [deletingId, setDeletingId] = React.useState<string | null>(null)
  const [invitingWorkspace, setInvitingWorkspace] =
    React.useState<Workspace | null>(null)

  // GitHub PR integration (docs/GITHUB_APP_SETUP.md) — repo linking.
  const [editingRepoId, setEditingRepoId] = React.useState<string | null>(null)
  const [repoInput, setRepoInput] = React.useState("")
  const [globInput, setGlobInput] = React.useState("")
  const [repoSaving, setRepoSaving] = React.useState(false)
  const [repoError, setRepoError] = React.useState<string | null>(null)
  const [github, setGithub] = React.useState<GithubIntegrationStatus | null>(null)

  React.useEffect(() => {
    // Best-effort: the GitHub section degrades to "not configured" guidance
    // rather than breaking the whole settings page if this call fails.
    void getGithubIntegrationStatus()
      .then(setGithub)
      .catch(() => setGithub(null))
  }, [])

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

  function startEditRepo(workspace: Workspace) {
    setEditingRepoId(workspace.id)
    setRepoInput(workspace.github_repo_full_name ?? "")
    setGlobInput(
      workspace.github_migration_glob || "backend/alembic/versions/*.py"
    )
    setRepoError(null)
  }

  async function handleSaveRepo(workspace: Workspace) {
    setRepoSaving(true)
    setRepoError(null)
    try {
      const trimmed = repoInput.trim()
      await updateWorkspace(workspace.id, {
        github_repo_full_name: trimmed || null,
        clear_github_repo: trimmed.length === 0,
        github_migration_glob: globInput.trim() || null,
      })
      setEditingRepoId(null)
      await refresh()
    } catch (err) {
      // The server verifies the GitHub App can actually see this repo, so
      // its message ("not installed on ..." + install link) is the useful
      // one — surface it verbatim rather than a generic failure.
      setRepoError(
        err instanceof ApiError ? err.message : "Could not link this repo."
      )
    } finally {
      setRepoSaving(false)
    }
  }

  async function handleUnlinkRepo(workspace: Workspace) {
    setRepoSaving(true)
    setRepoError(null)
    try {
      await updateWorkspace(workspace.id, { clear_github_repo: true })
      setEditingRepoId(null)
      await refresh()
    } catch (err) {
      setRepoError(
        err instanceof ApiError ? err.message : "Could not unlink this repo."
      )
    } finally {
      setRepoSaving(false)
    }
  }

  // The members section below always reflects the currently active
  // workspace (same localStorage convention as the sidebar switcher).
  const activeWorkspace =
    workspaces?.find((workspace) => workspace.id === getActiveWorkspaceId()) ??
    null

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
              className={cn("border-border rounded-lg border px-3 py-2.5")}
            >
              <div className="flex items-center justify-between gap-3">
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
                  <p className="text-muted-foreground truncate text-[11.5px]">
                    {workspace.github_repo_full_name
                      ? `GitHub: ${workspace.github_repo_full_name}`
                      : "No GitHub repo linked"}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => startEditRepo(workspace)}
                  >
                    {workspace.github_repo_full_name ? "Edit repo" : "Link repo"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setInvitingWorkspace(workspace)}
                    aria-label={`Invite people to ${workspace.name}`}
                  >
                    <UserPlus className="size-3.5" />
                  </Button>
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
              </div>

              {editingRepoId === workspace.id ? (
                <div className="border-border mt-3 space-y-2.5 border-t pt-3">
                  {github && !github.configured ? (
                    <p className="bg-muted rounded-md px-2.5 py-2 text-[11.5px] leading-snug">
                      This server has no GitHub App configured, so linking a
                      repo won&apos;t do anything yet. See{" "}
                      <span className="font-mono">docs/GITHUB_APP_SETUP.md</span>.
                    </p>
                  ) : (
                    <div className="bg-muted rounded-md px-2.5 py-2 text-[11.5px] leading-snug">
                      <span className="font-semibold">Step 1:</span> install the
                      Migration Oracle GitHub App on the repo you want to watch.
                      {github?.install_url ? (
                        <>
                          {" "}
                          <a
                            href={github.install_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary font-semibold underline underline-offset-2"
                          >
                            Install on GitHub →
                          </a>
                        </>
                      ) : null}
                      <br />
                      <span className="font-semibold">Step 2:</span> enter that
                      repo below. We&apos;ll check the App can actually see it
                      before saving.
                    </div>
                  )}
                  <div>
                    <Label className="mb-1 text-[11px]">
                      GitHub repo (owner/repo)
                    </Label>
                    <Input
                      value={repoInput}
                      onChange={(e) => setRepoInput(e.target.value)}
                      placeholder="e.g. my-org/my-service"
                      className="h-9 font-mono text-xs"
                      autoComplete="off"
                    />
                  </div>
                  <div>
                    <Label className="mb-1 text-[11px]">
                      Migration file glob
                    </Label>
                    <Input
                      value={globInput}
                      onChange={(e) => setGlobInput(e.target.value)}
                      placeholder="backend/alembic/versions/*.py"
                      className="h-9 font-mono text-xs"
                      autoComplete="off"
                    />
                    <p className="text-muted-foreground mt-1 text-[11px] leading-snug">
                      Which changed files in a PR count as a migration. Use{" "}
                      <span className="font-mono">migrations/*.sql</span> for
                      plain SQL files, or{" "}
                      <span className="font-mono">
                        backend/alembic/versions/*.py
                      </span>{" "}
                      for Alembic (the SQL must be inside an{" "}
                      <span className="font-mono">op.execute(...)</span> call).
                    </p>
                  </div>
                  {repoError ? (
                    <p className="text-destructive text-[12px] leading-snug">
                      {repoError}
                    </p>
                  ) : null}
                  <div className="flex items-center gap-2">
                    <Button
                      variant="default"
                      size="sm"
                      disabled={repoSaving}
                      onClick={() => void handleSaveRepo(workspace)}
                    >
                      {repoSaving ? "Saving…" : "Save"}
                    </Button>
                    {workspace.github_repo_full_name ? (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={repoSaving}
                        onClick={() => void handleUnlinkRepo(workspace)}
                      >
                        Unlink
                      </Button>
                    ) : null}
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={repoSaving}
                      onClick={() => setEditingRepoId(null)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : null}
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

      <div className="border-border mt-6 border-t pt-5">
        <WorkspaceMembersPanel
          key={activeWorkspace?.id ?? "none"}
          workspace={activeWorkspace}
        />
      </div>

      <InviteMembersDialog
        workspace={invitingWorkspace}
        open={invitingWorkspace !== null}
        onOpenChange={(open) => {
          if (!open) setInvitingWorkspace(null)
        }}
      />
    </div>
  )
}
