import { createFileRoute } from "@tanstack/react-router";
import { SiteHeader } from "@/components/site/site-header";
import { SiteFooter } from "@/components/site/site-footer";
import { HeroSection } from "@/components/site/hero-section";
import { MediaShowcase } from "@/components/site/media-showcase";
import { PipelineSection } from "@/components/site/pipeline-section";
import { TechMarquee } from "@/components/site/tech-marquee";

const title = "Migration Oracle — Know your migration before your database does";
const description =
  "Migration Oracle predicts, verifies, grades, and continuously improves database migrations using shadow execution and agentic memory.";

export const Route = createFileRoute("/")({
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
  component: Index,
});

function Index() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />
      <main className="flex-1">
        <HeroSection />
        <MediaShowcase />
        <PipelineSection />
        <TechMarquee />
      </main>
      <SiteFooter />
    </div>
  );
}
