/** Clerk session token bridge for the typed API client (non-React). */

import { getAccessToken } from "./auth-token"

type TokenGetter = () => Promise<string | null>

let clerkTokenGetter: TokenGetter | null = null

export function setClerkTokenGetter(getter: TokenGetter | null): void {
  clerkTokenGetter = getter
}

/** Bearer token: Clerk session JWT when signed in, else legacy localStorage token. */
export async function resolveAuthToken(): Promise<string | null> {
  if (clerkTokenGetter) {
    try {
      const clerkToken = await clerkTokenGetter()
      if (clerkToken) return clerkToken
    } catch {
      /* fall through */
    }
  }
  const legacy = getAccessToken()
  return legacy || null
}
