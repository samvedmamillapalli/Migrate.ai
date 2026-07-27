import { clearAccessToken } from "@/lib/api/auth-token"
import { setCurrentRunId, setOwnerIdentity } from "@/lib/api/owner"

type ClerkSignOut = (options?: { redirectUrl?: string }) => void | Promise<void>

export function clearLocalSession(): void {
  clearAccessToken()
  setOwnerIdentity("")
  setCurrentRunId(null)
}

/** Clear local state and end the Clerk session (redirects to landing). */
export async function performSignOut(signOut: ClerkSignOut): Promise<void> {
  clearLocalSession()
  await signOut({ redirectUrl: "/" })
}
