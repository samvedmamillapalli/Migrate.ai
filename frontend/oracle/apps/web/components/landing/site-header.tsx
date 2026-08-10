"use client"

import * as React from "react"
import Link from "next/link"
import { Menu, X } from "lucide-react"

import { GITHUB_URL } from "@/components/landing/site-data"
import { buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

const linkClass =
  "text-[13px] text-muted-foreground transition-colors hover:text-foreground"

export function SiteHeader({
  wordmarkUppercase = false,
  compact = false,
}: {
  wordmarkUppercase?: boolean
  compact?: boolean
}) {
  const [open, setOpen] = React.useState(false)

  const navItems = (
    <>
      <Link
        href="/#prediction-learning"
        className={linkClass}
        onClick={() => setOpen(false)}
      >
        How it works
      </Link>
      <a
        href={GITHUB_URL}
        target="_blank"
        rel="noreferrer"
        className={linkClass}
      >
        Github
      </a>
      <Link
        href="/our-journey"
        className={linkClass}
        onClick={() => setOpen(false)}
      >
        Our Journey
      </Link>
    </>
  )

  return (
    <header className="bg-background/85 sticky top-0 z-50 w-full shrink-0 border-b border-transparent backdrop-blur-md">
      <div
        className={cn(
          "mx-auto grid max-w-[1180px] grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-6 md:grid-cols-[1fr_auto_1fr]",
          compact ? "py-2" : "py-4"
        )}
      >
        <Link
          href="/"
          className={cn(
            "text-foreground min-w-0 truncate text-[15px] font-semibold tracking-[0.12em]",
            wordmarkUppercase && "uppercase"
          )}
        >
          Migration Oracle
        </Link>

        <nav className="hidden items-center gap-7 md:flex">{navItems}</nav>

        <div className="hidden items-center justify-end gap-2 md:flex">
          <Link
            href="/login"
            className={cn(
              buttonVariants({ variant: "outline", size: "sm" }),
              "bg-surface rounded-full border-border px-4 text-[13px]"
            )}
          >
            Sign In
          </Link>
          <Link
            href="/get-started"
            className={cn(
              buttonVariants({ size: "sm" }),
              "bg-ink text-ink-foreground hover:bg-ink/90 rounded-full px-4 text-[13px]"
            )}
          >
            Get Started
          </Link>
        </div>

        <button
          type="button"
          aria-label="Toggle menu"
          onClick={() => setOpen((v) => !v)}
          className="border-border text-foreground justify-self-end rounded-full border p-2 md:hidden"
        >
          {open ? <X className="size-4" /> : <Menu className="size-4" />}
        </button>
      </div>

      {open ? (
        <div className="border-border/60 bg-background border-t px-6 py-5 md:hidden">
          <nav className="flex flex-col gap-4">{navItems}</nav>
          <div className="mt-5 flex gap-2">
            <Link
              href="/login"
              onClick={() => setOpen(false)}
              className={cn(
                buttonVariants({ variant: "outline", size: "sm" }),
                "bg-surface flex-1 rounded-full"
              )}
            >
              Sign In
            </Link>
            <Link
              href="/get-started"
              onClick={() => setOpen(false)}
              className={cn(
                buttonVariants({ size: "sm" }),
                "bg-ink text-ink-foreground hover:bg-ink/90 flex-1 rounded-full"
              )}
            >
              Get Started
            </Link>
          </div>
        </div>
      ) : null}
    </header>
  )
}
