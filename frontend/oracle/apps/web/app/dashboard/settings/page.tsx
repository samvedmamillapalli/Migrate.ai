"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useAuth, useUser } from "@clerk/nextjs"
import { Moon, Sun } from "lucide-react"

import { apiBaseUrl } from "@/lib/api/client"
import { DashboardSignOutButton } from "@/components/dashboard-sign-out-button"
import {
  getConnectionSecretArn,
  setConnectionSecretArn,
} from "@/lib/api/owner"
import {
  disconnectSlack,
  getHealth,
  getMemoriesHealth,
  getSlackInstallUrl,
  getSlackStatus,
  isSfnReady,
  type CorpusHealth,
  type HealthResponse,
  type SlackStatusResponse,
} from "@/lib/api/endpoints"
import { ApiError } from "@/lib/api/client"
import { OwnerIdentityField } from "@/components/owner-identity-field"
import { useThemePreference } from "@/components/theme-provider"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import {
  EmptyNote,
  Label,
  PageHeader,
  Panel,
  ToneDot,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

/**
 * Settings.
 *
 * The design's settings page has seven controls — workspace name, shadow
 * on/off, auto-approve, a confidence threshold slider, email and Slack
 * alerts, and "clear agent memory". Most still don't exist in this system:
 * there is no workspace entity, no per-user policy override, and no
 * memory-delete endpoint. Auto-approve is deliberately absent rather than
 * merely unimplemented — a mandatory human gate is the point of the
 * product. Slack alerts are the one control that's now real — see the
 * "Slack notifications" panel below, backed by `/api/slack/*`.
 *
 * The rest of the page keeps the design's layout and shows what is actually
 * true: the identity requests are scoped to, the theme, the live execution
 * policy as reported by /health, and the connection secret used to start a
 * shadow.
 */

function Row({
  title,
  detail,
  children,
}: {
  title: string
  detail: string
  children?: React.ReactNode
}) {
  return (
    <div className="border-border flex items-center justify-between gap-6 border-b py-4 last:border-0">
      <div>
        <div className="text-foreground text-[13.5px] font-semibold">
          {title}
        </div>
        <p className="text-muted-foreground mt-0.5 text-[13px]">{detail}</p>
      </div>
      {children}
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
  const [mounted, setMounted] = React.useState(false)
  const [health, setHealth] = React.useState<HealthResponse | null>(null)
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

  const refreshSlackStatus = React.useCallback(async () => {
    try {
      setSlackStatus(await getSlackStatus())
    } catch {
      // Best-effort — the panel below shows "unknown" rather than blocking
      // the rest of the settings page on a Slack lookup failure.
      setSlackStatus(null)
    }
  }, [])

  React.useEffect(() => {
    setSecretArn(getConnectionSecretArn())
    setMounted(true)
    let cancelled = false
    async function load() {
      const [h, c] = await Promise.allSettled([getHealth(), getMemoriesHealth()])
      if (cancelled) return
      if (h.status === "fulfilled") setHealth(h.value)
      if (c.status === "fulfilled") setCorpus(c.value)
    }
    void load()
    void refreshSlackStatus()
    return () => {
      cancelled = true
    }
  }, [refreshSlackStatus])

  // The backend redirects here with ?slack=connected|error after the OAuth
  // callback completes (see SLACK_INSTALL_SUCCESS_REDIRECT /
  // SLACK_INSTALL_ERROR_REDIRECT in backend/app/config.py). Read it once,
  // then strip it from the URL so a page refresh doesn't re-show the banner.
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const slackParam = params.get("slack")
    if (slackParam === "connected" || slackParam === "error") {
      setSlackBanner(slackParam)
      router.replace("/dashboard/settings")
    }
  }, [router])

  async function handleSlackConnect() {
    setSlackBusy(true)
    setSlackActionError(null)
    try {
      const { authorize_url } = await getSlackInstallUrl()
      window.location.href = authorize_url
    } catch (err) {
      setSlackActionError(
        err instanceof ApiError ? err.message : "Could not start Slack install."
      )
      setSlackBusy(false)
    }
  }

  async function handleSlackDisconnect() {
    setSlackBusy(true)
    setSlackActionError(null)
    try {
      await disconnectSlack()
      await refreshSlackStatus()
    } catch (err) {
      setSlackActionError(
        err instanceof ApiError ? err.message : "Could not disconnect Slack."
      )
    } finally {
      setSlackBusy(false)
    }
  }

  const hasSession = isLoaded && isSignedIn
  const integrations = health?.integrations
  const sfnReady = health ? isSfnReady(health) : null
  const bedrockReady =
    typeof integrations?.bedrock_configured === "boolean"
      ? integrations.bedrock_configured
      : null

  return (
    <div className="mx-auto w-full max-w-[1500px] px-6 pb-10 lg:px-10">
      <PageHeader
        title="Settings"
        subtitle="Workspace identity, appearance, and the execution policy this environment is running under."
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <Panel className="px-6 py-5">
            <Label className="mb-4">Workspace</Label>
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
                <p className="text-muted-foreground mt-1.5 text-[12px] leading-snug">
                  Managed by your Clerk account, not editable here.
                </p>
              </div>
              <OwnerIdentityField id="owner-identity-settings" />
            </div>
            {hasSession ? (
              <div className="border-border mt-4 border-t pt-4">
                <DashboardSignOutButton />
              </div>
            ) : null}
          </Panel>

          <Panel className="px-6 py-5" delay={0.05}>
            <Label>Appearance</Label>
            <div className="mt-4">
              <ThemeModeField />
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.1}>
            <Label>Execution policy</Label>
            <p className="text-muted-foreground mt-2 mb-1 text-[13px] leading-relaxed">
              These reflect how this environment is configured on the server.
              They are reported, not set from here.
            </p>
            <div className="mt-2">
              <Row
                title="Shadow execution"
                detail="Every approved migration runs against a disposable shadow cluster before anything real happens."
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
                  integrations?.bedrock_prediction_model_id
                    ? `Model: ${integrations.bedrock_prediction_model_id}`
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
                detail="Always required. A migration cannot reach a shadow cluster without a recorded human decision."
              >
                <StatePill on={true} onLabel="ALWAYS ON" offLabel="" />
              </Row>
              <Row
                title="Shadow provider"
                detail="Where disposable verification clusters are provisioned."
              >
                <span className="text-foreground shrink-0 font-mono text-[13px]">
                  {integrations?.shadow_provider ?? "—"}
                </span>
              </Row>
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.12}>
            <Label className="mb-4">Slack notifications</Label>
            {slackBanner === "connected" ? (
              <div className="mb-4 rounded-lg border border-[var(--tone-pass-border)] bg-[var(--tone-pass-bg)] px-3 py-2 text-[13px] text-[var(--tone-pass-fg)]">
                Slack connected. Lifecycle notifications will be sent to you
                directly in Slack.
              </div>
            ) : null}
            {slackBanner === "error" ? (
              <div className="mb-4 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-[13px] text-destructive">
                Slack connection failed. Please try connecting again.
              </div>
            ) : null}

            <Row
              title={
                slackStatus?.connected
                  ? `Connected — ${slackStatus.team_name ?? slackStatus.team_id ?? "workspace"}`
                  : "Not connected"
              }
              detail={
                slackStatus?.connected
                  ? "Prediction-ready, shadow-started, and shadow-completed/failed events are sent to you as a Slack DM."
                  : slackStatus?.configured === false
                    ? "Slack OAuth is not configured on this server (SLACK_CLIENT_ID / SLACK_CLIENT_SECRET / SLACK_REDIRECT_URI)."
                    : "Connect Slack to receive migration lifecycle notifications as a direct message."
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
                  {slackBusy ? "Redirecting…" : "Connect Slack"}
                </Button>
              )}
            </Row>
            {slackActionError ? (
              <p className="mt-2 text-[12px] leading-snug text-destructive">
                {slackActionError}
              </p>
            ) : null}
          </Panel>

          <Panel className="px-6 py-5" delay={0.14}>
            <Label className="mb-4">Shadow connection secret</Label>
            <div className="max-w-lg space-y-1.5">
              <Input
                id="connection-secret-arn"
                disabled={!mounted}
                value={secretArn}
                onChange={(e) => {
                  setSecretArn(e.target.value)
                  setConnectionSecretArn(e.target.value)
                }}
                placeholder="arn:aws:secretsmanager:…"
                className="h-11 font-mono text-xs"
                autoComplete="off"
              />
              <p className="text-muted-foreground text-[12px] leading-snug">
                Optional override used when starting a shadow test. Normally set
                for you when you connect a database.
              </p>
            </div>
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel className="px-6 py-5" delay={0.08}>
            <Label className="mb-4">Current policy</Label>
            <div className="space-y-3 text-[13.5px]">
              {[
                [
                  "Shadow execution",
                  sfnReady == null
                    ? "unknown"
                    : sfnReady
                      ? "Enabled"
                      : "Not configured",
                ],
                ["Approval", "Manual review, always"],
                [
                  "Predictions",
                  bedrockReady == null
                    ? "unknown"
                    : bedrockReady
                      ? "Enabled"
                      : "Not configured",
                ],
                ["Environment", integrations?.environment ?? "—"],
                ["Database", health?.database ?? "—"],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="text-foreground font-semibold">{v}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.12}>
            <Label className="mb-4">API connection</Label>
            <div className="space-y-1.5">
              <Input readOnly value={apiBaseUrl()} className="h-9 font-mono text-xs" />
              <p className="text-muted-foreground text-[12px] leading-snug">
                Set via NEXT_PUBLIC_API_BASE_URL at build time.
              </p>
            </div>
            <div className="border-border mt-4 border-t pt-4">
              <div className="section-label mb-2">CockroachDB</div>
              <p className="text-muted-foreground font-mono text-[11px] leading-relaxed break-words">
                {health?.cockroachdb_version ?? "—"}
              </p>
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.16}>
            <Label className="mb-3">Agent memory</Label>
            {corpus ? (
              <div className="space-y-2 text-[13px]">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Total memories</span>
                  <span className="text-foreground font-semibold tabular-nums">
                    {corpus.total_memories ?? 0}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Corpus ready</span>
                  <span className="text-foreground font-semibold tabular-nums">
                    {corpus.corpus_ready_count ?? 0}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">
                    Missing embeddings
                  </span>
                  <span className="text-foreground font-semibold tabular-nums">
                    {corpus.missing_embeddings ?? 0}
                  </span>
                </div>
              </div>
            ) : (
              <EmptyNote>Corpus health unavailable.</EmptyNote>
            )}
            <p className="text-muted-foreground mt-4 text-[12px] leading-relaxed">
              Memories are written automatically after a run is graded. There is
              no delete operation — the corpus is an append-only audit record of
              what actually happened.
            </p>
            <Link
              href="/dashboard/memory"
              className="text-primary mt-3 inline-block text-[13px] font-semibold hover:underline"
            >
              Browse the corpus →
            </Link>
          </Panel>
        </div>
      </div>
    </div>
  )
}
