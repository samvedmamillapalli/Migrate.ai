"use client"

import { useEffect, useRef } from "react"

/** Terminal migration_run statuses — stop polling hard. */
export const TERMINAL_RUN_STATUSES = new Set(["completed", "failed"])

/** Workflow statuses that mean the durable execution is done. */
export const TERMINAL_WORKFLOW_STATUSES = new Set([
  "succeeded",
  "failed",
  "timed_out",
  "aborted",
])

export type PollOptions = {
  /** Initial interval ms. Default 2500. */
  intervalMs?: number
  /** After this many ms, slow the interval. Default 60_000. */
  backoffAfterMs?: number
  /** Interval after backoff. Default 8000. */
  backoffIntervalMs?: number
  /**
   * Absolute ceiling past the longest shadow timeouts (~30 min).
   * Default 1_800_000 (30 minutes).
   */
  ceilingMs?: number
  /** When false, the loop is paused (e.g. no run id yet). Default true. */
  enabled?: boolean
  /**
   * Return true to stop polling (terminal status reached).
   * Called after each successful tick.
   */
  shouldStop?: () => boolean
}

/**
 * Poll every 2–3s, back off after one minute, stop on terminal / ceiling,
 * cancel on unmount, and pause while the tab is hidden.
 */
export function usePolling(
  tick: () => void | Promise<void>,
  options: PollOptions = {}
): void {
  const {
    intervalMs = 2500,
    backoffAfterMs = 60_000,
    backoffIntervalMs = 8000,
    ceilingMs = 1_800_000,
    enabled = true,
    shouldStop,
  } = options

  const tickRef = useRef(tick)
  const stopRef = useRef(shouldStop)
  tickRef.current = tick
  stopRef.current = shouldStop

  useEffect(() => {
    if (!enabled) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const startedAt = Date.now()

    const clear = () => {
      if (timer != null) {
        clearTimeout(timer)
        timer = null
      }
    }

    const schedule = (delay: number) => {
      clear()
      timer = setTimeout(run, delay)
    }

    const run = async () => {
      if (cancelled) return
      if (typeof document !== "undefined" && document.hidden) {
        schedule(intervalMs)
        return
      }
      const elapsed = Date.now() - startedAt
      if (elapsed >= ceilingMs) return

      try {
        await tickRef.current()
      } catch {
        /* keep polling; callers surface errors themselves */
      }

      if (cancelled) return
      if (stopRef.current?.()) return

      const nextElapsed = Date.now() - startedAt
      if (nextElapsed >= ceilingMs) return

      const delay =
        nextElapsed >= backoffAfterMs ? backoffIntervalMs : intervalMs
      schedule(delay)
    }

    const onVisibility = () => {
      if (cancelled) return
      if (!document.hidden) {
        void run()
      }
    }

    document.addEventListener("visibilitychange", onVisibility)
    void run()

    return () => {
      cancelled = true
      clear()
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, [
    enabled,
    intervalMs,
    backoffAfterMs,
    backoffIntervalMs,
    ceilingMs,
  ])
}
