"use client"

import * as React from "react"
import { ChevronsUpDown, Database, Pencil, Plus, Users } from "lucide-react"

import { CreateWorkspaceDialog } from "@/components/create-workspace-dialog"
import { EditWorkspaceDialog } from "@/components/edit-workspace-dialog"
import { InviteMembersDialog } from "@/components/invite-members-dialog"
import { listWorkspaces, type Workspace } from "@/lib/api/endpoints"
import { getActiveWorkspaceId, getOwnerIdentity, setActiveWorkspaceId } from "@/lib/api/owner"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@workspace/ui/components/sidebar"

/**
 * Real workspace switcher — docs/FUTURE_WORKSPACES_PLAN.md. Replaces the
 * dead shadcn team-switcher.tsx template scaffolding (deleted, never wired
 * to any data). Reads/writes the active workspace via localStorage
 * (oracle:active_workspace_id, lib/api/owner.ts), same convention as owner
 * identity and the current-run pointer.
 *
 * Three things live here, per direct product feedback: the list of
 * workspaces (click a row to switch), adding one (+ New workspace ->
 * CreateWorkspaceDialog, a centered modal with a dimmed backdrop — not a
 * navigation to Settings), and editing one (pencil icon on each row ->
 * EditWorkspaceDialog, same modal treatment). Both dialogs report back into
 * this component's own state so a created/edited/deleted workspace shows up
 * in this list immediately, without a page reload.
 */
export function WorkspaceSwitcher() {
  const { isMobile } = useSidebar()
  const [workspaces, setWorkspaces] = React.useState<Workspace[] | null>(null)
  const [activeId, setActiveId] = React.useState<string>("")
  const [createOpen, setCreateOpen] = React.useState(false)
  const [editingWorkspace, setEditingWorkspace] = React.useState<Workspace | null>(null)
  const [invitingWorkspace, setInvitingWorkspace] =
    React.useState<Workspace | null>(null)

  const load = React.useCallback(async () => {
    const owner = getOwnerIdentity()
    try {
      const result = await listWorkspaces(owner || undefined)
      setWorkspaces(result.items)
      const stored = getActiveWorkspaceId()
      const stillExists = result.items.some((w) => w.id === stored)
      if (stored && stillExists) {
        setActiveId(stored)
      } else {
        const fallback = result.items.find((w) => w.is_default) ?? result.items[0]
        if (fallback) {
          setActiveId(fallback.id)
          setActiveWorkspaceId(fallback.id)
        } else {
          setActiveId("")
          setActiveWorkspaceId(null)
        }
      }
    } catch {
      // Best-effort — an empty/failed workspace list just means no
      // workspace-scoped filtering happens, not a broken sidebar.
      setWorkspaces([])
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  function selectWorkspace(id: string) {
    setActiveId(id)
    setActiveWorkspaceId(id)
    // Workspace-scoped views (history filter, run creation) read the
    // localStorage value directly on their own next render/fetch; a full
    // reload keeps every already-mounted page in sync without threading a
    // global state manager through the app for one value.
    window.location.reload()
  }

  function handleCreated(workspace: Workspace) {
    setWorkspaces((prev) => [...(prev ?? []), workspace])
    setActiveId(workspace.id)
    setActiveWorkspaceId(workspace.id)
  }

  function handleUpdated(workspace: Workspace) {
    setWorkspaces((prev) =>
      (prev ?? []).map((w) => (w.id === workspace.id ? workspace : w))
    )
  }

  function handleDeleted(workspaceId: string) {
    setWorkspaces((prev) => (prev ?? []).filter((w) => w.id !== workspaceId))
    if (activeId === workspaceId) {
      setActiveId("")
      setActiveWorkspaceId(null)
    }
  }

  const active = workspaces?.find((w) => w.id === activeId) ?? null

  if (workspaces === null) {
    return (
      <SidebarMenu>
        <SidebarMenuItem>
          <div className="text-muted-foreground flex items-center gap-2 px-2 py-1.5 text-xs">
            <Database className="size-3.5 animate-pulse" />
            <span className="group-data-[collapsible=icon]:hidden">Loading…</span>
          </div>
        </SidebarMenuItem>
      </SidebarMenu>
    )
  }

  return (
    <>
      <SidebarMenu>
        <SidebarMenuItem>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <SidebarMenuButton
                  size="lg"
                  className="data-open:bg-sidebar-accent data-open:text-sidebar-accent-foreground"
                />
              }
            >
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                <Database className="size-4" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">
                  {active?.name ?? "No workspace"}
                </span>
                <span className="text-muted-foreground truncate text-xs">
                  {active?.connection_label ?? (workspaces.length ? "No connection set" : "Create one below")}
                </span>
              </div>
              <ChevronsUpDown className="ml-auto" />
            </DropdownMenuTrigger>
            <DropdownMenuContent
              className="w-(--radix-dropdown-menu-trigger-width) min-w-64 rounded-lg"
              align="start"
              side={isMobile ? "bottom" : "right"}
              sideOffset={4}
            >
              <DropdownMenuGroup>
                <DropdownMenuLabel className="text-xs text-muted-foreground">
                  Workspaces
                </DropdownMenuLabel>
                {workspaces.length === 0 ? (
                  <div className="text-muted-foreground px-2 py-1.5 text-xs">
                    No workspaces yet.
                  </div>
                ) : (
                  workspaces.map((workspace) => (
                    <DropdownMenuItem
                      key={workspace.id}
                      onClick={() => selectWorkspace(workspace.id)}
                      className="group/ws-item gap-2 p-2"
                    >
                      <div className="flex size-6 items-center justify-center rounded-md border">
                        <Database className="size-3.5 shrink-0" />
                      </div>
                      <div className="min-w-0 flex-1 truncate">
                        <div className="truncate">{workspace.name}</div>
                        {workspace.connection_label ? (
                          <div className="text-muted-foreground truncate text-[11px]">
                            {workspace.connection_label}
                          </div>
                        ) : null}
                      </div>
                      <button
                        type="button"
                        aria-label={`Edit ${workspace.name}`}
                        className="text-muted-foreground hover:text-foreground hover:bg-muted shrink-0 rounded-md p-1 opacity-0 focus-visible:opacity-100 group-hover/ws-item:opacity-100"
                        onClick={(e) => {
                          e.stopPropagation()
                          setEditingWorkspace(workspace)
                        }}
                      >
                        <Pencil className="size-3.5" />
                      </button>
                    </DropdownMenuItem>
                  ))
                )}
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                {active ? (
                  <DropdownMenuItem
                    className="gap-2 p-2"
                    onClick={() => setInvitingWorkspace(active)}
                  >
                    <div className="flex size-6 items-center justify-center rounded-md border bg-transparent">
                      <Users className="size-4" />
                    </div>
                    <div className="font-medium text-muted-foreground">
                      Manage members
                    </div>
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem
                  className="gap-2 p-2"
                  onClick={() => setCreateOpen(true)}
                >
                  <div className="flex size-6 items-center justify-center rounded-md border bg-transparent">
                    <Plus className="size-4" />
                  </div>
                  <div className="font-medium text-muted-foreground">
                    New workspace
                  </div>
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>

      <CreateWorkspaceDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={handleCreated}
      />
      <EditWorkspaceDialog
        workspace={editingWorkspace}
        open={editingWorkspace !== null}
        onOpenChange={(open) => {
          if (!open) setEditingWorkspace(null)
        }}
        onUpdated={handleUpdated}
        onDeleted={handleDeleted}
      />
      <InviteMembersDialog
        workspace={invitingWorkspace}
        open={invitingWorkspace !== null}
        onOpenChange={(open) => {
          if (!open) setInvitingWorkspace(null)
        }}
      />
    </>
  )
}
