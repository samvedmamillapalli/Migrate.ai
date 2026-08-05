"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useUser } from "@clerk/nextjs"
import {
  Brain,
  Clock,
  Database,
  LayoutGrid,
  PanelLeftClose,
  PlusCircle,
  Zap,
  type LucideIcon,
} from "lucide-react"

import { SidebarSettingsMenu } from "@/components/sidebar-settings-menu"
import { WorkspaceSwitcher } from "@/components/workspace-switcher"
import { listMemories, listRuns } from "@/lib/api/endpoints"
import { getOwnerIdentity } from "@/lib/api/owner"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@workspace/ui/components/sidebar"
import { cn } from "@workspace/ui/lib/utils"

type NavItem = {
  title: string
  url: string
  icon: LucideIcon
  isActive: boolean
  badge?: number | null
}

function NavSection({ label, items }: { label?: string; items: NavItem[] }) {
  return (
    <SidebarGroup className="py-1">
      {label ? (
        <SidebarGroupLabel className="section-label px-2.5 pt-2 pb-1.5">
          {label}
        </SidebarGroupLabel>
      ) : null}
      <SidebarMenu>
        {items.map((item) => (
          <SidebarMenuItem key={item.title}>
            <SidebarMenuButton
              tooltip={item.title}
              isActive={item.isActive}
              className={cn(
                "h-auto gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium",
                item.isActive
                  ? "bg-muted text-primary"
                  : "text-secondary-foreground hover:bg-muted hover:text-foreground"
              )}
              render={<Link href={item.url} />}
            >
              <item.icon
                strokeWidth={1.75}
                className={cn(
                  "size-[18px] shrink-0",
                  item.isActive ? "text-primary" : "text-muted-foreground"
                )}
              />
              <span className="flex-1 truncate">{item.title}</span>
            </SidebarMenuButton>
            {item.badge ? (
              <SidebarMenuBadge className="bg-muted text-muted-foreground rounded-full px-1.5 text-[11px] font-semibold tabular-nums">
                {item.badge}
              </SidebarMenuBadge>
            ) : null}
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  )
}

/**
 * Live sidebar badges.
 *
 * The design shows a "1" beside Current Migration and "36" beside Agent
 * Memory. Both are real here: the first is the number of runs actually
 * waiting on a human decision, the second the size of the memory corpus.
 * Either renders nothing when the count is zero or unavailable — a badge is
 * never shown for a number we don't have.
 */
function useSidebarCounts(pathname: string) {
  const [awaiting, setAwaiting] = React.useState<number | null>(null)
  const [memories, setMemories] = React.useState<number | null>(null)

  // Re-fetch on every navigation. Approving something changes the queue count,
  // and a grade adds a memory — a badge fetched once at mount goes stale the
  // moment you act, and the sidebar is exactly where you'd notice.
  React.useEffect(() => {
    let cancelled = false
    async function load() {
      const owner = getOwnerIdentity()
      const [queue, corpus] = await Promise.allSettled([
        listRuns({
          limit: 1,
          status: "awaiting_approval",
          exclude_kinds: "chaos,debug",
          ...(owner ? { owner_identity: owner } : {}),
        }),
        listMemories({
          limit: 1,
          ...(owner ? { owner_identity: owner } : {}),
        }),
      ])
      if (cancelled) return
      if (queue.status === "fulfilled") setAwaiting(queue.value.total)
      if (corpus.status === "fulfilled") setMemories(corpus.value.total)
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [pathname])

  return { awaiting, memories }
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const pathname = usePathname()
  const { toggleSidebar } = useSidebar()
  const { user, isLoaded } = useUser()
  const { awaiting, memories } = useSidebarCounts(pathname)

  // Clerk resolves client-side only, so the server render has no user. Gate on
  // isLoaded rather than rendering a "Not signed in" placeholder the client
  // then replaces — that swap is a hydration mismatch.
  const ownerName = isLoaded
    ? user?.fullName || user?.username || user?.primaryEmailAddress?.emailAddress
    : undefined
  const ownerEmail = isLoaded ? user?.primaryEmailAddress?.emailAddress : undefined

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader className="px-4 pt-5 pb-4">
        <div className="flex items-start gap-2.5">
          <div className="bg-primary/10 mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md">
            <Database className="text-primary size-3.5" strokeWidth={2} />
          </div>
          <div className="flex-1 group-data-[collapsible=icon]:hidden">
            <div className="text-foreground text-[15px] leading-tight font-bold tracking-tight">
              Migration Oracle
            </div>
          </div>
          <button
            type="button"
            aria-label="Collapse sidebar"
            onClick={toggleSidebar}
            className="text-muted-foreground hover:text-foreground mt-1 transition-colors group-data-[collapsible=icon]:hidden"
          >
            <PanelLeftClose className="size-4" />
          </button>
        </div>
        <div className="mt-3">
          <WorkspaceSwitcher />
        </div>
      </SidebarHeader>

      <SidebarContent className="px-1">
        <NavSection
          items={[
            {
              title: "Overview",
              url: "/dashboard",
              icon: LayoutGrid,
              isActive: pathname === "/dashboard",
            },
          ]}
        />
        <NavSection
          label="Migrations"
          items={[
            {
              title: "New Migration",
              url: "/dashboard/migrations/new",
              icon: PlusCircle,
              isActive: pathname === "/dashboard/migrations/new",
            },
            {
              title: "Current Migration",
              url: "/dashboard/migrations/current",
              icon: Zap,
              isActive: pathname.startsWith("/dashboard/migrations/current"),
              badge: awaiting,
            },
            {
              title: "Past Migrations",
              url: "/dashboard/migrations/history",
              icon: Clock,
              isActive:
                pathname.startsWith("/dashboard/migrations/history") ||
                /^\/dashboard\/migrations\/[0-9a-f-]{8,}$/i.test(pathname),
            },
          ]}
        />
        <NavSection
          label="Intelligence"
          items={[
            {
              title: "Agent Memory",
              url: "/dashboard/memory",
              icon: Brain,
              isActive: pathname === "/dashboard/memory",
              badge: memories,
            },
          ]}
        />
      </SidebarContent>

      <SidebarFooter className="gap-0 p-0">
        <div className="px-3 pb-3 group-data-[collapsible=icon]:hidden">
          <div className="section-label px-3 pb-2">Owner Identity</div>
          <div className="bg-muted rounded-lg px-3 py-2.5">
            <div className="text-foreground truncate text-sm font-semibold">
              {ownerName ?? " "}
            </div>
            <div
              className="text-muted-foreground truncate text-xs"
              title={ownerEmail}
            >
              {ownerEmail ?? " "}
            </div>
          </div>
        </div>
        <div className="border-border border-t px-3 py-3">
          <SidebarSettingsMenu />
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
