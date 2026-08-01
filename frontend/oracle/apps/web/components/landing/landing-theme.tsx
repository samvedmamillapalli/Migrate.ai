"use client"

import * as React from "react"

/**
 * Visually force the marketing page into light/cream mode without
 * persisting a theme preference that would affect the dashboard.
 */
export function LandingTheme({ children }: { children: React.ReactNode }) {
  React.useEffect(() => {
    const root = document.documentElement
    const hadDark = root.classList.contains("dark")
    root.classList.remove("dark")
    root.classList.add("light")
    return () => {
      root.classList.remove("light")
      if (hadDark) root.classList.add("dark")
    }
  }, [])

  return <>{children}</>
}
