import { createFileRoute } from "@tanstack/react-router";
import { SiteHeader } from "@/components/site/site-header";
import { SiteFooter } from "@/components/site/site-footer";
import { AuthForm } from "@/components/site/auth-form";

const title = "Sign In — Migration Oracle";
const description = "Sign in to Migration Oracle to plan, predict, and verify database migrations.";

export const Route = createFileRoute("/sign-in")({
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
  component: SignIn,
});

function SignIn() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />
      <main className="flex flex-1 flex-col">
        <AuthForm mode="sign-in" />
      </main>
      <SiteFooter />
    </div>
  );
}