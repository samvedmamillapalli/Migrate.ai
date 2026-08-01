import { HeroSection } from "@/components/landing/hero-section"
import { LandingTheme } from "@/components/landing/landing-theme"
import { MediaShowcase } from "@/components/landing/media-showcase"
import { PipelineSection } from "@/components/landing/pipeline-section"
import { SiteFooter } from "@/components/landing/site-footer"
import { SiteHeader } from "@/components/landing/site-header"
import { TechMarquee } from "@/components/landing/tech-marquee"

export default function Page() {
  return (
    <LandingTheme>
      <div className="bg-background flex min-h-svh flex-col">
        <SiteHeader />
        <main className="flex-1">
          <HeroSection />
          <MediaShowcase />
          <PipelineSection />
          <TechMarquee />
        </main>
        <SiteFooter />
      </div>
    </LandingTheme>
  )
}
