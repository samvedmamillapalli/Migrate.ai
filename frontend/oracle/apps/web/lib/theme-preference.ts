export type ThemePreference = "light" | "dark"

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "light" || value === "dark"
}

function storageKey(userId: string): string {
  return `oracle:theme:${userId}`
}

/** Explicit preference for this Clerk user, if they've ever set one — keyed
 * per user id so different accounts on the same browser don't clobber each
 * other's choice. */
export function getStoredTheme(userId: string): ThemePreference | null {
  if (typeof window === "undefined") return null
  const value = window.localStorage.getItem(storageKey(userId))
  return isThemePreference(value) ? value : null
}

export function setStoredTheme(userId: string, theme: ThemePreference): void {
  if (typeof window === "undefined") return
  window.localStorage.setItem(storageKey(userId), theme)
}
