import * as React from "react"

/**
 * Marker wrapper for marketing/auth routes. Theme resolution actually
 * happens in ThemeProvider — these routes just default to light for
 * signed-out visitors and users with no explicit preference yet. A
 * signed-in user's chosen theme (Settings → Appearance) still applies here
 * too. This component exists so call sites stay self-documenting about
 * which pages are light-by-default.
 */
export function LandingTheme({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
