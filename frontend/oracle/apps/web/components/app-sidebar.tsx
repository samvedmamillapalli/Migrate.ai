"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  Brain,
  GalleryVerticalEnd,
  History,
  LayoutDashboard,
  Workflow,
} from "lucide-react"

import { NavMain } from "@/components/nav-main"
import { NavUser } from "@/components/nav-user"
import { OwnerIdentityField } from "@/components/owner-identity-field"
import { SidebarSettingsMenu } from "@/components/sidebar-settings-menu"
import { TeamSwitcher } from "@/components/team-switcher"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
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
        <SidebarGroup className="p-2 pt-0">
          <NavUser
            user={{
              name: "Operator",
              email: "",
            }}
          />
        </SidebarGroup>
        <SidebarGroup className="p-0">
          <SidebarSettingsMenu />
        </SidebarGroup>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
