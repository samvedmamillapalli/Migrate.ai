"use client"

import * as React from "react"
import { useAuth, useUser } from "@clerk/nextjs"

import {
  getOwnerIdentity,
  setOwnerIdentity,
} from "@/lib/api/owner"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"

export function OwnerIdentityField({
  id = "owner-identity",
  className,
}: {
  id?: string
  className?: string
}) {
  const { isLoaded, isSignedIn, userId } = useAuth()
  const { user } = useUser()
  const [value, setValue] = React.useState("")
  const [ready, setReady] = React.useState(false)

  const clerkLocked = isLoaded && isSignedIn && Boolean(userId)
  // owner_identity sent to the backend is always the raw Clerk user id — this
  // only changes what's *displayed*. A raw "user_..." id means nothing to a
  // viewer; the real id stays available via the title tooltip for debugging.
  const displayName =
    user?.fullName ||
    user?.primaryEmailAddress?.emailAddress ||
    user?.username ||
    userId ||
    ""

  React.useEffect(() => {
    if (clerkLocked && userId) {
      setOwnerIdentity(userId)
      setReady(true)
      return
    }
    setValue(getOwnerIdentity())
    setReady(true)
  }, [clerkLocked, userId])

  return (
    <div className={className}>
      <Label htmlFor={id} className="text-muted-foreground text-[11px]">
        Owner identity
      </Label>
      <Input
        id={id}
        value={clerkLocked ? displayName : value}
        readOnly={clerkLocked}
        disabled={!ready}
        title={clerkLocked ? userId ?? undefined : undefined}
        onChange={(e) => {
          if (clerkLocked) return
          setValue(e.target.value)
          setOwnerIdentity(e.target.value)
        }}
        placeholder={ready ? "e.g. samved" : "Loading…"}
        className="mt-1.5 h-8 font-mono text-xs"
        autoComplete="username"
      />
      <p className="text-muted-foreground/70 mt-1.5 text-[10px] leading-snug">
        {clerkLocked
          ? "Scoped to your signed-in account. Hover to see the raw id."
          : "Scopes runs and memories. Set manually when auth is off."}
      </p>
    </div>
  )
}
