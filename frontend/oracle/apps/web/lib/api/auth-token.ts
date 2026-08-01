/** Auth token helpers — legacy custom auth + Clerk (see clerk-token.ts). */

const TOKEN_KEY = "oracle:access_token"
const COOKIE_NAME = "oracle_access_token"

export function getAccessToken(): string {
  if (typeof window === "undefined") return ""
  return window.localStorage.getItem(TOKEN_KEY)?.trim() || ""
}

export function setAccessToken(token: string | null): void {
  if (typeof window === "undefined") return
  if (!token) {
    window.localStorage.removeItem(TOKEN_KEY)
    document.cookie = `${COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`
    return
  }
  window.localStorage.setItem(TOKEN_KEY, token)
  document.cookie = `${COOKIE_NAME}=1; Path=/; Max-Age=${60 * 60 * 24 * 7}; SameSite=Lax`
}

export function clearAccessToken(): void {
  setAccessToken(null)
}
