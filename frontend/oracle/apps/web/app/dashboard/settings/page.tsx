"use client"

import * as React from "react"
import { useAuth } from "@clerk/nextjs"

import { apiBaseUrl } from "@/lib/api/client"
import { DashboardSignOutButton } from "@/components/dashboard-sign-out-button"
import {
  getConnectionSecretArn,
  setConnectionSecretArn,
} from "@/lib/api/owner"
import { OwnerIdentityField } from "@/components/owner-identity-field"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"

function Section({
  title,
  children,
  className,
}: {
  title: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      aria-label={title}
      className={
        "border-border flex w-full flex-col gap-3 rounded-lg border p-4" +
        (className ? ` ${className}` : "")
      }
    >
      <p className="text-muted-foreground text-[11px] font-medium tracking-[0.16em] uppercase">
        {title}
      </p>
      {children}
    </section>
  )
}

export default function SettingsPage() {
  const { isLoaded, isSignedIn } = useAuth()
  const [secretArn, setSecretArn] = React.useState("")
  const [mounted, setMounted] = React.useState(false)

  React.useEffect(() => {
    setSecretArn(getConnectionSecretArn())
    setMounted(true)
  }, [])

  const hasSession = isLoaded && isSignedIn

  return (
    <div className="flex flex-1 flex-col gap-5 px-4 pb-6 md:px-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-foreground text-2xl font-medium tracking-tight">
          Settings
        </h1>
        <p className="text-muted-foreground text-sm">
          Workspace preferences and account configuration.
        </p>
      </div>

      <Section title="Identity">
        <OwnerIdentityField id="owner-identity-settings" className="max-w-sm" />
        {hasSession ? (
          <DashboardSignOutButton />
        ) : null}
      </Section>

      <Section title="API Connection">
        <div className="max-w-sm space-y-1.5">
          <Label className="text-muted-foreground text-[11px]">
            API base URL
          </Label>
          <Input
            readOnly
            value={apiBaseUrl()}
            className="h-8 font-mono text-xs"
          />
          <p className="text-muted-foreground/70 text-[10px] leading-snug">
            Set via NEXT_PUBLIC_API_BASE_URL at build time. Not editable here.
          </p>
        </div>

        <div className="border-border/60 max-w-sm space-y-1.5 border-t pt-3">
          <Label className="text-muted-foreground text-[11px]">
            Demo API key
          </Label>
          <p className="text-muted-foreground/70 text-[10px] leading-snug">
            Set NEXT_PUBLIC_DEMO_API_KEY in the environment to send an
            X-API-Key header with every request. There is no in-app editor
            for this value — it is read from the build environment only.
          </p>
        </div>
      </Section>

      <Section title="Shadow secret">
        <div className="max-w-sm space-y-1.5">
          <Label
            htmlFor="connection-secret-arn"
            className="text-muted-foreground text-[11px]"
          >
            Database secret
          </Label>
          <Input
            id="connection-secret-arn"
            disabled={!mounted}
            value={secretArn}
            onChange={(e) => {
              setSecretArn(e.target.value)
              setConnectionSecretArn(e.target.value)
            }}
            placeholder="arn:aws:secretsmanager:…"
            className="h-8 font-mono text-xs"
            autoComplete="off"
          />
          <p className="text-muted-foreground/70 text-[10px] leading-snug">
            Optional override when starting a shadow test.
          </p>
        </div>
      </Section>
    </div>
  )
}
