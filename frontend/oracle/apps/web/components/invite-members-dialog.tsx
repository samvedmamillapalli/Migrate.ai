"use client"

import * as React from "react"
import { AtSign, Check, Copy, Link2, Mail, RefreshCw, X } from "lucide-react"

import { ApiError } from "@/lib/api/client"
import {
  createWorkspaceInvite,
  listWorkspaceInvites,
  revokeWorkspaceInvite,
  type Workspace,
  type WorkspaceInvite,
  type WorkspaceInviteMethod,
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
import { EmptyNote, Label } from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

/**
 * Invite teammates to one workspace — the invite entry point behind the
 * "Invite people" button in workspace settings and the switcher's "Manage
 * members" item. Modeled on CreateWorkspaceDialog (shadcn-style Dialog,
 * local state, inline error text, no toast).
 *
 * Three invite methods in one dialog: email (validated client-side), GitHub
 * (debounced lookup against GitHub's public API so the inviter confirms the
 * handle first), and a shareable link (generated on demand, copyable,
 * revocable). Below the tabs: this workspace's pending invites with a revoke
 * button per row, reusing the workspace-row visual pattern.
 *
 * Backed by real workspace_invites rows (docs/backendfix.md 2026-08-07) —
 * roster only: accepting an invite adds a workspace_members row, which
 * grants visibility of the workspace, not access to its migration runs.
 */
export function InviteMembersDialog({
  workspace,
  open,
  onOpenChange,
}: {
  workspace: Workspace | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [tab, setTab] = React.useState<"email" | "github" | "link">("email")

  const [email, setEmail] = React.useState("")
  const [githubUsername, setGithubUsername] = React.useState("")
  const [githubUser, setGithubUser] = React.useState<{
    login: string
    name: string | null
    avatar_url: string
  } | null>(null)
  const [githubStatus, setGithubStatus] = React.useState<
    "idle" | "checking" | "missing" | "error"
  >("idle")

  const [sending, setSending] = React.useState(false)
  const [sendError, setSendError] = React.useState<string | null>(null)
  const [sentNotice, setSentNotice] = React.useState<string | null>(null)

  // Set after creating an email invite SES couldn't deliver, or any GitHub
  // invite (GitHub has no API to message an arbitrary user — there is no
  // "sent" state for that method, only a link the owner shares themselves).
  const [manualShareInvite, setManualShareInvite] =
    React.useState<WorkspaceInvite | null>(null)
  const [manualCopied, setManualCopied] = React.useState(false)
  const manualShareUrl = manualShareInvite?.token
    ? `${typeof window !== "undefined" ? window.location.origin : ""}/invite/${manualShareInvite.token}`
    : ""

  const [linkInvite, setLinkInvite] = React.useState<WorkspaceInvite | null>(
    null
  )
  const [linkLoading, setLinkLoading] = React.useState(false)
  const [copied, setCopied] = React.useState(false)

  const [invites, setInvites] = React.useState<WorkspaceInvite[]>([])
  const [invitesLoaded, setInvitesLoaded] = React.useState(false)
  const [revokingId, setRevokingId] = React.useState<string | null>(null)

  const pendingInvites = invites.filter((invite) => invite.status === "pending")

  const inviteUrl = linkInvite?.token
    ? `${typeof window !== "undefined" ? window.location.origin : ""}/invite/${linkInvite.token}`
    : ""

  const refreshInvites = React.useCallback(async () => {
    if (!workspace) return
    try {
      const result = await listWorkspaceInvites(workspace.id)
      setInvites(result.items)
    } catch {
      // Best-effort — the list just stays empty rather than blocking the
      // whole dialog on an invite-lookup failure.
      setInvites([])
    } finally {
      setInvitesLoaded(true)
    }
  }, [workspace])

  // Reset + reload every time the dialog opens for a (new) workspace.
  React.useEffect(() => {
    if (!open || !workspace) return
    setTab("email")
    setEmail("")
    setGithubUsername("")
    setGithubUser(null)
    setGithubStatus("idle")
    setLinkInvite(null)
    setCopied(false)
    setManualShareInvite(null)
    setManualCopied(false)
    setSending(false)
    setSendError(null)
    setSentNotice(null)
    setInvites([])
    setInvitesLoaded(false)
    void refreshInvites()
  }, [open, workspace, refreshInvites])

  // Debounced GitHub username lookup — the inviter confirms they typed the
  // right handle before the invite is sent.
  React.useEffect(() => {
    if (tab !== "github") return
    const username = githubUsername.trim()
    if (!username) {
      setGithubUser(null)
      setGithubStatus("idle")
      return
    }
    let cancelled = false
    setGithubStatus("checking")
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const res = await fetch(
            `https://api.github.com/users/${encodeURIComponent(username)}`
          )
          if (cancelled) return
          if (res.status === 404) {
            setGithubUser(null)
            setGithubStatus("missing")
            return
          }
          if (!res.ok) {
            setGithubUser(null)
            setGithubStatus("error")
            return
          }
          const data = (await res.json()) as {
            login: string
            name: string | null
            avatar_url: string
          }
          if (cancelled) return
          setGithubUser(data)
          setGithubStatus("idle")
        } catch {
          if (cancelled) return
          setGithubUser(null)
          setGithubStatus("error")
        }
      })()
    }, 450)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [tab, githubUsername])

  // Link tab: reuse the workspace's pending link invite if one exists,
  // otherwise generate a fresh one.
  React.useEffect(() => {
    if (!open || !workspace || tab !== "link" || linkInvite) return
    let cancelled = false
    setLinkLoading(true)
    void (async () => {
      try {
        const result = await listWorkspaceInvites(workspace.id)
        if (cancelled) return
        const existing = result.items.find(
          (invite) => invite.method === "link" && invite.status === "pending"
        )
        if (existing) {
          setLinkInvite(existing)
        } else {
          const created = await createWorkspaceInvite(workspace.id, {
            method: "link",
          })
          if (cancelled) return
          setLinkInvite(created)
          setInvites((prev) => [created, ...prev])
        }
      } catch (err) {
        if (cancelled) return
        setSendError(
          err instanceof ApiError
            ? err.message
            : "Could not generate an invite link."
        )
      } finally {
        if (!cancelled) setLinkLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [open, workspace, tab, linkInvite])

  async function handleEmailInvite(e: React.FormEvent) {
    e.preventDefault()
    if (!workspace) return
    const target = email.trim()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) {
      setSendError("Enter a valid email address.")
      return
    }
    setSending(true)
    setSendError(null)
    setSentNotice(null)
    setManualShareInvite(null)
    try {
      const created = await createWorkspaceInvite(workspace.id, {
        method: "email",
        email: target,
      })
      setEmail("")
      if (created.email_delivered) {
        setSentNotice(`Invite emailed to ${target}.`)
      } else {
        // The invite row exists either way — SES just didn't (or couldn't)
        // deliver it. Never claim "sent" when nothing went out.
        setManualShareInvite(created)
      }
      await refreshInvites()
    } catch (err) {
      setSendError(
        err instanceof ApiError ? err.message : "Could not send the invite."
      )
    } finally {
      setSending(false)
    }
  }

  async function handleGithubInvite(e: React.FormEvent) {
    e.preventDefault()
    if (!workspace) return
    const username = githubUsername.trim()
    if (!username) {
      setSendError("Enter a GitHub username.")
      return
    }
    if (!githubUser) {
      setSendError(
        "No GitHub account confirmed for that handle — check it and try again."
      )
      return
    }
    setSending(true)
    setSendError(null)
    setSentNotice(null)
    setManualShareInvite(null)
    try {
      // GitHub has no API to message an arbitrary user, so this only ever
      // records the invite — it never delivers anything by itself. Show the
      // link to share instead of claiming it was "sent".
      const created = await createWorkspaceInvite(workspace.id, {
        method: "github",
        github_username: username,
      })
      setGithubUsername("")
      setGithubUser(null)
      setGithubStatus("idle")
      setManualShareInvite(created)
      await refreshInvites()
    } catch (err) {
      setSendError(
        err instanceof ApiError ? err.message : "Could not send the invite."
      )
    } finally {
      setSending(false)
    }
  }

  async function handleCopyManual() {
    if (!manualShareUrl) return
    try {
      await navigator.clipboard.writeText(manualShareUrl)
      setManualCopied(true)
      window.setTimeout(() => setManualCopied(false), 2000)
    } catch {
      setSendError("Could not copy — select the link and copy it manually.")
    }
  }

  async function handleCopy() {
    if (!inviteUrl) return
    try {
      await navigator.clipboard.writeText(inviteUrl)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setSendError("Could not copy — select the link and copy it manually.")
    }
  }

  async function handleRevokeAndRegenerate() {
    if (!workspace || !linkInvite) return
    setLinkLoading(true)
    setSendError(null)
    try {
      await revokeWorkspaceInvite(workspace.id, linkInvite.id)
      // Clearing the invite makes the link-tab effect regenerate a fresh
      // one automatically. If the regeneration then fails, the effect
      // surfaces the error and no revoked link is left on screen.
      setLinkInvite(null)
      setCopied(false)
      await refreshInvites()
    } catch (err) {
      setSendError(
        err instanceof ApiError
          ? err.message
          : "Could not regenerate the invite link."
      )
      // linkInvite is untouched on failure, so the effect won't rerun —
      // release the spinner here instead.
      setLinkLoading(false)
    }
  }

  async function handleRevoke(invite: WorkspaceInvite) {
    if (!workspace) return
    setRevokingId(invite.id)
    setSendError(null)
    try {
      await revokeWorkspaceInvite(workspace.id, invite.id)
      setInvites((prev) => prev.filter((item) => item.id !== invite.id))
    } catch (err) {
      setSendError(
        err instanceof ApiError ? err.message : "Could not revoke that invite."
      )
    } finally {
      setRevokingId(null)
    }
  }

  if (!workspace) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton>
        <DialogHeader>
          <DialogTitle>Invite people to {workspace.name}</DialogTitle>
          <DialogDescription>
            Invite teammates to collaborate on this workspace.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-1">
          {/* Segmented mode switch — same control as the settings theme picker. */}
          <div
            aria-label="Invite method"
            className="border-border bg-muted/30 inline-flex w-full gap-0.5 rounded-lg border p-0.5"
          >
            {(
              [
                { value: "email", label: "Email", icon: Mail },
                { value: "github", label: "GitHub", icon: AtSign },
                { value: "link", label: "Link", icon: Link2 },
              ] as const
            ).map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                type="button"
                onClick={() => {
                  setSendError(null)
                  setSentNotice(null)
                  setManualShareInvite(null)
                  setManualCopied(false)
                  setTab(value)
                }}
                aria-pressed={tab === value}
                className={cn(
                  "flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                  tab === value
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Icon className="size-3.5" />
                {label}
              </button>
            ))}
          </div>

          {tab === "email" ? (
            <form
              onSubmit={(e) => void handleEmailInvite(e)}
              className="space-y-2.5"
            >
              <Input
                type="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="teammate@company.com"
                className="h-10"
                autoComplete="off"
              />
              <Button
                type="submit"
                size="sm"
                disabled={sending || !email.trim()}
              >
                {sending ? "Sending…" : "Send invite"}
              </Button>
            </form>
          ) : null}

          {tab === "github" ? (
            <form
              onSubmit={(e) => void handleGithubInvite(e)}
              className="space-y-2.5"
            >
              <Input
                autoFocus
                value={githubUsername}
                onChange={(e) => setGithubUsername(e.target.value)}
                placeholder="GitHub username"
                className="h-10"
                autoComplete="off"
              />
              <div className="min-h-[2.5rem]">
                {githubStatus === "checking" ? (
                  <p className="text-muted-foreground text-[12px]">
                    Looking up @{githubUsername.trim()}…
                  </p>
                ) : githubStatus === "missing" ? (
                  <p className="text-[12px] leading-snug text-destructive">
                    No GitHub user named “{githubUsername.trim()}”. Check the
                    handle and try again.
                  </p>
                ) : githubStatus === "error" ? (
                  <p className="text-[12px] leading-snug text-destructive">
                    Could not reach GitHub — check the handle manually or try
                    again.
                  </p>
                ) : githubUser ? (
                  <div className="border-border bg-muted/30 flex items-center gap-2.5 rounded-lg border px-3 py-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={githubUser.avatar_url}
                      alt=""
                      className="size-7 shrink-0 rounded-full"
                    />
                    <div className="min-w-0">
                      <div className="text-foreground truncate text-[13px] font-semibold">
                        {githubUser.name ?? githubUser.login}
                      </div>
                      <div className="text-muted-foreground truncate text-[11.5px]">
                        @{githubUser.login}
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
              <Button
                type="submit"
                size="sm"
                disabled={
                  sending ||
                  !githubUsername.trim() ||
                  githubStatus === "checking"
                }
              >
                {sending ? "Sending…" : "Send invite"}
              </Button>
            </form>
          ) : null}

          {manualShareInvite && (tab === "email" || tab === "github") ? (
            <div className="border-border bg-muted/30 space-y-2 rounded-lg border px-3 py-2.5">
              <p className="text-muted-foreground text-[12px] leading-snug">
                {manualShareInvite.method === "github"
                  ? `Invite created for @${manualShareInvite.github_username}. GitHub has no way for us to message someone automatically — copy this link and send it to them yourself.`
                  : `Could not email this invite automatically. Copy this link and send it to ${manualShareInvite.email} yourself.`}
              </p>
              <div className="flex items-center gap-2">
                <Input
                  readOnly
                  value={manualShareUrl}
                  className="h-9 flex-1 font-mono text-xs"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void handleCopyManual()}
                >
                  {manualCopied ? (
                    <Check className="size-3.5" />
                  ) : (
                    <Copy className="size-3.5" />
                  )}
                  {manualCopied ? "Copied" : "Copy"}
                </Button>
              </div>
            </div>
          ) : null}

          {tab === "link" ? (
            <div className="space-y-2.5">
              <div className="flex items-center gap-2">
                <Input
                  readOnly
                  value={inviteUrl}
                  placeholder={linkLoading ? "Generating invite link…" : ""}
                  className="h-10 flex-1 font-mono text-xs"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void handleCopy()}
                  disabled={!inviteUrl || linkLoading}
                >
                  {copied ? (
                    <Check className="size-3.5" />
                  ) : (
                    <Copy className="size-3.5" />
                  )}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
              <div className="flex items-start justify-between gap-3">
                <p className="text-muted-foreground text-[11.5px] leading-snug">
                  Anyone with this link can join. It expires{" "}
                  {linkInvite?.expires_at
                    ? `on ${new Date(linkInvite.expires_at).toLocaleDateString()}`
                    : "after a short time"}
                  .
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground shrink-0"
                  disabled={linkLoading || !linkInvite}
                  onClick={() => void handleRevokeAndRegenerate()}
                >
                  <RefreshCw className="size-3.5" />
                  Revoke &amp; regenerate
                </Button>
              </div>
            </div>
          ) : null}

          {sentNotice ? (
            <p className="rounded-lg border border-[var(--tone-pass-border)] bg-[var(--tone-pass-bg)] px-3 py-2 text-[12.5px] text-[var(--tone-pass-fg)]">
              {sentNotice}
            </p>
          ) : null}
          {sendError ? (
            <p className="text-[12px] leading-snug text-destructive">
              {sendError}
            </p>
          ) : null}

          <div className="border-border border-t pt-3">
            <Label className="mb-2">Pending invites</Label>
            {!invitesLoaded ? (
              <p className="text-muted-foreground text-[12px]">Loading…</p>
            ) : pendingInvites.length === 0 ? (
              <EmptyNote>No pending invites.</EmptyNote>
            ) : (
              <div className="space-y-2">
                {pendingInvites.map((invite) => (
                  <div
                    key={invite.id}
                    className="border-border flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5"
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <InviteMethodIcon method={invite.method} />
                      <div className="min-w-0">
                        <div className="text-foreground truncate text-[13px] font-medium">
                          {invite.email ??
                            (invite.github_username
                              ? `@${invite.github_username}`
                              : "Invite link")}
                        </div>
                        <p className="text-muted-foreground truncate text-[11.5px]">
                          {invite.created_at
                            ? `Sent ${new Date(invite.created_at).toLocaleDateString()}`
                            : "Pending"}
                        </p>
                      </div>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={revokingId === invite.id}
                      onClick={() => void handleRevoke(invite)}
                      aria-label={`Revoke invite to ${
                        invite.email ??
                        (invite.github_username
                          ? `@${invite.github_username}`
                          : "the link")
                      }`}
                    >
                      <X className="size-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function InviteMethodIcon({ method }: { method: WorkspaceInviteMethod }) {
  const Icon =
    method === "email" ? Mail : method === "github" ? AtSign : Link2
  return (
    <div className="flex size-6 shrink-0 items-center justify-center rounded-md border">
      <Icon className="size-3.5" />
    </div>
  )
}
