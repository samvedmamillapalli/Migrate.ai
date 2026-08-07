"use client"

import Link from "next/link"
import { SignIn } from "@clerk/nextjs"

import { AuthTerminalPreview } from "@/components/auth-terminal-preview"
import { Card, CardContent } from "@workspace/ui/components/card"
import { clerkAppearance } from "@/lib/clerk-appearance"
import { cn } from "@workspace/ui/lib/utils"

export function LoginForm({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div className={cn("flex w-full flex-col gap-4", className)} {...props}>
      <Card className="border-border bg-surface overflow-hidden p-0 shadow-[0_1px_0_0_rgba(0,0,0,0.02)]">
        <CardContent className="grid p-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
          <div className="bg-surface text-foreground flex flex-col justify-center px-6 py-8 sm:px-8 md:py-10">
            <SignIn
              routing="path"
              path="/login"
              appearance={clerkAppearance}
              signUpUrl="/get-started"
              forceRedirectUrl="/dashboard"
              fallbackRedirectUrl="/dashboard"
            />
            <p className="text-muted-foreground mt-6 text-center text-sm md:hidden">
              Don&apos;t have an account?{" "}
              <Link
                href="/get-started"
                className="text-primary font-medium underline underline-offset-4"
              >
                Get started
              </Link>
            </p>
          </div>

          <div className="bg-surface-tint border-border relative hidden min-h-[28rem] border-l md:block">
            <AuthTerminalPreview className="absolute inset-0" />
          </div>
        </CardContent>
      </Card>


    </div>
  )
}
