"use client"

import * as React from "react"
import Link from "next/link"
import { Menu } from "lucide-react"

import { ThemeToggle } from "@/components/theme-toggle"
import { Button, buttonVariants } from "@workspace/ui/components/button"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@workspace/ui/components/sheet"
import { cn } from "@workspace/ui/lib/utils"

const NAV_LINKS = [
  { href: "#how-it-works", label: "How It Works", anchor: true },
  {
    href: "https://github.com/samvedmamillapalli/migration_oracle",
    label: "GitHub",
    external: true,
  },
] as const

function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "bg-foreground flex size-6 shrink-0 items-center justify-center rounded-md",
        className
      )}
    >
      <span className="bg-background size-2 rounded-[2px]" />
    </span>
  )
}

function scrollToAnchor(hash: string) {
  const id = hash.replace(/^#/, "")
  const target = document.getElementById(id)
  if (!target) return
  target.scrollIntoView({ behavior: "smooth", block: "start" })
}

export function Navbar() {
  const [scrolled, setScrolled] = React.useState(false)
  const [mobileOpen, setMobileOpen] = React.useState(false)

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])

  return (
    <header
      className={cn(
        "sticky top-0 z-50 w-full transition-[background-color,border-color,backdrop-filter] duration-200",
        scrolled
          ? "border-border/60 bg-background/80 border-b backdrop-blur-md"
          : "border-transparent bg-transparent border-b"
      )}
    >
      <nav
        aria-label="Primary"
        className="mx-auto flex h-[72px] w-full max-w-7xl items-center justify-between px-6 md:px-8"
      >
        <Link
          href="/"
          className="text-foreground flex items-center gap-2.5 font-medium tracking-tight transition-opacity duration-200 hover:opacity-90"
        >
          <BrandMark />
          <span className="text-sm md:text-[15px]">Migration Oracle</span>
        </Link>

        <div className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-3 lg:gap-4 md:flex">
          {NAV_LINKS.map((link) => (
            <NavLink key={link.href} {...link} />
          ))}
        </div>

        <div className="hidden items-center gap-2 md:flex">
          <ThemeToggle />
          <Link
            href="/login"
            className={cn(
              buttonVariants({ variant: "ghost", size: "sm" }),
              "rounded-full px-4 transition-colors duration-200"
            )}
          >
            Sign in
          </Link>
          <Link
            href="/signup"
            className={cn(
              buttonVariants({ variant: "default", size: "sm" }),
              "rounded-full px-4 transition-colors duration-200"
            )}
          >
            Get Started
          </Link>
        </div>

        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className="rounded-full md:hidden"
                aria-label="Open menu"
              />
            }
          >
            <Menu />
          </SheetTrigger>
          <SheetContent side="right" className="w-full gap-0 sm:max-w-xs">
            <SheetHeader className="border-border/60 border-b">
              <SheetTitle className="flex items-center gap-2.5">
                <BrandMark />
                Migration Oracle
              </SheetTitle>
            </SheetHeader>
            <div className="flex flex-1 flex-col gap-1 px-4 py-4">
              {NAV_LINKS.map((link) => (
                <NavLink
                  key={link.href}
                  {...link}
                  className="w-full justify-start px-3.5 py-2.5"
                  onNavigate={() => setMobileOpen(false)}
                />
              ))}
            </div>
            <div className="border-border/60 mt-auto flex flex-col gap-2 border-t p-4">
              <div className="mb-1 flex items-center justify-between px-1">
                <span className="text-muted-foreground text-sm">Theme</span>
                <ThemeToggle />
              </div>
              <Link
                href="/login"
                onClick={() => setMobileOpen(false)}
                className={cn(
                  buttonVariants({ variant: "ghost" }),
                  "rounded-full transition-colors duration-200"
                )}
              >
                Sign in
              </Link>
              <Link
                href="/signup"
                onClick={() => setMobileOpen(false)}
                className={cn(
                  buttonVariants({ variant: "default" }),
                  "rounded-full transition-colors duration-200"
                )}
              >
                Get Started
              </Link>
            </div>
          </SheetContent>
        </Sheet>
      </nav>
    </header>
  )
}

function NavLink({
  href,
  label,
  anchor,
  external,
  className,
  onNavigate,
}: {
  href: string
  label: string
  anchor?: boolean
  external?: boolean
  className?: string
  onNavigate?: () => void
}) {
  const classes = cn(
    "text-muted-foreground hover:text-foreground rounded-full px-3.5 py-2 text-sm transition-colors duration-200",
    className
  )

  if (external) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className={classes}
        onClick={onNavigate}
      >
        {label}
      </a>
    )
  }

  if (anchor) {
    return (
      <a
        href={href}
        className={classes}
        onClick={(e) => {
          e.preventDefault()
          scrollToAnchor(href)
          onNavigate?.()
        }}
      >
        {label}
      </a>
    )
  }

  return (
    <Link href={href} className={classes} onClick={onNavigate}>
      {label}
    </Link>
  )
}
