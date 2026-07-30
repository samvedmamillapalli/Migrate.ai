import { createFileRoute } from "@tanstack/react-router";
import { SiteHeader } from "@/components/site/site-header";
import { SiteFooter } from "@/components/site/site-footer";
import { AuthForm } from "@/components/site/auth-form";

const title = "Get Started — Migration Oracle";
const description =
  "Create a Migration Oracle account to plan migrations with prediction, shadow execution, and agentic memory.";

export const Route = createFileRoute("/sign-up")({
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
  component: SignUp,
});

function SignUp() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <SiteHeader />
      <main className="flex flex-1 flex-col">
        <AuthForm mode="sign-up" />
      </main>
      <SiteFooter />
    </div>
  );
}