"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"

import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"

import { ApiError } from "@/lib/api/client"
import {
  getAuthStatus,
  loginUser,
  registerUser,
} from "@/lib/api/endpoints"
import { setAccessToken } from "@/lib/api/auth-token"
import { setOwnerIdentity } from "@/lib/api/owner"

export default function LoginPage() {
  const router = useRouter()
  const [authEnabled, setAuthEnabled] = React.useState<boolean | null>(null)
  const [mode, setMode] = React.useState<"login" | "register">("login")
  const [owner, setOwner] = React.useState("")
  const [password, setPassword] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    void getAuthStatus()
      .then((s) => {
        if (!cancelled) setAuthEnabled(Boolean(s.auth_enabled))
      })
      .catch(() => {
        if (!cancelled) setAuthEnabled(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  React.useEffect(() => {
    if (authEnabled === false) {
      router.replace("/dashboard")
    }
  }, [authEnabled, router])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const res =
        mode === "login"
          ? await loginUser({
              owner_identity: owner.trim(),
              password,
            })
          : await registerUser({
              owner_identity: owner.trim(),
              password,
              display_name: owner.trim(),
            })
      setAccessToken(res.access_token)
      setOwnerIdentity(res.owner_identity)
      router.push("/dashboard")
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Authentication failed"
      )
    } finally {
      setBusy(false)
    }
  }

  if (authEnabled === null) {
    return (
      <main className="flex min-h-svh items-center justify-center p-6">
        <p className="text-muted-foreground font-mono text-xs">Checking auth…</p>
      </main>
    )
  }

  if (!authEnabled) {
    return null
  }

  return (
    <main className="bg-background text-foreground flex min-h-svh flex-col items-center justify-center gap-6 p-6">
      <div className="w-full max-w-sm space-y-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-medium tracking-tight">
            Migration Oracle
          </h1>
          <p className="text-muted-foreground text-sm leading-relaxed">
            {mode === "login"
              ? "Sign in with your owner identity."
              : "Create an account to own your migration runs."}
          </p>
        </div>

        <form className="space-y-3" onSubmit={(e) => void handleSubmit(e)}>
          <div className="space-y-1.5">
            <label
              htmlFor="owner"
              className="text-muted-foreground font-mono text-[10px] tracking-[0.12em] uppercase"
            >
              Owner identity
            </label>
            <Input
              id="owner"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              required
              autoComplete="username"
            />
          </div>
          <div className="space-y-1.5">
            <label
              htmlFor="password"
              className="text-muted-foreground font-mono text-[10px] tracking-[0.12em] uppercase"
            >
              Password
            </label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === "register" ? 8 : 1}
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
            />
          </div>
          {error ? (
            <p className="text-sm text-[var(--oracle-risk)]">{error}</p>
          ) : null}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy
              ? "Working…"
              : mode === "login"
                ? "Sign in"
                : "Create account"}
          </Button>
        </form>

        <button
          type="button"
          className="text-muted-foreground hover:text-foreground font-mono text-[11px] tracking-tight"
          onClick={() =>
            setMode((m) => (m === "login" ? "register" : "login"))
          }
        >
          {mode === "login"
            ? "Need an account? Register"
            : "Already registered? Sign in"}
        </button>

        <Link
          href="/"
          className="text-muted-foreground hover:text-foreground block font-mono text-[11px] tracking-tight"
        >
          ← Back to landing
        </Link>
      </div>
    </main>
  )
}
