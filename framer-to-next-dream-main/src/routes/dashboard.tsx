import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowUpRight } from "lucide-react";
import { SiteHeader } from "@/components/site/site-header";
import { SiteFooter } from "@/components/site/site-footer";
import { PIPELINE_STEPS } from "@/components/site/site-data";

const title = "Dashboard — Migration Oracle";
const description = "Your migration workspace: runs, predictions, and shadow execution results.";

export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      { title },
      { name: "description", content: description },
      { property: "og:title", content: title },
      { property: "og:description", content: description },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Dashboard,
});

function Dashboard() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />
      <main className="mx-auto w-full max-w-[1180px] flex-1 px-6 py-16">
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 sm:flex sm:justify-between">
          <div className="min-w-0">
            <p className="eyebrow text-accent">Workspace</p>
            <h1 className="font-display mt-3 truncate text-[34px] leading-[1.03] tracking-[-1.5px] text-foreground sm:text-[44px]">
              Dashboard
            </h1>
          </div>
          <Link
            to="/"
            hash="prediction-learning"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-surface px-4 py-2 text-[12px] font-semibold text-foreground"
          >
            View the method
            <ArrowUpRight className="size-3.5" />
          </Link>
        </div>

        <p className="mt-4 max-w-xl text-[14px] text-muted-foreground">
          Placeholder workspace. Migration runs, predictions, and grades will render here once
          connected to your API.
        </p>

        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {PIPELINE_STEPS.map((step) => (
            <div key={step.title} className="rounded-2xl border border-border bg-surface p-6">
              <h2 className="text-[13px] font-semibold text-foreground">{step.title}</h2>
              <p className="mt-2 text-[12px] text-muted-foreground">{step.description}</p>
              <div className="mt-6 h-24 rounded-xl border border-dashed border-border bg-surface-tint" />
            </div>
          ))}
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}