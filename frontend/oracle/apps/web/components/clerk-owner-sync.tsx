"use client"

import { useEffect } from "react"
import { useAuth, useUser } from "@clerk/nextjs"

import { setOwnerIdentity } from "@/lib/api/owner"

/** Map Clerk user id → owner_identity for API scoping and sidebar display. */
export function ClerkOwnerSync() {
  const { isLoaded, isSignedIn, userId } = useAuth()
  const { user } = useUser()

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !userId) return
    setOwnerIdentity(userId)
  }, [isLoaded, isSignedIn, userId, user?.id])

  return null
}
