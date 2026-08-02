/** Clerk session token bridge for the typed API client (non-React). */

import { getAccessToken } from "./auth-token"

type TokenGetter = () => Promise<string | null>

let clerkTokenGetter: TokenGetter | null = null

/**
 * Resolves once the auth state is known — either a Clerk token getter has been
 * registered, or we've been told nobody is signed in.
 *
 * Without this, any request issued between first paint and Clerk finishing its
 * client-side load goes out with no Authorization header. That was harmless
 * while the backend ignored auth; with auth enforced it turns the first fetch
 * of every page into a 401 that never retries.
 */
let resolveReady: (() => void) | null = null
let readyPromise: Promise<void> = new Promise((resolve) => {
  resolveReady = resolve
})
let isReady = false

function markReady(): void {
  if (isReady) return
  isReady = true
  resolveReady?.()
}

export function setClerkTokenGetter(getter: TokenGetter | null): void {
  clerkTokenGetter = getter
  if (getter) markReady()
}

/** Clerk has loaded and reports nobody is signed in — stop waiting. */
export function markUnauthenticated(): void {
  markReady()
}

/** Bearer token: Clerk session JWT when signed in, else legacy localStorage token. */
export async function resolveAuthToken(): Promise<string | null> {
  if (!isReady && typeof window !== "undefined") {
    // Bounded: never let a stuck auth provider hang every request forever.
    // Falling through unauthenticated after the timeout produces an honest
    // 401 rather than a request that never settles.
    await Promise.race([
      readyPromise,
      new Promise<void>((resolve) => setTimeout(resolve, 5000)),
    ])
  }

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
