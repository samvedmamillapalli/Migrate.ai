"use client"

import Link from "next/link"
import { SignedIn, useClerk } from "@clerk/nextjs"

import { performSignOut } from "@/lib/auth/sign-out"
import { buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

/** Top-right actions on login / get-started when already signed in. */
export function AuthPageToolbar() {
  const { signOut } = useClerk()

  return (
    <div className="mb-4 flex flex-wrap items-center justify-end gap-2">
      <SignedIn>
        <Link
          href="/dashboard"
          className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
        >
          Dashboard
        </Link>
        <button
          type="button"
          className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
          onClick={() => void performSignOut(signOut)}
        >
          Sign out
        </button>
      </SignedIn>
    </div>
  )
}
