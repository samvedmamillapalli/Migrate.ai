import { Link } from "@tanstack/react-router";
import type { FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface AuthFormProps {
  mode: "sign-in" | "sign-up";
}

export function AuthForm({ mode }: AuthFormProps) {
  const isSignUp = mode === "sign-up";

  // Frontend only — wire this submit handler to your existing FastAPI backend.
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
  }

  return (
    <section className="mx-auto flex w-full max-w-[1180px] flex-1 items-center justify-center px-6 py-20">
      <div className="w-full max-w-[440px]">
        <div className="text-center">
          <p className="eyebrow text-accent">{isSignUp ? "Get started" : "Welcome back"}</p>
          <h1 className="font-display mt-4 text-[38px] leading-[1.03] tracking-[-1.5px] text-foreground sm:text-[46px]">
            {isSignUp ? "Create your account." : "Sign in to continue."}
          </h1>
          <p className="mt-3 text-[14px] text-muted-foreground">
            {isSignUp
              ? "Plan, predict, and verify migrations with agentic memory."
              : "Pick up your migrations exactly where you left them."}
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="mt-10 rounded-3xl border border-border bg-surface p-6 sm:p-8"
        >
          <div className="space-y-5">
            {isSignUp && (
              <div className="space-y-2">
                <Label htmlFor="name" className="text-[12px] font-semibold">
                  Full name
                </Label>
                <Input id="name" name="name" placeholder="Ada Lovelace" autoComplete="name" required className="h-11 rounded-xl bg-background" />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="email" className="text-[12px] font-semibold">
                Work email
              </Label>
              <Input
                id="email"
                name="email"
                type="email"
                placeholder="you@company.com"
                autoComplete="email"
                required
                className="h-11 rounded-xl bg-background"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password" className="text-[12px] font-semibold">
                Password
              </Label>
              <Input
                id="password"
                name="password"
                type="password"
                placeholder="••••••••"
                autoComplete={isSignUp ? "new-password" : "current-password"}
                required
                className="h-11 rounded-xl bg-background"
              />
            </div>
          </div>

          <Button type="submit" size="lg" className="mt-7 w-full rounded-full text-[14px]">
            {isSignUp ? "Create account" : "Sign in"}
          </Button>

          <p className="mt-6 text-center text-[13px] text-muted-foreground">
            {isSignUp ? "Already have an account? " : "New to Migration Oracle? "}
            <Link
              to={isSignUp ? "/sign-in" : "/sign-up"}
              className="font-semibold text-foreground underline underline-offset-4"
            >
              {isSignUp ? "Sign in" : "Create one"}
            </Link>
          </p>
        </form>
      </div>
    </section>
  );
}