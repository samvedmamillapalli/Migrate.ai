"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { usePathname } from "next/navigation"
import { LogOut, Settings2 } from "lucide-react"
import { useClerk } from "@clerk/nextjs"

import { performSignOut } from "@/lib/auth/sign-out"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@workspace/ui/components/sidebar"

export function SidebarSettingsMenu() {
  const pathname = usePathname()
  const router = useRouter()
  const { isMobile } = useSidebar()
  const { signOut } = useClerk()

  function handleSignOut() {
    void performSignOut(signOut)
  }

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <SidebarMenuButton
                tooltip="Settings & sign out"
                isActive={pathname === "/dashboard/settings"}
                className="data-open:bg-sidebar-accent data-open:text-sidebar-accent-foreground"
              />
            }
          >
            <Settings2 />
            <span>Settings</span>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="min-w-48 rounded-lg"
            side={isMobile ? "bottom" : "right"}
            align="end"
            sideOffset={6}
          >
            <DropdownMenuGroup>
              <DropdownMenuItem
                onClick={() => router.push("/dashboard/settings")}
              >
                <Settings2 />
                Open settings
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem variant="destructive" onClick={handleSignOut}>
                <LogOut />
                Log out
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
