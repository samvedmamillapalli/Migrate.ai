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
          <SidebarProvider className="h-svh max-h-svh overflow-hidden">
            <AppSidebar />
            <SidebarInset className="bg-background min-h-0 overflow-hidden">
              <DashboardHeader />
              <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
                {children}
              </div>
            </SidebarInset>
          </SidebarProvider>
          <ShadowExecutionWindow />
        </ShadowWatchProvider>
      </TooltipProvider>
    </DashboardProviders>
  )
}
