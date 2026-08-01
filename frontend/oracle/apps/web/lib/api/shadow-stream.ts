"use client"

import * as React from "react"

import { apiBaseUrl } from "./client"
import { resolveAuthToken } from "./clerk-token"
import type { ShadowCluster } from "./endpoints"

export type ShadowStreamState = {
  shadow: ShadowCluster | null
  /** True once at least one SSE frame has been received on this connection. */
  connected: boolean
  /** Shadow cluster row doesn't exist yet (run created, workflow not started). */
  waiting: boolean
}

/**
 * Live shadow-cluster updates over Server-Sent Events — replaces polling
 * `GET /shadow-cluster` for the live view. The browser's EventSource retries
 * automatically on a dropped connection; this hook just reflects state, it
 * doesn't need its own retry loop. Silently produces "not connected" (never
 * throws) if EventSource isn't available in this environment — callers that
 * need a guaranteed fallback should keep a slow poll alongside `connected`.
 */
export function useShadowStream(
  runId: string | null,
  opts?: { enabled?: boolean }
): ShadowStreamState {
  const enabled = opts?.enabled ?? true
  const [shadow, setShadow] = React.useState<ShadowCluster | null>(null)
  const [connected, setConnected] = React.useState(false)
  const [waiting, setWaiting] = React.useState(true)

  React.useEffect(() => {
    if (
      !runId ||
      !enabled ||
      typeof window === "undefined" ||
      typeof EventSource === "undefined"
    ) {
      setConnected(false)
      return
    }
    let cancelled = false
    let source: EventSource | null = null

    async function connect() {
      const token = await resolveAuthToken().catch(() => null)
      if (cancelled) return
      const url = new URL(`${apiBaseUrl()}/runs/${runId}/shadow-cluster/stream`)
      // EventSource can't set an Authorization header — the backend accepts
      // the same bearer token via this query param for this route only.
      if (token) url.searchParams.set("token", token)

      const es = new EventSource(url.toString())
      source = es
      es.addEventListener("shadow", (event) => {
        if (cancelled) return
        try {
          const data = JSON.parse((event as MessageEvent).data) as
            | (Record<string, unknown> & { waiting?: boolean })
            | ShadowCluster
          setConnected(true)
          if ("waiting" in data && data.waiting) {
            setWaiting(true)
          } else {
            setWaiting(false)
            setShadow(data as ShadowCluster)
          }
        } catch {
          /* malformed frame — ignore, next frame will correct state */
        }
      })
      es.addEventListener("heartbeat", () => {
        if (!cancelled) setConnected(true)
      })
      es.addEventListener("error", () => {
        if (!cancelled) setConnected(false)
      })
    }
    void connect()

    return () => {
      cancelled = true
      source?.close()
      setConnected(false)
    }
  }, [runId, enabled])

  return { shadow, connected, waiting }
}
