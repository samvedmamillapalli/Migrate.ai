/** Owner identity for API scoping — synced from Clerk user id when signed in. */

const OWNER_KEY = "oracle:owner_identity"
const CURRENT_RUN_KEY = "oracle:current_run_id"
const SECRET_ARN_KEY = "oracle:connection_secret_arn"
const ACTIVE_WORKSPACE_KEY = "oracle:active_workspace_id"

export function getOwnerIdentity(): string {
  if (typeof window === "undefined") return ""
  return (window.localStorage.getItem(OWNER_KEY) || "").trim()
}

export function setOwnerIdentity(value: string): void {
  if (typeof window === "undefined") return
  const normalized = value.trim()
  if (!normalized) {
    window.localStorage.removeItem(OWNER_KEY)
    return
  }
  window.localStorage.setItem(OWNER_KEY, normalized)
}

export function requireOwnerIdentity(): string {
  const owner = getOwnerIdentity()
  if (!owner) {
    throw new Error(
      "Set an owner identity in the sidebar (or Settings) before creating a run."
    )
  }
  return owner
}

export function getCurrentRunId(): string | null {
  if (typeof window === "undefined") return null
  return window.localStorage.getItem(CURRENT_RUN_KEY)
}

export function setCurrentRunId(id: string | null): void {
  if (typeof window === "undefined") return
  if (!id) {
    window.localStorage.removeItem(CURRENT_RUN_KEY)
    return
  }
  window.localStorage.setItem(CURRENT_RUN_KEY, id)
}

export function getConnectionSecretArn(): string {
  if (typeof window === "undefined") return ""
  return (window.localStorage.getItem(SECRET_ARN_KEY) || "").trim()
}

export function setConnectionSecretArn(value: string): void {
  if (typeof window === "undefined") return
  const normalized = value.trim()
  if (!normalized) {
    window.localStorage.removeItem(SECRET_ARN_KEY)
    return
  }
  window.localStorage.setItem(SECRET_ARN_KEY, normalized)
}

/** Active workspace — docs/FUTURE_WORKSPACES_PLAN.md. Empty string/null
 * means "no workspace selected", same convention as owner identity. */
export function getActiveWorkspaceId(): string {
  if (typeof window === "undefined") return ""
  return (window.localStorage.getItem(ACTIVE_WORKSPACE_KEY) || "").trim()
}

export function setActiveWorkspaceId(id: string | null): void {
  if (typeof window === "undefined") return
  if (!id) {
    window.localStorage.removeItem(ACTIVE_WORKSPACE_KEY)
    return
  }
  window.localStorage.setItem(ACTIVE_WORKSPACE_KEY, id)
}

/** Same "does the stored id still exist? else is_default, else first" fallback
 * as WorkspaceSwitcher's own load() — extracted so every call site that
 * needs a workspace id to CREATE something (a run, in particular) resolves
 * and persists the same validated value instead of trusting a bare
 * getActiveWorkspaceId() read. A stale/missing localStorage value (first
 * visit on a device, or the switcher's own fetch not resolved yet on a deep
 * link straight to /dashboard/migrations/new) previously fell through to
 * `|| null`, silently creating a run with no workspace at all — invisible
 * in that workspace's history and disconnected from any linked GitHub repo,
 * even though the migration itself ran fine. Returns null only when the
 * owner truly has zero workspaces.
 */
export async function resolveActiveWorkspaceId(): Promise<string | null> {
  const { listWorkspaces } = await import("./endpoints")
  const owner = getOwnerIdentity()
  let items: { id: string; is_default?: boolean }[]
  try {
    items = (await listWorkspaces(owner || undefined)).items
  } catch {
    // Can't validate right now — fall back to whatever's stored rather than
    // wiping a perfectly good selection over a transient network blip.
    return getActiveWorkspaceId() || null
  }
  const stored = getActiveWorkspaceId()
  if (stored && items.some((w) => w.id === stored)) {
    return stored
  }
  const fallback = items.find((w) => w.is_default) ?? items[0]
  setActiveWorkspaceId(fallback?.id ?? null)
  return fallback?.id ?? null
}

/** Fired whenever a workspace's persisted state (e.g. its stored connection)
 * changes somewhere other than the sidebar switcher itself — the switcher
 * listens and re-fetches, so it reflects the change without a full page
 * reload (unlike selectWorkspace, which does reload). */
export const WORKSPACES_CHANGED_EVENT = "oracle:workspaces-changed"

export function notifyWorkspacesChanged(): void {
  if (typeof window === "undefined") return
  window.dispatchEvent(new Event(WORKSPACES_CHANGED_EVENT))
}
