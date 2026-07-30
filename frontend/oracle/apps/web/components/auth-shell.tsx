import Link from "next/link"

import { AuthPageToolbar } from "@/components/auth-page-toolbar"
import { LandingTheme } from "@/components/landing/landing-theme"
import { cn } from "@workspace/ui/lib/utils"

export function AuthShell({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <LandingTheme>
      <main className="bg-background text-foreground flex min-h-svh flex-col">
        <header className="flex shrink-0 items-center px-6 py-5 sm:px-10">
          <Link
            href="/"
            className="text-muted-foreground hover:text-foreground text-[13px] font-medium tracking-tight transition-colors"
          >
            ← Migration Oracle
          </Link>
        </header>

        <div
          className={cn(
            "flex flex-1 flex-col items-center justify-center px-4 pb-10 sm:px-6",
            className
          )}
        >
          <div className="w-full max-w-4xl">
            <AuthPageToolbar />
            {children}
          </div>
        </div>
      </main>
    </LandingTheme>
  )
}
