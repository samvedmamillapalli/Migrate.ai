"use client"

import * as React from "react"
import { usePathname } from "next/navigation"
import { useUser } from "@clerk/nextjs"
import { ThemeProvider as NextThemesProvider } from "next-themes"

import { getStoredTheme, setStoredTheme, type ThemePreference } from "@/lib/theme-preference"

/**
 * The workspace design is light-first (see packages/ui globals.css — the
 * light tokens are the design source of truth, the dark block is authored
 * on top of them). So every route defaults to light and dark becomes an
 * explicit opt-in via Settings → Appearance, per signed-in user.
 */
function routeDefault(_pathname: string): ThemePreference {
  return "light"
}

type ThemePreferenceContextValue = {
  theme: ThemePreference
  setTheme: (theme: ThemePreference) => void
}

const ThemePreferenceContext = React.createContext<ThemePreferenceContextValue | null>(null)

/** Current light/dark preference and setter, scoped to the signed-in user.
 * Use this instead of next-themes' own `useTheme` — the class on <html> is
 * fully controlled by this context via `forcedTheme`, so next-themes'
 * internal state/storage is unused. */
export function useThemePreference(): ThemePreferenceContextValue {
  const ctx = React.useContext(ThemePreferenceContext)
  if (!ctx) {
    throw new Error("useThemePreference must be used within ThemeProvider")
  }
  return ctx
}

function ThemeProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { user, isLoaded } = useUser()
  const [theme, setThemeState] = React.useState<ThemePreference>(() => routeDefault(pathname))

  // Once we know who's signed in (or that nobody is), resolve their explicit
  // preference — falling back to the route's usual look if they've never
  // set one. Runs client-only, after first paint, matching the
  // suppressHydrationWarning already set on <html>.
  React.useEffect(() => {
    if (!isLoaded) return
    setThemeState(
      user ? (getStoredTheme(user.id) ?? routeDefault(pathname)) : routeDefault(pathname)
    )
  }, [isLoaded, user, pathname])

  const setTheme = React.useCallback(
    (next: ThemePreference) => {
      setThemeState(next)
      if (user) setStoredTheme(user.id, next)
    },
    [user]
  )

  const value = React.useMemo(() => ({ theme, setTheme }), [theme, setTheme])

  return (
    <ThemePreferenceContext.Provider value={value}>
      <NextThemesProvider attribute="class" forcedTheme={theme} enableSystem={false}>
        {children}
      </NextThemesProvider>
    </ThemePreferenceContext.Provider>
  )
}

export { ThemeProvider }
