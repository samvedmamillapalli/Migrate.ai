import { AppSidebar } from "@/components/app-sidebar"
import { ShadowExecutionWindow } from "@/components/shadow-execution-window"
import { ShadowWatchProvider } from "@/components/shadow-watch-context"
import { Separator } from "@workspace/ui/components/separator"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@workspace/ui/components/sidebar"
import { TooltipProvider } from "@workspace/ui/components/tooltip"
import { auth } from "@clerk/nextjs/server"
import { redirect } from "next/navigation"

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  // Protect dashboard routes with Clerk auth
  const { userId } = await auth()
  if (!userId) {
    redirect("/login")
  }

  return (
    <TooltipProvider>
      <ShadowWatchProvider>
        <SidebarProvider>
          <AppSidebar />
          <SidebarInset>
            <header className="flex h-16 shrink-0 items-center gap-2 transition-[width,height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:h-12">
              <div className="flex items-center gap-2 px-4">
                <SidebarTrigger className="-ml-1" />
                <Separator
                  orientation="vertical"
                  className="mr-2 data-vertical:h-4 data-vertical:self-auto"
                />
              </div>
            </header>
            {children}
          </SidebarInset>
        </SidebarProvider>
        <ShadowExecutionWindow />
      </ShadowWatchProvider>
    </TooltipProvider>
  )
}
