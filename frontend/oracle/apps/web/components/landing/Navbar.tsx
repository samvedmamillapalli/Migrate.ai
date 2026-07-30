"use client"

import * as React from "react"
import Link from "next/link"
import { Menu } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@workspace/ui/components/sheet"
import { cn } from "@workspace/ui/lib/utils"

const NAV_LINKS = [
  { href: "#how-it-works", label: "How it works", anchor: true },
  {
    href: "https://github.com/samvedmamillapalli/migration_oracle",
    label: "Github",
    external: true,
  },
  { href: "#journey", label: "Our Journey", anchor: true },
] as const

function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex size-6 shrink-0 items-center justify-center rounded-md bg-[#1f1b1a]",
        className
      )}
    >
      <span className="size-2 rounded-[2px] bg-[#fffcf9]" />
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
          ? "border-[#1f1b1a]/8 bg-[#f8f5f1]/85 border-b backdrop-blur-md"
          : "border-transparent bg-transparent border-b"
      )}
    >
      <nav
        aria-label="Primary"
        className="mx-auto flex h-[72px] w-full max-w-6xl items-center justify-between px-6 md:px-8"
      >
        <Link
          href="/"
          className="flex items-center gap-2.5 font-medium tracking-tight text-[#1f1b1a] transition-opacity duration-200 hover:opacity-90"
        >
          <BrandMark />
          <span className="text-sm md:text-[15px]">Migration Oracle</span>
        </Link>

        <div className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-1 md:flex">
          {NAV_LINKS.map((link) => (
            <NavLink key={link.href} {...link} />
          ))}
        </div>

        <div className="hidden items-center gap-2 md:flex">
          <Link
            href="/get-started"
            className="inline-flex h-9 items-center justify-center rounded-full bg-[#1f1b1a] px-4 text-sm font-medium text-[#fffcf9] transition-opacity hover:opacity-90"
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
                className="rounded-full text-[#1f1b1a] md:hidden"
                aria-label="Open menu"
              />
            }
          >
            <Menu />
          </SheetTrigger>
          <SheetContent
            side="right"
            className="w-full gap-0 border-[#1f1b1a]/10 bg-[#fffcf9] sm:max-w-xs"
          >
            <SheetHeader className="border-b border-[#1f1b1a]/10">
              <SheetTitle className="flex items-center gap-2.5 text-[#1f1b1a]">
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
            <div className="mt-auto border-t border-[#1f1b1a]/10 p-4">
              <Link
                href="/get-started"
                onClick={() => setMobileOpen(false)}
                className="inline-flex h-11 w-full items-center justify-center rounded-full bg-[#1f1b1a] text-sm font-medium text-[#fffcf9]"
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
    "rounded-full px-3.5 py-2 text-sm text-[#716b67] transition-colors duration-200 hover:text-[#1f1b1a]",
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
