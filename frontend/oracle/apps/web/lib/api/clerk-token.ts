/** Clerk session token bridge for the typed API client (non-React). */

import { getAccessToken } from "./auth-token"

type TokenGetter = () => Promise<string | null>

let clerkTokenGetter: TokenGetter | null = null
let unauthenticated = false

/**
 * Resolves whenever a token getter is currently registered, or we've been
 * told nobody is signed in — reopened (a fresh pending promise) any time the
 * getter is unregistered while still signed in, not just once at startup.
 *
 * Without this, any request issued before Clerk's first registration goes
 * out with no Authorization header — harmless while the backend ignored
 * auth, a guaranteed 401 with auth enforced. A single one-time latch isn't
 * enough: `ApiAuthBootstrap`'s effect cleanup unregisters the getter (sets it
 * null) on every re-run, not just on sign-out — e.g. Clerk handing back a new
 * `getToken` reference between renders — and immediately re-registers a
 * fresh one. A request landing in that gap with a latch that only ever
 * flips once skips the wait entirely and silently ships with no token,
 * indistinguishable from a real "failed to fetch" to the caller. Reopening
 * the gate on every unregister (except as part of an actual sign-out, where
 * we want requests through immediately rather than waiting out the full
 * timeout) makes that gap wait, bounded, instead of failing.
 */
let resolveReady: (() => void) | null = null
let readyPromise: Promise<void> = new Promise((resolve) => {
  resolveReady = resolve
})

function markReady(): void {
  resolveReady?.()
}

function reopenGate(): void {
  readyPromise = new Promise((resolve) => {
    resolveReady = resolve
  })
}

export function setClerkTokenGetter(getter: TokenGetter | null): void {
  clerkTokenGetter = getter
  if (getter) {
    unauthenticated = false
    markReady()
  } else if (!unauthenticated) {
    reopenGate()
  }
}

/** Clerk has loaded and reports nobody is signed in — stop waiting. */
export function markUnauthenticated(): void {
  unauthenticated = true
  markReady()
}

/** Bearer token: Clerk session JWT when signed in, else legacy localStorage token. */
export async function resolveAuthToken(): Promise<string | null> {
  if (!clerkTokenGetter && !unauthenticated && typeof window !== "undefined") {
    // Bounded: never let a stuck/slow-to-reregister auth provider hang every
    // request forever. Falling through unauthenticated after the timeout
    // produces an honest 401 rather than a request that never settles.
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
