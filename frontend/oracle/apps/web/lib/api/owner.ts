/** Owner identity for API scoping — synced from Clerk user id when signed in. */

const OWNER_KEY = "oracle:owner_identity"
const CURRENT_RUN_KEY = "oracle:current_run_id"
const SECRET_ARN_KEY = "oracle:connection_secret_arn"

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
