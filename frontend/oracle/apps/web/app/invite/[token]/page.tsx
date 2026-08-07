"use client"

import * as React from "react"
import Link from "next/link"
import { useParams, useRouter } from "next/navigation"
import { SignIn } from "@clerk/nextjs"
import { useAuth } from "@clerk/nextjs"

import { AuthShell } from "@/components/auth-shell"
import { clerkAppearance } from "@/lib/clerk-appearance"
import { ApiError } from "@/lib/api/client"
import {
  acceptInvite,
  getInvitePreview,
  type InvitePreview,
} from "@/lib/api/endpoints"
import { setActiveWorkspaceId } from "@/lib/api/owner"
import { Button } from "@workspace/ui/components/button"

/**
 * Public invite acceptance — app/invite/[token]. Anyone with the link can
 * land here without an account (the token is the credential), so this route
 * lives outside the dashboard and is public in middleware.ts.
 *
 * Loads the invite preview by token, then branches:
 *  - not signed in → Clerk sign-in embedded here, redirecting back to this
 *    same URL after auth (so the preview is still visible to accept);
 *  - signed in → Accept button → sets the new workspace active and goes to
 *    /dashboard;
 *  - revoked / expired / already-accepted → clear inline messaging, no toast.
 *
 * The preview endpoints don't exist in the backend yet — this is the UI
 * shape to build toward (see lib/api/endpoints.ts).
 */
export default function InvitePage() {
  const params = useParams<{ token: string }>()
  const router = useRouter()
  const { isLoaded, isSignedIn } = useAuth()
  const token = params.token

  const [preview, setPreview] = React.useState<InvitePreview | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [accepting, setAccepting] = React.useState(false)
  const [redirectTo, setRedirectTo] = React.useState("")

  // Clerk's redirect targets must be absolute; compute once on the client.
  React.useEffect(() => {
    setRedirectTo(`${window.location.origin}${window.location.pathname}`)
  }, [])

  React.useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const result = await getInvitePreview(token)
        if (cancelled) return
        setPreview(result)
      } catch (err) {
        if (cancelled) return
        setPreview(null)
        setError(
          err instanceof ApiError
            ? err.message
            : "This invite could not be loaded."
        )
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token])

  async function handleAccept() {
    setAccepting(true)
    setError(null)
    try {
      const result = await acceptInvite(token)
      setActiveWorkspaceId(result.workspace_id)
      router.push("/dashboard")
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not accept this invite."
      )
      setAccepting(false)
    }
  }

  const status = preview?.status ?? null
  const unusable =
    status === "revoked" || status === "expired" || status === "accepted"

  return (
    <AuthShell>
      <div className="mx-auto w-full max-w-md">
        {loading ? (
          <div className="border-border bg-card rounded-xl border p-8 text-center">
            <p className="text-muted-foreground text-sm">Loading invite…</p>
          </div>
        ) : !preview ? (
          <div className="border-border bg-card rounded-xl border p-8">
            <h1 className="text-foreground text-lg font-bold tracking-tight">
              Invite unavailable
            </h1>
            <p className="text-muted-foreground mt-2 text-[13px] leading-relaxed">
              {error ?? "This invite could not be loaded."}
            </p>
            <Link
              href="/"
              className="text-primary mt-4 inline-block text-[13px] font-semibold hover:underline"
            >
              ← Back to Migration Oracle
            </Link>
          </div>
        ) : unusable ? (
          <div className="border-border bg-card rounded-xl border p-8">
            <h1 className="text-foreground text-lg font-bold tracking-tight">
              {status === "revoked"
                ? "This invite was revoked"
                : status === "expired"
                  ? "This invite has expired"
                  : "This invite has already been used"}
            </h1>
            <p className="text-muted-foreground mt-2 text-[13px] leading-relaxed">
              {status === "revoked"
                ? `${preview.inviter_display_name ?? preview.inviter_identity} revoked the invitation to ${preview.workspace_name}.`
                : status === "expired"
                  ? `The invitation to ${preview.workspace_name} from ${
                      preview.inviter_display_name ?? preview.inviter_identity
                    } is no longer valid. Ask them to send a new invite.`
                  : `You have already joined ${preview.workspace_name}.`}
            </p>
            <Link
              href="/"
              className="text-primary mt-4 inline-block text-[13px] font-semibold hover:underline"
            >
              ← Back to Migration Oracle
            </Link>
          </div>
        ) : !isLoaded ? (
          <div className="border-border bg-card rounded-xl border p-8 text-center">
            <p className="text-muted-foreground text-sm">Checking sign-in…</p>
          </div>
        ) : isSignedIn ? (
          <div className="border-border bg-card rounded-xl border p-8">
            <h1 className="text-foreground text-lg font-bold tracking-tight">
              You&apos;ve been invited
            </h1>
            <p className="text-muted-foreground mt-2 text-[13px] leading-relaxed">
              {preview.inviter_display_name ?? preview.inviter_identity} has
              invited you to join{" "}
              <span className="text-foreground font-semibold">
                {preview.workspace_name}
              </span>
              .
            </p>
            {error ? (
              <p className="mt-3 text-[12px] leading-snug text-destructive">
                {error}
              </p>
            ) : null}
            <Button
              variant="default"
              size="sm"
              className="mt-5 w-full"
              disabled={accepting}
              onClick={() => void handleAccept()}
            >
              {accepting ? "Joining…" : "Accept invitation"}
            </Button>
          </div>
        ) : (
          <div className="border-border bg-card rounded-xl border p-6 sm:p-8">
            <h1 className="text-foreground text-lg font-bold tracking-tight">
              You&apos;ve been invited
            </h1>
            <p className="text-muted-foreground mt-2 text-[13px] leading-relaxed">
              {preview.inviter_display_name ?? preview.inviter_identity} has
              invited you to join{" "}
              <span className="text-foreground font-semibold">
                {preview.workspace_name}
              </span>
              . Sign in to accept.
            </p>
            {redirectTo ? (
              <div className="mt-4">
                <SignIn
                  routing="virtual"
                  appearance={clerkAppearance}
                  signUpUrl="/get-started"
                  forceRedirectUrl={redirectTo}
                  fallbackRedirectUrl={redirectTo}
                />
              </div>
            ) : (
              <p className="text-muted-foreground mt-4 text-center text-xs">
                Preparing sign-in…
              </p>
            )}
          </div>
        )}
      </div>
    </AuthShell>
  )
}
