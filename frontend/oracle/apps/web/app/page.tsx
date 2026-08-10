import { HeroSection } from "@/components/landing/hero-section"
import { LandingTheme } from "@/components/landing/landing-theme"
import { LockLandingViewport } from "@/components/landing/lock-landing-viewport"
import { PipelineSection } from "@/components/landing/pipeline-section"
import { SiteFooter } from "@/components/landing/site-footer"
import { SiteHeader } from "@/components/landing/site-header"
import { TechMarquee } from "@/components/landing/tech-marquee"

export default function Page() {
  return (
    <LandingTheme>
      <LockLandingViewport>
        <div className="bg-background flex h-dvh max-h-dvh flex-col overflow-hidden">
          <SiteHeader compact />
          <main className="flex min-h-0 flex-1 flex-col justify-between overflow-hidden">
            <HeroSection compact />
            <PipelineSection compact />
            <div className="shrink-0">
              <TechMarquee compact />
              <SiteFooter compact />
            </div>
          </main>
        </div>
      </LockLandingViewport>
    </LandingTheme>
  )
}
