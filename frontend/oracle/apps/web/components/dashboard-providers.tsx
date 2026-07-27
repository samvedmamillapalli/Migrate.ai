"use client"

import { ApiAuthBootstrap } from "@/components/api-auth-bootstrap"
import { ClerkOwnerSync } from "@/components/clerk-owner-sync"

export function DashboardProviders({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <>
      <ApiAuthBootstrap />
      <ClerkOwnerSync />
      {children}
    </>
  )
}
