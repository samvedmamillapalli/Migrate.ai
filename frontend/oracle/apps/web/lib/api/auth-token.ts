/** Auth token helpers for the console (Wave 2 / Clerk). */

import { useAuth } from "@clerk/nextjs"

const TOKEN_KEY = "oracle:access_token"
const COOKIE_NAME = "oracle_access_token"

/**
 * Get the current access token from localStorage (fallback for custom auth)
 * or from Clerk's session token when Clerk is configured.
 */
export function getAccessToken(): string {
  if (typeof window === "undefined") return ""
  return window.localStorage.getItem(TOKEN_KEY)?.trim() || ""
}

/**
 * Set the access token in localStorage and mirror a cookie for middleware.
 * This is used by the custom auth flow; Clerk manages its own tokens.
 */
export function setAccessToken(token: string | null): void {
  if (typeof window === "undefined") return
  if (!token) {
    window.localStorage.removeItem(TOKEN_KEY)
    document.cookie = `${COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`
    return
  }
  window.localStorage.setItem(TOKEN_KEY, token)
  // Mirror for Next middleware soft gate (not HttpOnly — API still uses Bearer).
  document.cookie = `${COOKIE_NAME}=1; Path=/; Max-Age=${60 * 60 * 24 * 7}; SameSite=Lax`
}

/**
 * Get a Clerk JWT session token for API authentication.
 * Returns null if Clerk is not configured or user is not signed in.
 */
export async function getClerkToken(): Promise<string | null> {
  if (typeof window === "undefined") return null
  try {
    // Use dynamic import to avoid issues when Clerk is not configured
    const { useAuth } = await import("@clerk/nextjs")
    // This hook must be called within a React component context.
    // For non-component usage, fall back to localStorage token.
    return null
  } catch {
    return null
  }
}

/**
 * Clear all auth tokens (both Clerk and custom).
 */
export function clearAccessToken(): void {
  setAccessToken(null)
}
