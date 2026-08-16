"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Settings2 } from "lucide-react"

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@workspace/ui/components/sidebar"

/**
 * Settings is a plain link now, not a dropdown.
 *
 * It previously opened a two-item menu whose first entry was "Open settings" —
 * an extra click to reach the only place it could go. Sign out moved to the
 * bottom of the Settings page, where destructive account actions belong and
 * where it cannot be hit by accident from the nav.
 */
export function SidebarSettingsMenu() {
  const pathname = usePathname()

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          tooltip="Settings"
          isActive={pathname === "/dashboard/settings"}
          render={<Link href="/dashboard/settings" />}
        >
          <Settings2 />
          <span>Settings</span>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
