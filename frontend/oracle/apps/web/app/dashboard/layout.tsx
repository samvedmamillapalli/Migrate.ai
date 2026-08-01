import { AppSidebar } from "@/components/app-sidebar"
import { DashboardHeader } from "@/components/dashboard-header"
import { DashboardProviders } from "@/components/dashboard-providers"
import { ShadowExecutionWindow } from "@/components/shadow-execution-window"
import { ShadowWatchProvider } from "@/components/shadow-watch-context"
import {
  SidebarInset,
  SidebarProvider,
} from "@workspace/ui/components/sidebar"
import { TooltipProvider } from "@workspace/ui/components/tooltip"
import { auth } from "@clerk/nextjs/server"
import { redirect } from "next/navigation"

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { userId } = await auth()
  if (!userId) {
    redirect("/login")
  }

  return (
    <DashboardProviders>
      <TooltipProvider>
        <ShadowWatchProvider>
          <SidebarProvider>
            <AppSidebar />
            <SidebarInset>
            <DashboardHeader />
            {children}
            </SidebarInset>
          </SidebarProvider>
          <ShadowExecutionWindow />
        </ShadowWatchProvider>
      </TooltipProvider>
    </DashboardProviders>
  )
}
