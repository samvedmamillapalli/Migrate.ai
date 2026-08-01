import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function HeroSection() {
  return (
    <section className="mx-auto w-full max-w-[1180px] px-6 pb-8 pt-16 text-center sm:pt-24">
      <h1 className="animate-text-reveal font-display mx-auto max-w-[1000px] text-balance pb-1 text-[38px] leading-[1.03] tracking-[-1.5px] text-foreground sm:text-[56px] lg:text-[68px]">
        Know your migration{" "}
        <span className="block sm:inline">
          <em className="not-italic font-display italic text-primary">before</em> your database does.
        </span>
      </h1>
      <p className="animate-rise mx-auto mt-6 max-w-xl text-[15px] leading-relaxed text-muted-foreground [animation-delay:120ms]">
        Migration Oracle predicts, verifies, grades, and continuously improves database migrations
        using shadow execution and agentic memory.
      </p>
      <div className="animate-rise mt-8 flex flex-wrap items-center justify-center gap-3 [animation-delay:220ms]">
        <Button asChild size="lg" className="group rounded-full px-6 text-[14px]">
          <Link to="/sign-up">
            Plan a migration
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </Button>
        <Button
          asChild
          size="lg"
          variant="outline"
          className="rounded-full border-border bg-surface px-6 text-[14px]"
        >
          <Link to="/" hash="prediction-learning">
            View the method
          </Link>
        </Button>
      </div>
    </section>
  );
}