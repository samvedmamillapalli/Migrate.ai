"use client"

import { LogOut } from "lucide-react"
import { useClerk } from "@clerk/nextjs"

import { performSignOut } from "@/lib/auth/sign-out"
import { Button } from "@workspace/ui/components/button"

export function DashboardSignOutButton() {
  const { signOut } = useClerk()

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="gap-1.5 font-normal"
      onClick={() => void performSignOut(signOut)}
    >
      <LogOut className="size-3.5" aria-hidden />
      Sign out
    </Button>
  )
}
