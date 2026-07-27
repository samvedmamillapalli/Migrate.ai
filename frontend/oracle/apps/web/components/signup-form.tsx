"use client"

import Link from "next/link"
import { SignUp } from "@clerk/nextjs"

import { AuthTerminalPreview } from "@/components/auth-terminal-preview"
import { Card, CardContent } from "@workspace/ui/components/card"
import { clerkAppearance } from "@/lib/clerk-appearance"
import { cn } from "@workspace/ui/lib/utils"

export function SignupForm({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div className={cn("flex w-full flex-col gap-4", className)} {...props}>
      <Card className="bg-card overflow-hidden border-border/60 p-0 shadow-sm">
        <CardContent className="grid p-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
          <div className="bg-card text-card-foreground flex flex-col justify-center px-6 py-8 sm:px-8 md:py-10">
            <SignUp
              routing="path"
              path="/get-started"
              appearance={clerkAppearance}
              signInUrl="/login"
              forceRedirectUrl="/dashboard"
              fallbackRedirectUrl="/dashboard"
            />
            <p className="text-muted-foreground mt-6 text-center text-sm md:hidden">
              Already have an account?{" "}
              <Link
                href="/login"
                className="text-foreground underline underline-offset-4"
              >
                Sign in
              </Link>
            </p>
          </div>

          <div className="bg-muted/40 border-border/50 relative hidden min-h-[28rem] border-l md:block">
            <AuthTerminalPreview className="absolute inset-0" />
          </div>
        </CardContent>
      </Card>

      <p className="text-muted-foreground text-center text-xs leading-relaxed">
        By continuing, you agree to our Terms of Service and Privacy Policy.
      </p>
    </div>
  )
}
