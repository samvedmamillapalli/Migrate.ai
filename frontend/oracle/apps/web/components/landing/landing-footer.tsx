"use client"

import Link from "next/link"

export function LandingFooter() {
  return (
    <footer
      id="journey"
      className="border-t border-[#1f1b1a]/8 px-6 py-12 md:px-8"
    >
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-[family-name:var(--font-display)] text-xl font-medium tracking-[-0.02em] text-[#1f1b1a]">
            Migration Oracle{" "}
            <span className="text-[#716b67]">/ 2026</span>
          </p>
          <p className="mt-1 text-sm text-[#716b67]">
            AI-powered database migration
          </p>
        </div>
        <div className="flex items-center gap-4 text-sm text-[#716b67]">
          <Link href="/login" className="hover:text-[#1f1b1a]">
            Sign in
          </Link>
          <Link href="/get-started" className="hover:text-[#1f1b1a]">
            Get Started
          </Link>
          <a
            href="https://github.com/samvedmamillapalli/migration_oracle"
            target="_blank"
            rel="noreferrer"
            className="hover:text-[#1f1b1a]"
          >
            Github
          </a>
        </div>
      </div>
    </footer>
  )
}
