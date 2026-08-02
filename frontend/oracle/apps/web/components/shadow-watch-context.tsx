"use client"

import * as React from "react"

import { ApiError, getCurrentRunId, getRun, hasRealSfnArn, setCurrentRunId } from "@/lib/api"

/** True when the pinned run can never load in this session again. */
function isGoneOrForbidden(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.status === 404 || err.status === 401 || err.status === 403)
  )
}

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
    let cancelled = false
    async function rehydrate() {
      let parsed: { runId?: string; open?: boolean; minimized?: boolean }
      try {
        const raw = window.localStorage.getItem(STORAGE_KEY)
        if (!raw) return
        parsed = JSON.parse(raw)
      } catch {
        return
      }
      if (!parsed.runId) return

      // A persisted runId can outlive its usefulness: deleted, or (as
      // happened during development switching Clerk test accounts) belonging
      // to a different owner than whoever is signed in now. Confirm it still
      // resolves before restoring the watcher open on top of a run that will
      // just 401 forever — otherwise the floating widget reappears every load
      // trying and failing to fetch something it can never show.
      try {
        await getRun(parsed.runId)
        if (cancelled) return
        setRunId(parsed.runId)
        setOpen(Boolean(parsed.open))
        setMinimized(Boolean(parsed.minimized))
      } catch (err) {
        if (isGoneOrForbidden(err)) {
          try {
            window.localStorage.removeItem(STORAGE_KEY)
          } catch {
            /* ignore */
          }
        }
      }
    }
    void rehydrate()
    return () => {
      cancelled = true
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

  /**
   * Surface a shadow that is already running.
   *
   * Without this, arriving on the dashboard while a workflow is mid-flight
   * showed nothing at all unless you happened to have opened the watcher
   * before. Opens minimized so it announces itself without covering the page,
   * and only for a real Step Functions execution — never for a run that is
   * merely approved and waiting to be started by hand.
   */
  React.useEffect(() => {
    if (open) return
    let cancelled = false
    async function detectLiveShadow() {
      const pinned = getCurrentRunId()
      if (!pinned) return
      try {
        const run = await getRun(pinned)
        if (cancelled || !run) return
        const live =
          hasRealSfnArn(run) &&
          (run.workflow_status === "running" || run.status === "running")
        if (live) {
          setRunId(run.id)
          setOpen(true)
          setMinimized(true)
        }
      } catch (err) {
        if (isGoneOrForbidden(err)) setCurrentRunId(null)
      }
    }
    void detectLiveShadow()
    return () => {
      cancelled = true
    }
    // Mount-only: a live shadow should announce itself once, not re-open
    // every time the user deliberately closes it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
