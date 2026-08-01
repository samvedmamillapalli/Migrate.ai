"use client"

import * as React from "react"

type ShadowWatchContextValue = {
  runId: string | null
  open: boolean
  minimized: boolean
  openWatch: (runId: string) => void
  closeWatch: () => void
  toggleMinimized: () => void
  setMinimized: (value: boolean) => void
}

const ShadowWatchContext = React.createContext<ShadowWatchContextValue | null>(
  null
)

const STORAGE_KEY = "oracle:shadow_watch"

export function ShadowWatchProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const [runId, setRunId] = React.useState<string | null>(null)
  const [open, setOpen] = React.useState(false)
  const [minimized, setMinimized] = React.useState(false)

  React.useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const parsed = JSON.parse(raw) as {
        runId?: string
        open?: boolean
        minimized?: boolean
      }
      if (parsed.runId) {
        setRunId(parsed.runId)
        setOpen(Boolean(parsed.open))
        setMinimized(Boolean(parsed.minimized))
      }
    } catch {
      /* ignore */
    }
  }, [])

  React.useEffect(() => {
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ runId, open, minimized })
      )
    } catch {
      /* ignore */
    }
  }, [runId, open, minimized])

  const value = React.useMemo<ShadowWatchContextValue>(
    () => ({
      runId,
      open,
      minimized,
      openWatch: (id: string) => {
        setRunId(id)
        setOpen(true)
        setMinimized(false)
      },
      closeWatch: () => {
        setOpen(false)
        setMinimized(false)
      },
      toggleMinimized: () => setMinimized((m) => !m),
      setMinimized,
    }),
    [runId, open, minimized]
  )

  return (
    <ShadowWatchContext.Provider value={value}>
      {children}
    </ShadowWatchContext.Provider>
  )
}

export function useShadowWatch(): ShadowWatchContextValue {
  const ctx = React.useContext(ShadowWatchContext)
  if (!ctx) {
    throw new Error("useShadowWatch must be used within ShadowWatchProvider")
  }
  return ctx
}
