"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  BookOpen,
  Brain,
  GalleryVerticalEnd,
  History,
  LayoutDashboard,
  Settings2,
  Workflow,
} from "lucide-react"

import { NavMain } from "@/components/nav-main"
import { NavUser } from "@/components/nav-user"
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

const data = {
  user: {
    name: "Operator",
    email: "operator@migrationoracle.dev",
    avatar: "",
  },
  teams: [
    {
      name: "Migration Oracle",
      logo: GalleryVerticalEnd,
      plan: "Workspace",
    },
  ],
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname()

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <TeamSwitcher teams={data.teams} />
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
              isActive: pathname === "/dashboard/migrations/current",
            },
            {
              title: "Past Migrations",
              url: "/dashboard/migrations/history",
              icon: History,
              isActive: pathname === "/dashboard/migrations/history",
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
        <SidebarGroup className="p-0">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                tooltip="Documentation"
                render={<Link href="/docs" />}
              >
                <BookOpen />
                <span>Documentation</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
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
        <NavUser user={data.user} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
