"use client"

import * as React from "react"

/** Prevents document scroll while the landing is mounted (h-dvh shell alone isn't enough if body grows). */
export function LockLandingViewport({
  children,
}: {
  children: React.ReactNode
}) {
  React.useEffect(() => {
    const html = document.documentElement
    const body = document.body
    const prevHtml = html.style.overflow
    const prevBody = body.style.overflow
    html.style.overflow = "hidden"
    body.style.overflow = "hidden"
    return () => {
      html.style.overflow = prevHtml
      body.style.overflow = prevBody
    }
  }, [])

  return <>{children}</>
}
