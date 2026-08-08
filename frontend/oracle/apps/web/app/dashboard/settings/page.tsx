"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useAuth, useUser } from "@clerk/nextjs"
import { Moon, Sun } from "lucide-react"

import { DashboardSignOutButton } from "@/components/dashboard-sign-out-button"
import {
  getConnectionSecretArn,
  getOwnerIdentity,
  setConnectionSecretArn,
} from "@/lib/api/owner"
import {
  disconnectGithub,
  disconnectSlack,
  getGithubInstallUrl,
  getGithubStatus,
  getHealth,
  getMemoriesHealth,
  getMemorySharingPreview,
  getMemorySharingStatus,
  getSlackInstallUrl,
  getSlackStatus,
  isSfnReady,
  setMemorySharing,
  type CorpusHealth,
  type GithubStatusResponse,
  type HealthResponse,
  type MemorySharingPreviewResponse,
  type MemorySharingStatusResponse,
  type SlackStatusResponse,
} from "@/lib/api/endpoints"
import { ApiError } from "@/lib/api/client"
import { OwnerIdentityField } from "@/components/owner-identity-field"
import { useThemePreference } from "@/components/theme-provider"
import { WorkspaceSettingsPanel } from "@/components/workspace-settings-panel"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import {
  ErrorNote,
  Label,
  PageHeader,
  Panel,
  ToneDot,
  toneText,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

/**
 * Settings.
 *
 * The design's original mockup had seven controls — workspace name, shadow
 * on/off, auto-approve, a confidence threshold slider, email and Slack
 * alerts, and "clear agent memory". Most still don't exist in this system:
 * there is no per-user policy override and no memory-delete endpoint.
 * Auto-approve is deliberately absent rather than merely unimplemented — a
 * mandatory human gate is the point of the product.
 *
 * Layout is grouped into compact cards (General, Execution, Integrations,
 * Workspaces, Advanced) rather than the mockup's flat list, with System
 * Health pinned full-width at the top so it's visible without scrolling.
 * Everything shown is either live server state (execution policy via
 * /health, integration status, agent memory counts) or a real, working
 * control — including GitHub identity connect (docs/backendfix.md
 * 2026-08-08) and workspace invites/members (2026-08-07e), both real now.
 */

/**
 * One labeled row — title, a one-line detail, a trailing action, and an
 * optional expandable `footer` (e.g. an edit field or a preview panel) that
 * stays inside the row's own border so spacing/dividers stay consistent
 * whether or not a row has extra content underneath.
 */
function Row({
  title,
  detail,
  children,
  footer,
}: {
  title: React.ReactNode
  detail: React.ReactNode
  children?: React.ReactNode
  footer?: React.ReactNode
}) {
  return (
    <div className="border-border border-b py-4 last:border-0">
      <div className="flex items-center justify-between gap-6">
        <div>
          <div className="text-foreground text-[13.5px] font-semibold">
            {title}
          </div>
          <p className="text-muted-foreground mt-0.5 text-[13px]">{detail}</p>
        </div>
        {children}
      </div>
      {footer ? <div className="mt-3">{footer}</div> : null}
    </div>
  )
}

/** One dependency in the System Health strip. `ok === null` means unknown. */
function Health({ name, ok }: { name: string; ok: boolean | null }) {
  return (
    <div className="flex items-center gap-2">
      <ToneDot tone={ok === null ? "neutral" : ok ? "pass" : "fail"} />
      <span className="text-foreground text-sm font-semibold">{name}</span>
      <span
        className={cn(
          "text-sm",
          ok === null
            ? "text-muted-foreground"
            : ok
              ? toneText("pass")
              : toneText("fail")
        )}
      >
        {ok === null ? "Unknown" : ok ? "Ready" : "Needs setup"}
      </span>
    </div>
  )
}

/** Read-only state pill — this reflects server config, it does not set it. */
function StatePill({ on, onLabel, offLabel }: { on: boolean | null; onLabel: string; offLabel: string }) {
  if (on === null) {
    return (
      <span className="text-muted-foreground shrink-0 text-[13px]">unknown</span>
    )
  }
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-bold",
        on
          ? "border-[var(--tone-pass-border)] bg-[var(--tone-pass-bg)] text-[var(--tone-pass-fg)]"
          : "border-border bg-muted text-muted-foreground"
      )}
    >
      <ToneDot tone={on ? "pass" : "neutral"} />
      {on ? onLabel : offLabel}
    </span>
  )
}

/** Known `shadow_provider` config values (see backend/app/config.py) mapped
 * to names a user would recognize, rather than the internal setting name. */
const SHADOW_PROVIDER_LABELS: Record<string, string> = {
  ccloud_api: "CockroachDB Cloud",
  mock: "Local (mock)",
}
function formatShadowProvider(provider: string | null | undefined): string {
  if (!provider) return "—"
  return SHADOW_PROVIDER_LABELS[provider] ?? titleCase(provider)
}

function formatEnvironment(env: string | null | undefined): string {
  if (!env) return "—"
  return titleCase(env)
}

function titleCase(raw: string): string {
  return raw
    .split(/[_-]+/)
    .filter(Boolean)
    .map((w) => w[0]!.toUpperCase() + w.slice(1).toLowerCase())
    .join(" ")
}

/**
 * A Bedrock model id (e.g. "us.anthropic.claude-haiku-4-5-20251001-v1:0" or
 * the older "anthropic.claude-3-5-sonnet-20241022-v2:0") isn't something a
 * user should have to parse. Recognizes both of Anthropic's Bedrock naming
 * conventions — family-first (Claude 4+) and version-first (Claude 3.x) —
 * and falls back to the raw id rather than guessing wrong.
 */
function formatModelId(modelId: string | null | undefined): string | null {
  if (!modelId) return null
  const familyFirst = modelId.match(
    /claude-(haiku|sonnet|opus)-(\d+)(?:-(\d+))?-\d{8}-v\d+/i
  )
  if (familyFirst) {
    const [, family, major, minor] = familyFirst
    const version = minor ? `${major}.${minor}` : major
    return `Claude ${titleCase(family!)} ${version}`
  }
  const versionFirst = modelId.match(
    /claude-(\d+)(?:-(\d+))?-(haiku|sonnet|opus)-\d{8}-v\d+/i
  )
  if (versionFirst) {
    const [, major, minor, family] = versionFirst
    const version = minor ? `${major}.${minor}` : major
    return `Claude ${version} ${titleCase(family!)}`
  }
  if (/^amazon\.titan-embed/i.test(modelId)) return "Amazon Titan Embeddings"
  return modelId
}

function ThemeModeField() {
  const { theme, setTheme } = useThemePreference()

  return (
    <div className="space-y-1.5">
      <Label className="mb-2">Theme</Label>
      <div className="border-border bg-muted/30 inline-flex w-fit gap-0.5 rounded-lg border p-0.5">
        {[
          { value: "light" as const, label: "Light", icon: Sun },
          { value: "dark" as const, label: "Dark", icon: Moon },
        ].map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            type="button"
            onClick={() => setTheme(value)}
            aria-pressed={theme === value}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              theme === value
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="size-3.5" />
            {label}
          </button>
        ))}
      </div>
      <p className="text-muted-foreground mt-2 text-[12px] leading-snug">
        Tied to your account — applies everywhere, and doesn&apos;t affect other
        users on this browser.
      </p>
    </div>
  )
}

export default function SettingsPage() {
  const router = useRouter()
  const { isLoaded, isSignedIn } = useAuth()
  const { user } = useUser()
  const [secretArn, setSecretArn] = React.useState("")
  const [editingSecret, setEditingSecret] = React.useState(false)
  const [mounted, setMounted] = React.useState(false)
  const [health, setHealth] = React.useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = React.useState<string | null>(null)
  const [corpus, setCorpus] = React.useState<CorpusHealth | null>(null)
  const [slackStatus, setSlackStatus] =
    React.useState<SlackStatusResponse | null>(null)
  const [slackBanner, setSlackBanner] = React.useState<
    "connected" | "error" | null
  >(null)
  const [slackBusy, setSlackBusy] = React.useState(false)
  const [slackActionError, setSlackActionError] = React.useState<
    string | null
  >(null)
  const [githubStatus, setGithubStatus] =
    React.useState<GithubStatusResponse | null>(null)
  const [githubBanner, setGithubBanner] = React.useState<
    "connected" | "error" | null
  >(null)
  const [githubBusy, setGithubBusy] = React.useState(false)
  const [githubActionError, setGithubActionError] = React.useState<
    string | null
  >(null)
  const [sharingStatus, setSharingStatus] =
    React.useState<MemorySharingStatusResponse | null>(null)
  const [sharingPreview, setSharingPreview] =
    React.useState<MemorySharingPreviewResponse | null>(null)
  const [sharingBusy, setSharingBusy] = React.useState(false)
  const [sharingPreviewLoading, setSharingPreviewLoading] =
    React.useState(false)
  const [sharingActionError, setSharingActionError] = React.useState<
    string | null
  >(null)
  const [sharingConfirming, setSharingConfirming] = React.useState(false)

  const refreshSlackStatus = React.useCallback(async () => {
    try {
      setSlackStatus(await getSlackStatus())
    } catch {
      // Best-effort — the panel below shows "unknown" rather than blocking
      // the rest of the settings page on a Slack lookup failure.
      setSlackStatus(null)
    }
  }, [])

  const refreshGithubStatus = React.useCallback(async () => {
    try {
      setGithubStatus(await getGithubStatus())
    } catch {
      setGithubStatus(null)
    }
  }, [])

  const refreshSharingStatus = React.useCallback(async () => {
    try {
      setSharingStatus(await getMemorySharingStatus(getOwnerIdentity()))
    } catch {
      setSharingStatus(null)
    }
  }, [])

  React.useEffect(() => {
    setSecretArn(getConnectionSecretArn())
    setMounted(true)
    let cancelled = false
    async function load() {
      const [h, c] = await Promise.allSettled([getHealth(), getMemoriesHealth()])
      if (cancelled) return
      if (h.status === "fulfilled") {
        setHealth(h.value)
        setHealthError(null)
      } else {
        // Never the raw fetch/network error text — that's implementation
        // detail, not something a user can act on.
        setHealthError("Couldn't check system health. Try refreshing.")
      }
      if (c.status === "fulfilled") setCorpus(c.value)
    }
    void load()
    void refreshSlackStatus()
    void refreshGithubStatus()
    void refreshSharingStatus()
    return () => {
      cancelled = true
    }
  }, [refreshSlackStatus, refreshGithubStatus, refreshSharingStatus])

  // The backend redirects here with ?slack=connected|error (or
  // ?github=connected|error) after the OAuth callback completes (see
  // SLACK_INSTALL_SUCCESS_REDIRECT / GITHUB_OAUTH_INSTALL_SUCCESS_REDIRECT
  // in backend/app/config.py). Read it once, then strip it from the URL so
  // a page refresh doesn't re-show the banner.
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const slackParam = params.get("slack")
    const githubParam = params.get("github")
    if (slackParam === "connected" || slackParam === "error") {
      setSlackBanner(slackParam)
      router.replace("/dashboard/settings")
    }
    if (githubParam === "connected" || githubParam === "error") {
      setGithubBanner(githubParam)
      router.replace("/dashboard/settings")
    }
  }, [router])

  // Connect/disconnect failures never surface the raw backend message here —
  // it can be server config detail (missing env vars) or a plain "Not Found"
  // for a route that isn't built yet, neither of which means anything to an
  // end user. A fixed, friendly message covers every failure mode.
  async function handleSlackConnect() {
    setSlackBusy(true)
    setSlackActionError(null)
    try {
      const { authorize_url } = await getSlackInstallUrl()
      window.location.href = authorize_url
    } catch {
      setSlackActionError("Couldn't connect to Slack. Try again in a moment.")
      setSlackBusy(false)
    }
  }

  async function handleSlackDisconnect() {
    setSlackBusy(true)
    setSlackActionError(null)
    try {
      await disconnectSlack()
      await refreshSlackStatus()
    } catch {
      setSlackActionError("Couldn't disconnect Slack. Try again in a moment.")
    } finally {
      setSlackBusy(false)
    }
  }

  async function handleGithubConnect() {
    setGithubBusy(true)
    setGithubActionError(null)
    try {
      const { authorize_url } = await getGithubInstallUrl()
      window.location.href = authorize_url
    } catch {
      setGithubActionError("Couldn't connect to GitHub. Try again in a moment.")
      setGithubBusy(false)
    }
  }

  async function handleGithubDisconnect() {
    setGithubBusy(true)
    setGithubActionError(null)
    try {
      await disconnectGithub()
      await refreshGithubStatus()
    } catch {
      setGithubActionError("Couldn't disconnect GitHub. Try again in a moment.")
    } finally {
      setGithubBusy(false)
    }
  }

  /**
   * docs/cross_customer.md §6 — enabling requires seeing a real example
   * first, not just a checkbox. This fetches that example (built live from
   * the account's own most recent graded run, never written anywhere) and
   * opens the confirm step; the actual opt-in only happens in
   * handleSharingConfirm below.
   */
  async function handleSharingEnableClick() {
    setSharingActionError(null)
    setSharingPreviewLoading(true)
    setSharingConfirming(true)
    try {
      setSharingPreview(await getMemorySharingPreview(getOwnerIdentity()))
    } catch (err) {
      setSharingActionError(
        err instanceof ApiError
          ? err.message
          : "Could not build a preview of what would be shared."
      )
      setSharingConfirming(false)
    } finally {
      setSharingPreviewLoading(false)
    }
  }

  async function handleSharingConfirm() {
    setSharingBusy(true)
    setSharingActionError(null)
    try {
      setSharingStatus(await setMemorySharing(true, getOwnerIdentity()))
      setSharingConfirming(false)
      setSharingPreview(null)
    } catch (err) {
      setSharingActionError(
        err instanceof ApiError
          ? err.message
          : "Could not enable cross-customer sharing."
      )
    } finally {
      setSharingBusy(false)
    }
  }

  function handleSharingCancel() {
    setSharingConfirming(false)
    setSharingPreview(null)
    setSharingActionError(null)
  }

  async function handleSharingDisable() {
    setSharingBusy(true)
    setSharingActionError(null)
    try {
      setSharingStatus(await setMemorySharing(false, getOwnerIdentity()))
    } catch (err) {
      setSharingActionError(
        err instanceof ApiError
          ? err.message
          : "Could not disable cross-customer sharing."
      )
    } finally {
      setSharingBusy(false)
    }
  }

  const hasSession = isLoaded && isSignedIn
  const integrations = health?.integrations
  const sfnReady = health ? isSfnReady(health) : null
  const bedrockReady =
    typeof integrations?.bedrock_configured === "boolean"
      ? integrations.bedrock_configured
      : null
  const apiOk = health ? health.status === "healthy" : null
  const memoryOk = corpus ? corpus.healthy !== false : null
  const predictionModelLabel = formatModelId(
    integrations?.bedrock_prediction_model_id
  )

  return (
    <div className="mx-auto w-full max-w-[1500px] px-6 pb-10 lg:px-10">
      <PageHeader
        title="Settings"
        subtitle="Account, execution policy, integrations, and workspaces."
      />

      {/* System Health — kept full-width and first so it's visible without
          scrolling, regardless of column. */}
      <Panel className="mb-5 px-6 py-5">
        <Label className="mb-3">System Health</Label>
        {healthError ? (
          <ErrorNote>{healthError}</ErrorNote>
        ) : (
          <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
            <Health name="API" ok={apiOk} />
            <Health name="Shadow" ok={sfnReady} />
            <Health name="Predictions" ok={bedrockReady} />
            <Health name="Memory" ok={memoryOk} />
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          {/* General — identity + appearance */}
          <Panel className="px-6 py-5" delay={0.02}>
            <Label className="mb-4">General</Label>
            <div className="space-y-4">
              <div>
                <Label className="mb-2">Signed in as</Label>
                <Input
                  readOnly
                  value={
                    mounted && isLoaded
                      ? (user?.fullName ??
                        user?.primaryEmailAddress?.emailAddress ??
                        "")
                      : ""
                  }
                  className="h-11"
                />
              </div>
              <OwnerIdentityField id="owner-identity-settings" />
            </div>
            <div className="border-border mt-4 border-t pt-4">
              <ThemeModeField />
            </div>
            {hasSession ? (
              <div className="border-border mt-4 border-t pt-4">
                <DashboardSignOutButton />
              </div>
            ) : null}
          </Panel>

          {/* Execution — the live policy this environment runs under.
              Merges the old "Execution policy" + "Current policy" panels,
              which duplicated the same three facts in two formats. */}
          <Panel className="px-6 py-5" delay={0.06}>
            <Label>Execution</Label>
            <p className="text-muted-foreground mt-1 mb-2 text-[12px] leading-snug">
              Reported by the server — not editable here.
            </p>
            <div className="mt-2">
              <Row
                title="Shadow execution"
                detail="Approved migrations run against a disposable shadow cluster first."
              >
                <StatePill
                  on={sfnReady}
                  onLabel="ENABLED"
                  offLabel="NOT CONFIGURED"
                />
              </Row>
              <Row
                title="AI prediction"
                detail={
                  predictionModelLabel
                    ? `Model: ${predictionModelLabel}`
                    : "No prediction model configured."
                }
              >
                <StatePill
                  on={bedrockReady}
                  onLabel="ENABLED"
                  offLabel="NOT CONFIGURED"
                />
              </Row>
              <Row
                title="Manual approval"
                detail="Always required before a shadow run starts."
              >
                <StatePill on={true} onLabel="ALWAYS ON" offLabel="" />
              </Row>
              <Row title="Shadow provider" detail="Verification cluster provisioner.">
                <span className="text-foreground shrink-0 text-[13px] font-semibold">
                  {formatShadowProvider(integrations?.shadow_provider)}
                </span>
              </Row>
              <Row title="Environment" detail="Server deployment environment.">
                <span className="text-foreground shrink-0 text-[13px] font-semibold">
                  {formatEnvironment(integrations?.environment)}
                </span>
              </Row>
            </div>
          </Panel>

          {/* Integrations — Slack (real) + GitHub (not built yet, marked
              rather than offered as a dead Connect button). */}
          <Panel className="px-6 py-5" delay={0.1}>
            <Label className="mb-2">Integrations</Label>
            {slackBanner === "connected" ? (
              <div className="mb-3 rounded-lg border border-[var(--tone-pass-border)] bg-[var(--tone-pass-bg)] px-3 py-2 text-[13px] text-[var(--tone-pass-fg)]">
                Slack connected.
              </div>
            ) : null}
            {slackBanner === "error" ? (
              <div className="mb-3 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-[13px] text-destructive">
                Slack connection failed. Try again.
              </div>
            ) : null}

            <Row
              title={
                slackStatus?.connected
                  ? `Slack — ${slackStatus.team_name ?? slackStatus.team_id ?? "connected"}`
                  : "Slack"
              }
              detail={
                slackStatus?.connected
                  ? "Lifecycle events sent to you as a DM."
                  : slackStatus?.configured === false
                    ? "Not configured on this server."
                    : "Get migration lifecycle notifications."
              }
            >
              {slackStatus?.connected ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={slackBusy}
                  onClick={() => void handleSlackDisconnect()}
                >
                  {slackBusy ? "Disconnecting…" : "Disconnect"}
                </Button>
              ) : (
                <Button
                  variant="default"
                  size="sm"
                  disabled={slackBusy || slackStatus?.configured === false}
                  onClick={() => void handleSlackConnect()}
                >
                  {slackBusy ? "Redirecting…" : "Connect"}
                </Button>
              )}
            </Row>
            {slackActionError ? (
              <p className="mt-1 mb-2 text-[12px] leading-snug text-destructive">
                {slackActionError}
              </p>
            ) : null}

            {githubBanner === "connected" ? (
              <div className="mb-3 rounded-lg border border-[var(--tone-pass-border)] bg-[var(--tone-pass-bg)] px-3 py-2 text-[13px] text-[var(--tone-pass-fg)]">
                GitHub connected.
              </div>
            ) : null}
            {githubBanner === "error" ? (
              <div className="mb-3 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-[13px] text-destructive">
                GitHub connection failed. Try again.
              </div>
            ) : null}

            <Row
              title={
                githubStatus?.connected
                  ? `GitHub — @${githubStatus.username ?? "connected"}`
                  : "GitHub"
              }
              detail={
                githubStatus?.connected
                  ? "Your identity is verified for workspace invites."
                  : githubStatus?.configured === false
                    ? "Not configured on this server."
                    : "Verify your identity for workspace invites."
              }
            >
              {githubStatus?.connected ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={githubBusy}
                  onClick={() => void handleGithubDisconnect()}
                >
                  {githubBusy ? "Disconnecting…" : "Disconnect"}
                </Button>
              ) : (
                <Button
                  variant="default"
                  size="sm"
                  disabled={githubBusy || githubStatus?.configured === false}
                  onClick={() => void handleGithubConnect()}
                >
                  {githubBusy ? "Redirecting…" : "Connect"}
                </Button>
              )}
            </Row>
            {githubActionError ? (
              <p className="mt-1 mb-2 text-[12px] leading-snug text-destructive">
                {githubActionError}
              </p>
            ) : null}
          </Panel>
        </div>

        <div className="space-y-5">
          {/* Workspaces */}
          <Panel className="px-6 py-5" delay={0.08}>
            <WorkspaceSettingsPanel />
          </Panel>

          {/* Advanced — connection status, connection secret, memory
              sharing, agent memory. Raw technical detail (URLs, version
              strings, secret values) stays out of the UI — status pills and
              "managed automatically" cover what a user actually needs. */}
          <Panel className="px-6 py-5" delay={0.12}>
            <Label className="mb-4">Advanced</Label>

            <div>
              <Row title="API connection" detail="Reachability of the backend API.">
                <StatePill on={apiOk} onLabel="CONNECTED" offLabel="UNAVAILABLE" />
              </Row>
              <Row title="Database" detail="Primary data store.">
                <StatePill
                  on={health ? health.database === "healthy" : null}
                  onLabel="CONNECTED"
                  offLabel="UNAVAILABLE"
                />
              </Row>

              <Row
                title="Shadow connection secret"
                detail={
                  secretArn.trim()
                    ? "Custom override configured."
                    : "Managed automatically."
                }
                footer={
                  editingSecret ? (
                    <>
                      <Input
                        id="connection-secret-arn"
                        disabled={!mounted}
                        value={secretArn}
                        onChange={(e) => {
                          setSecretArn(e.target.value)
                          setConnectionSecretArn(e.target.value)
                        }}
                        placeholder="arn:aws:secretsmanager:…"
                        className="h-9 font-mono text-xs"
                        autoComplete="off"
                      />
                      <p className="text-muted-foreground mt-1.5 text-[11.5px] leading-snug">
                        Optional override for starting a shadow test — usually
                        set automatically.
                      </p>
                    </>
                  ) : null
                }
              >
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setEditingSecret((v) => !v)}
                >
                  {editingSecret ? "Done" : "Edit"}
                </Button>
              </Row>

              <Row
                title="Cross-customer memory sharing"
                detail={
                  sharingStatus?.enabled
                    ? "Your graded runs are anonymized and contributed automatically."
                    : "Shares anonymized migration patterns with other accounts. No identifiers leave yours."
                }
                footer={
                  <>
                    {sharingConfirming ? (
                      <div className="border-border bg-muted/30 space-y-3 rounded-lg border p-4">
                        <div className="text-foreground text-[13px] font-semibold">
                          Example of what would be shared
                        </div>
                        {sharingPreviewLoading ? (
                          <p className="text-muted-foreground text-[13px]">
                            Building a live example from your most recent
                            graded run…
                          </p>
                        ) : sharingPreview?.available ? (
                          <div className="space-y-2">
                            <div className="rounded-md border border-border bg-background p-3 font-mono text-[12px] leading-relaxed break-words">
                              {sharingPreview.sql_shape_template}
                            </div>
                            {sharingPreview.generalized_summary ? (
                              <p className="text-[12.5px] text-foreground leading-relaxed">
                                {sharingPreview.generalized_summary}
                              </p>
                            ) : null}
                            {sharingPreview.generalized_risk_narrative ? (
                              <p className="text-muted-foreground text-[12.5px] leading-relaxed">
                                {sharingPreview.generalized_risk_narrative}
                              </p>
                            ) : null}
                          </div>
                        ) : (
                          <p className="text-muted-foreground text-[13px] leading-relaxed">
                            {sharingPreview?.reason ??
                              "No preview yet — you can still enable sharing."}
                          </p>
                        )}
                        <p className="text-muted-foreground text-[12px] leading-relaxed">
                          Shared patterns stay shared even after you disable
                          this.
                        </p>
                        <div className="flex items-center gap-2 pt-1">
                          <Button
                            variant="default"
                            size="sm"
                            disabled={sharingBusy || sharingPreviewLoading}
                            onClick={() => void handleSharingConfirm()}
                          >
                            {sharingBusy ? "Enabling…" : "Confirm & enable"}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={sharingBusy}
                            onClick={handleSharingCancel}
                          >
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : null}
                    {sharingActionError ? (
                      <p className="mt-2 text-[12px] leading-snug text-destructive">
                        {sharingActionError}
                      </p>
                    ) : null}
                  </>
                }
              >
                {sharingStatus?.enabled ? (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={sharingBusy}
                    onClick={() => void handleSharingDisable()}
                  >
                    {sharingBusy ? "Disabling…" : "Disable"}
                  </Button>
                ) : (
                  <Button
                    variant="default"
                    size="sm"
                    disabled={sharingBusy || sharingConfirming}
                    onClick={() => void handleSharingEnableClick()}
                  >
                    Enable…
                  </Button>
                )}
              </Row>

              <Row
                title="Agent memory"
                detail={
                  corpus
                    ? `${corpus.corpus_ready_count ?? 0} memories indexed`
                    : "Not available"
                }
              >
                <Link
                  href="/dashboard/memory"
                  className="text-primary shrink-0 text-[13px] font-semibold hover:underline"
                >
                  Browse corpus →
                </Link>
              </Row>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
