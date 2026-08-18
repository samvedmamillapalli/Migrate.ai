"use client"

import { ClerkOwnerSync } from "@/components/clerk-owner-sync"

/**
 * Registers owner-identity sync above the dashboard content. The Clerk
 * token bridge (`ApiAuthBootstrap`) now lives in the root layout — every
 * route needs it, not just the dashboard (the invite-acceptance page at
 * `/invite/[token]` is the reason: it makes authenticated API calls while
 * living outside `/dashboard`, and silently shipped every request with no
 * Authorization header until this moved up).
 *
 * This must never branch the rendered tree on Clerk's `isLoaded`/`isSignedIn`
 * state: those are `false` during SSR (Clerk only resolves client-side) but
 * can already be `true` on the client's very first paint when a session
 * cookie exists, so the server and client trees would genuinely differ and
 * React discards the whole tree and re-renders from scratch — the entire
 * subtree remounts, refiring every request. `children` is always rendered
 * identically on server and client; the request-timing problem (a page's
 * mount-effect fetch firing before Clerk has produced a token) is instead
 * solved asynchronously, in `resolveAuthToken()` (lib/api/clerk-token.ts),
 * which delays the outgoing request rather than delaying what's on screen.
 */
export function DashboardProviders({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <>
      <ClerkOwnerSync />
      {children}
    </>
  )
}
