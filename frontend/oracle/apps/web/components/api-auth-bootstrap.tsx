"use client"

import { useEffect } from "react"
import { useAuth } from "@clerk/nextjs"

import { markUnauthenticated, setClerkTokenGetter } from "@/lib/api/clerk-token"

/** Registers Clerk getToken() for the shared api() fetch helper. */
export function ApiAuthBootstrap() {
  const { getToken, isLoaded, isSignedIn } = useAuth()

  useEffect(() => {
    if (!isLoaded) return

    if (!isSignedIn) {
      // Release the gate in resolveAuthToken — otherwise every request on a
      // signed-out page waits out the full timeout before failing.
      markUnauthenticated()
      setClerkTokenGetter(null)
      return
    }

    setClerkTokenGetter(async () => {
      try {
        return (await getToken()) ?? null
      } catch {
        return null
      }
    })

    return () => setClerkTokenGetter(null)
  }, [getToken, isLoaded, isSignedIn])

  return null
}
