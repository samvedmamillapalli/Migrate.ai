"use client"

import * as React from "react"

import { useThemePreference } from "@/components/theme-provider"
import { AnimatedThemeToggler } from "@/components/ui/animated-theme-toggler"
import { buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useThemePreference()
  const [mounted, setMounted] = React.useState(false)

  React.useEffect(() => {
    setMounted(true)
  }, [])

  const buttonClass = cn(
    buttonVariants({ variant: "ghost", size: "icon-sm" }),
    "text-muted-foreground hover:text-foreground relative z-50 rounded-full",
    className
  )

  if (!mounted) {
    return (
      <button
        type="button"
        className={buttonClass}
        aria-label="Toggle theme"
        disabled
      >
        <span className="bg-foreground/40 size-4 rounded-full" />
      </button>
    )
  }

  return (
    <AnimatedThemeToggler
      variant="circle"
      duration={550}
      theme={theme}
      onThemeChange={setTheme}
      className={buttonClass}
      aria-label="Toggle theme"
    />
  )
}
