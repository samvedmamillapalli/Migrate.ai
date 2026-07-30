import { createFileRoute } from "@tanstack/react-router";
import { SiteHeader } from "@/components/site/site-header";
import { SiteFooter } from "@/components/site/site-footer";
import { JournalCard } from "@/components/site/journal-card";
import { JOURNAL_ENTRIES } from "@/components/site/site-data";

const title = "Our Journey — Migration Oracle Field Notes";
const description =
  "An evolving record of the engineering questions, experiments, and decisions that shape Migration Oracle.";

export const Route = createFileRoute("/our-journey")({
  head: () => ({
    meta: [
      { title },
      { name: "description", content: description },
      { property: "og:title", content: title },
      { property: "og:description", content: description },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: OurJourney,
});

function OurJourney() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader wordmarkUppercase />
      <main className="flex-1">
        <section className="mx-auto w-full max-w-[1180px] px-6 pb-8 pt-24 text-center sm:pt-32">
          <p className="eyebrow animate-rise text-accent">Field Notes / 2026</p>
          <h1 className="animate-rise font-display mx-auto mt-5 max-w-4xl pb-1 text-[40px] leading-[1.03] tracking-[-1.5px] text-foreground sm:text-[62px]">
            Our journey, made legible.
          </h1>
          <p className="animate-rise mx-auto mt-5 max-w-lg text-[15px] leading-relaxed text-muted-foreground [animation-delay:120ms]">
            {description}
          </p>
        </section>

        <section className="mx-auto w-full max-w-[1180px] space-y-6 px-6 py-16">
          {JOURNAL_ENTRIES.map((entry) => (
            <JournalCard key={entry.href} entry={entry} />
          ))}
        </section>
      </main>
      <SiteFooter
        left="Migration Oracle / 2026"
        right="Engineering notes on Medium"
        bordered
        uppercaseLeft
      />
    </div>
  );
}