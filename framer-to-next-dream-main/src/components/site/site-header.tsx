import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { GITHUB_URL } from "./site-data";
import { cn } from "@/lib/utils";

const linkClass =
  "text-[13px] text-muted-foreground transition-colors hover:text-foreground";

export function SiteHeader({ wordmarkUppercase = false }: { wordmarkUppercase?: boolean }) {
  const [open, setOpen] = useState(false);

  const navItems = (
    <>
      <Link to="/" hash="prediction-learning" className={linkClass} onClick={() => setOpen(false)}>
        How it works
      </Link>
      <a href={GITHUB_URL} target="_blank" rel="noreferrer" className={linkClass}>
        Github
      </a>
      <Link
        to="/our-journey"
        className={linkClass}
        activeProps={{ className: "text-foreground font-medium" }}
        onClick={() => setOpen(false)}
      >
        Our Journey
      </Link>
    </>
  );

  return (
    <header className="sticky top-0 z-50 w-full border-b border-transparent bg-background/85 backdrop-blur-md">
      <div className="mx-auto grid max-w-[1180px] grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-6 py-4 md:grid-cols-[1fr_auto_1fr]">
        <Link
          to="/"
          className={cn(
            "min-w-0 truncate text-[15px] font-semibold tracking-[0.12em] text-foreground",
            wordmarkUppercase && "uppercase",
          )}
        >
          Migration Oracle
        </Link>

        <nav className="hidden items-center gap-7 md:flex">{navItems}</nav>

        <div className="hidden items-center justify-end gap-2 md:flex">
          <Button asChild variant="outline" size="sm" className="rounded-full border-border bg-surface px-4 text-[13px]">
            <Link to="/sign-in">Sign In</Link>
          </Button>
          <Button asChild size="sm" className="rounded-full bg-ink px-4 text-[13px] text-ink-foreground hover:bg-ink/90">
            <Link to="/sign-up">Get Started</Link>
          </Button>
        </div>

        <button
          type="button"
          aria-label="Toggle menu"
          onClick={() => setOpen((v) => !v)}
          className="justify-self-end rounded-full border border-border p-2 text-foreground md:hidden"
        >
          {open ? <X className="size-4" /> : <Menu className="size-4" />}
        </button>
      </div>

      {open && (
        <div className="border-t border-border/60 bg-background px-6 py-5 md:hidden">
          <nav className="flex flex-col gap-4">{navItems}</nav>
          <div className="mt-5 flex gap-2">
            <Button asChild variant="outline" size="sm" className="flex-1 rounded-full bg-surface">
              <Link to="/sign-in">Sign In</Link>
            </Button>
            <Button asChild size="sm" className="flex-1 rounded-full bg-ink text-ink-foreground hover:bg-ink/90">
              <Link to="/sign-up">Get Started</Link>
            </Button>
          </div>
        </div>
      )}
    </header>
  );
}