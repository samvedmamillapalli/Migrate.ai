"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  Brain,
  GalleryVerticalEnd,
  History,
  LayoutDashboard,
  Settings2,
  Workflow,
} from "lucide-react"

import { NavMain } from "@/components/nav-main"
import { OwnerIdentityField } from "@/components/owner-identity-field"
import { TeamSwitcher } from "@/components/team-switcher"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@workspace/ui/components/sidebar"

const teams = [
  {
    name: "Migration Oracle",
    logo: GalleryVerticalEnd,
    plan: "Workspace",
  },
]

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname()

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <TeamSwitcher teams={teams} />
      </SidebarHeader>
      <SidebarContent>
        <NavMain
          items={[
            {
              title: "Overview",
              url: "/dashboard",
              icon: LayoutDashboard,
              isActive: pathname === "/dashboard",
            },
          ]}
        />
        <NavMain
          label="Migrations"
          items={[
            {
              title: "Current Migration",
              url: "/dashboard/migrations/current",
              icon: Workflow,
              isActive: pathname.startsWith("/dashboard/migrations/current"),
            },
            {
              title: "Past Migrations",
              url: "/dashboard/migrations/history",
              icon: History,
              isActive:
                pathname.startsWith("/dashboard/migrations/history") ||
                /^\/dashboard\/migrations\/[^/]+$/.test(pathname),
            },
          ]}
        />
        <NavMain
          label="Intelligence"
          items={[
            {
              title: "Agent Memory",
              url: "/dashboard/memory",
              icon: Brain,
              isActive: pathname === "/dashboard/memory",
            },
          ]}
        />
      </SidebarContent>
      <SidebarFooter>
        <SidebarGroup className="group-data-[collapsible=icon]:hidden p-2">
          <OwnerIdentityField id="owner-identity-sidebar" />
        </SidebarGroup>
        <SidebarGroup className="p-0">
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
        </SidebarGroup>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
