"use client"

import * as React from "react"

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
  // Always controlled (`value` never undefined) so Base UI Input does not
  // flip uncontrolled → controlled after localStorage hydration.
  const [value, setValue] = React.useState("")
  const [ready, setReady] = React.useState(false)

  React.useEffect(() => {
    setValue(getOwnerIdentity())
    setReady(true)
  }, [])

  return (
    <div className={className}>
      <Label htmlFor={id} className="text-muted-foreground text-[11px]">
        Owner identity
      </Label>
      <Input
        id={id}
        value={value}
        disabled={!ready}
        onChange={(e) => {
          setValue(e.target.value)
          setOwnerIdentity(e.target.value)
        }}
        placeholder={ready ? "e.g. samved" : "Loading…"}
        className="mt-1.5 h-8 font-mono text-xs"
        autoComplete="username"
      />
      <p className="text-muted-foreground/70 mt-1.5 text-[10px] leading-snug">
        Soft identity for memory scope and approvals. No account system.
      </p>
    </div>
  )
}
