import { Hero } from "@/components/landing/Hero"
import { HowItWorks } from "@/components/landing/HowItWorks"
import { Navbar } from "@/components/landing/Navbar"

export default function Page() {
  return (
    <div className="bg-background text-foreground min-h-svh">
      <Navbar />
      <main>
        <Hero />
        <HowItWorks />
      </main>
    </div>
  )
}
