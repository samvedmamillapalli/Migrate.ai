import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

/**
 * When NEXT_PUBLIC_AUTH_ENABLED=true, require an access token cookie/header
 * signal before entering the dashboard. The real Bearer token lives in
 * localStorage (client); this gate only redirects unauthenticated browsers
 * that never visited /login (soft check via cookie mirror).
 */
export function middleware(request: NextRequest) {
  const authOn = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true"
  if (!authOn) {
    return NextResponse.next()
  }

  const { pathname } = request.nextUrl
  if (!pathname.startsWith("/dashboard")) {
    return NextResponse.next()
  }

  const token = request.cookies.get("oracle_access_token")?.value
  if (!token) {
    const url = request.nextUrl.clone()
    url.pathname = "/login"
    url.searchParams.set("next", pathname)
    return NextResponse.redirect(url)
  }
  return NextResponse.next()
}

export const config = {
  matcher: ["/dashboard/:path*"],
}
