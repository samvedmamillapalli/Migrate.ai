"use client"

import { ApiAuthBootstrap } from "@/components/api-auth-bootstrap"
import { ClerkOwnerSync } from "@/components/clerk-owner-sync"

/**
 * Registers the Clerk token bridge and owner-identity sync above the
 * dashboard content.
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
      <ApiAuthBootstrap />
      <ClerkOwnerSync />
      {children}
    </>
  )
}
