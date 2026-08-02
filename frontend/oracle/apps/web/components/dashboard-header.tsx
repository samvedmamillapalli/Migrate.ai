"use client"

import { Database } from "lucide-react"

import { SidebarTrigger } from "@workspace/ui/components/sidebar"

/**
 * Mobile-only chrome.
 *
 * The workspace design has no top bar — the sidebar is the only navigation
 * chrome and on desktop it is always present. Below `md` the sidebar
 * collapses into a sheet, so its trigger has to live somewhere; this is that
 * somewhere. Sign-out moved into the sidebar's Settings menu.
 */
export function DashboardHeader() {
  return (
    <header className="border-border flex h-14 shrink-0 items-center gap-3 border-b px-4 md:hidden">
      <SidebarTrigger className="-ml-1" />
      <div className="flex items-center gap-2">
        <div className="bg-primary/10 flex size-5 items-center justify-center rounded">
          <Database className="text-primary size-3" strokeWidth={2} />
        </div>
        <span className="text-foreground text-sm font-bold tracking-tight">
          Migration Oracle
        </span>
      </div>
    </header>
  )
}
