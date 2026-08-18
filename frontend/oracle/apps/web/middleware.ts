import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server"

// Routes that don't require authentication
const isPublicRoute = createRouteMatcher([
  "/",
  "/our-journey(.*)",
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/login(.*)",
  "/signup(.*)",
  "/get-started(.*)",
  "/invite(.*)",
  "/api(.*)",
  "/health(.*)",
])

export default clerkMiddleware(async (auth, req) => {
  if (!isPublicRoute(req)) {
    // Send signed-out visitors to our own sign-in page explicitly.
    //
    // Without unauthenticatedUrl, a bare auth.protect() on a Clerk *development*
    // instance answers a cold request (no __clerk_db_jwt cookie yet) with
    // `x-clerk-auth-reason: protect-rewrite, dev-browser-missing` and an internal
    // rewrite to /clerk_<timestamp>, which surfaces to the visitor as a bare 404
    // instead of a sign-in prompt. Anyone opening a deep link such as
    // /dashboard/migrations/current before signing in hits that dead end.
    // A Clerk sign-in-token magic link (?__clerk_ticket=...) must survive this
    // redirect verbatim — clerk-js only detects and consumes the ticket once
    // it's mounted client-side on /login, and a request carrying it is by
    // definition unauthenticated (no session cookie yet), so it always lands
    // here first. Dropping the param here silently breaks every magic link.
    const unauthenticatedUrl = new URL("/login", req.url)
    const ticket = req.nextUrl.searchParams.get("__clerk_ticket")
    if (ticket) {
      unauthenticatedUrl.searchParams.set("__clerk_ticket", ticket)
    }
    await auth.protect({
      unauthenticatedUrl: unauthenticatedUrl.toString(),
    })
  }
})

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest|mp4|webm|mov)).*)",
    // Always run for API routes
    "/(api|trpc)(.*)",
  ],
}
