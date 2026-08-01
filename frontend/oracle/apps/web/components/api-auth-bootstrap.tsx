"use client"

import { useEffect } from "react"
import { useAuth } from "@clerk/nextjs"

import { setClerkTokenGetter } from "@/lib/api/clerk-token"

/** Registers Clerk getToken() for the shared api() fetch helper. */
export function ApiAuthBootstrap() {
  const { getToken, isLoaded, isSignedIn } = useAuth()

  useEffect(() => {
    if (!isLoaded) return

    setClerkTokenGetter(async () => {
      if (!isSignedIn) return null
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
