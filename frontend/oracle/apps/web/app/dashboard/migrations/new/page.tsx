"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { AnimatePresence, motion } from "motion/react"
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Database,
  FileCode2,
  Loader2,
  ShieldCheck,
  Table2,
  UploadCloud,
  Zap,
} from "lucide-react"

import {
  ApiError,
  createDemoWithDb,
  createRun,
  discardRun,
  discoverErrorHint,
  discoverSchema,
  getActiveWorkspaceId,
  getCurrentRunId,
  getPipelineProgress,
  getRun,
  mapSchema,
  notifyWorkspacesChanged,
  predictRun,
  requireOwnerIdentity,
  setConnectionSecretArn,
  setCurrentRunId,
  updateWorkspace,
  type MigrationRun,
  type PipelineProgress,
  type SchemaView,
} from "@/lib/api"
import { Button } from "@workspace/ui/components/button"
import {
  EmptyNote,
  ErrorNote,
  Label,
  PageHeader,
  Panel,
  SqlBlock,
} from "@workspace/ui/components/ui-kit"
import { cn } from "@workspace/ui/lib/utils"

/**
 * New Migration wizard.
 *
 * Step order departs from the design deliberately. The backend cannot
 * discover a schema without a run, and cannot create a run without SQL
 * (POST /runs requires migration_sql), so "write the SQL" has to come before
 * "browse the schema". The design's SQL-last ordering would need a
 * placeholder run — inventing a migration the user never wrote — so the
 * steps are re-ordered instead: SQL → Connect → Schema → Columns → Review.
 *
 * The design's step 4 "Preview — first 5 of 20 rows" is not reproduced.
 * Discovery is metadata-only and read-only by design (the product promise is
 * that customer rows are never read), so there is no honest source for it.
 * That step is replaced by a Review step over what discovery actually returned.
 */

const COLUMNS_PAGE_SIZE = 10

const STEPS = [
  ["SQL", "Write migration"],
  ["Connect", "Database or demo"],
  ["Schema", "Browse tables"],
  ["Structure", "Inspect columns & indexes"],
  ["Analyze", "Review & submit"],
] as const

const GRANT_HELP_SQL = `-- Create a dedicated read-only user
CREATE USER migration_oracle_ro WITH PASSWORD '<password>';

-- Allow access to your schema
GRANT USAGE ON SCHEMA public TO migration_oracle_ro;

-- Allow read-only access to all tables
GRANT SELECT ON ALL TABLES IN SCHEMA public TO migration_oracle_ro;

-- Optional: automatically grant SELECT on future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON TABLES TO migration_oracle_ro;`

const fieldCls =
  "h-11 w-full rounded-lg border border-border bg-card px-3.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"

/**
 * Supported engines. CockroachDB and PostgreSQL share the postgres wire
 * protocol, which is what schema discovery speaks. Engines that aren't
 * supported yet (e.g. MySQL) are left off entirely rather than shown
 * disabled — there's nothing useful for a user to do with that option.
 */
const ENGINES = [
  { name: "CockroachDB", port: "26257", supported: true },
  { name: "PostgreSQL", port: "5432", supported: true },
] as const

function Field({
  label,
  placeholder,
  type,
  value,
  onChange,
}: {
  label: string
  placeholder: string
  type?: string
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div>
      <Label className="mb-2">{label}</Label>
      <input
        className={fieldCls}
        placeholder={placeholder}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        spellCheck={false}
      />
    </div>
  )
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return "Something went wrong."
}

/** Compose the discrete connection fields into the URL the API expects. */
function composeDatabaseUrl(f: {
  host: string
  port: string
  database: string
  username: string
  password: string
  sslMode: string
}): string {
  const auth = f.password
    ? `${encodeURIComponent(f.username)}:${encodeURIComponent(f.password)}`
    : encodeURIComponent(f.username)
  return `postgresql://${auth}@${f.host}:${f.port}/${f.database}?sslmode=${f.sslMode}`
}

export default function NewMigrationPage() {
  const router = useRouter()
  const fileRef = React.useRef<HTMLInputElement>(null)

  const [step, setStep] = React.useState(0)
  const [tab, setTab] = React.useState<"fields" | "url" | "demo">("fields")
  const [engine, setEngine] = React.useState("CockroachDB")

  const [sql, setSql] = React.useState("")
  const [fileName, setFileName] = React.useState<string | null>(null)

  const [host, setHost] = React.useState("")
  const [port, setPort] = React.useState("26257")
  const [dbName, setDbName] = React.useState("")
  const [user, setUser] = React.useState("")
  const [pass, setPass] = React.useState("")
  const [sslMode, setSslMode] = React.useState("verify-full")
  const [rawUrl, setRawUrl] = React.useState("")
  const [secretArn, setSecretArn] = React.useState("")

  const [run, setRun] = React.useState<MigrationRun | null>(null)
  const [schema, setSchema] = React.useState<SchemaView | null>(null)
  const [table, setTable] = React.useState<string | null>(null)

  const [busy, setBusy] = React.useState<
    null | "connect" | "submit" | "discard"
  >(null)
  const [progress, setProgress] = React.useState<PipelineProgress | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [showGrantHelp, setShowGrantHelp] = React.useState(false)
  const [grantCopied, setGrantCopied] = React.useState(false)
  const [demoReplacedSql, setDemoReplacedSql] = React.useState(false)
  const [resumable, setResumable] = React.useState<MigrationRun | null>(null)

  const connected = schema != null && schema.tables.length >= 0 && run != null

  /**
   * Offer to resume. A refresh mid-wizard used to lose everything and leave
   * the half-created run stranded; if the pinned run is still `pending` it can
   * be picked back up exactly where it was.
   */
  React.useEffect(() => {
    let cancelled = false
    async function check() {
      const rid = getCurrentRunId()
      if (!rid) return
      try {
        const existing = await getRun(rid)
        if (cancelled) return
        if (existing.status === "pending") setResumable(existing)
      } catch {
        /* pinned run is gone — nothing to resume */
      }
    }
    void check()
    return () => {
      cancelled = true
    }
  }, [])

  function resume(existing: MigrationRun) {
    setRun(existing)
    setSql(existing.migration_sql)
    setResumable(null)
    if (existing.connection_secret_arn) {
      setSecretArn(existing.connection_secret_arn)
    }
    const mapped = mapSchema(existing)
    if (existing.schema_discovery_status === "succeeded" && mapped) {
      setSchema(mapped)
      setStep(2)
    } else {
      setStep(1)
    }
  }

  /** Remove a run abandoned before discovery ever succeeded. */
  async function discardRunAndReset() {
    if (!run) return
    setError(null)
    try {
      setBusy("discard")
      await discardRun(run.id)
      setRun(null)
      setSchema(null)
      setTable(null)
      setCurrentRunId(null)
      setStep(0)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  function readFile(f: File) {
    setFileName(f.name)
    const reader = new FileReader()
    reader.onload = () => setSql(String(reader.result ?? "").slice(0, 8000))
    reader.readAsText(f)
  }

  async function copyGrant() {
    try {
      await navigator.clipboard.writeText(GRANT_HELP_SQL)
      setGrantCopied(true)
      setTimeout(() => setGrantCopied(false), 2000)
    } catch {
      /* clipboard denied — the block is still selectable by hand */
    }
  }

  /**
   * Step 2 → 3. Creates the run from the SQL written in step 1, then runs
   * read-only schema discovery against the connection. This is the real
   * create → discover chain, with the live pipeline-progress poll attached.
   */
  async function connectAndDiscover() {
    setError(null)
    const trimmedSql = sql.trim()
    if (!trimmedSql) {
      setError("Write your migration SQL in step 1 first.")
      setStep(0)
      return
    }

    let timer: ReturnType<typeof setInterval> | null = null
    try {
      setBusy("connect")
      const owner = requireOwnerIdentity()

      if (tab === "demo") {
        const created = await createDemoWithDb(owner)
        setRun(created)
        setCurrentRunId(created.id)
        if (created.connection_secret_arn) {
          setConnectionSecretArn(created.connection_secret_arn)
          setSecretArn(created.connection_secret_arn)
        }
        // The demo endpoint creates its own run with its own migration SQL.
        // Replace what the user typed with the SQL that actually got recorded,
        // so the Review step and the workspace show the same statement rather
        // than a draft that was silently discarded.
        setSql(created.migration_sql)
        setDemoReplacedSql(true)
        setSchema(mapSchema(created))
        setStep(2)
        return
      }

      const url =
        tab === "url"
          ? rawUrl.trim()
          : host && dbName && user
            ? composeDatabaseUrl({
                host,
                port,
                database: dbName,
                username: user,
                password: pass,
                sslMode,
              })
            : ""
      const arn = secretArn.trim()
      if (!url && !arn) {
        setError(
          "Provide connection details, a read-only database URL, or a stored secret ARN."
        )
        return
      }

      const created = run ?? (await createRun({
        migration_sql: trimmedSql,
        owner_identity: owner,
        workspace_id: getActiveWorkspaceId() || null,
      }))
      setRun(created)
      setCurrentRunId(created.id)

      const tick = async () => {
        try {
          setProgress(await getPipelineProgress(created.id))
        } catch {
          /* transient poll errors while discovering are not interesting */
        }
      }
      await tick()
      timer = setInterval(() => void tick(), 1000)

      const updated = await discoverSchema(created.id, {
        connection_secret_arn: arn || null,
        database_url: url || null,
      })
      await tick()
      setRun(updated)
      if (updated.connection_secret_arn) {
        setConnectionSecretArn(updated.connection_secret_arn)
        setSecretArn(updated.connection_secret_arn)
      }
      setSchema(mapSchema(updated))
      if (updated.schema_discovery_status === "succeeded") {
        setStep(2)
        void syncWorkspaceConnection(updated)
      } else {
        setError(
          `Discovery status: ${updated.schema_discovery_status ?? "unknown"}`
        )
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? discoverErrorHint(err.status, err.message)
          : errorMessage(err)
      )
    } finally {
      if (timer) clearInterval(timer)
      setBusy(null)
      setProgress(null)
    }
  }

  /**
   * Persist a just-verified connection onto the run's workspace so the
   * sidebar's connection state is real backend/workspace state, not
   * something inferred from this wizard's own local state. Reuses the
   * secret ARN the run already stored — no credentials re-enter the
   * request, and the backend re-verifies + relabels (host, engine) from
   * that same pointer. Best-effort: a failure here doesn't affect the run,
   * which already connected successfully.
   */
  async function syncWorkspaceConnection(updatedRun: MigrationRun) {
    const workspaceId = updatedRun.workspace_id ?? getActiveWorkspaceId()
    if (!workspaceId || !updatedRun.connection_secret_arn) return
    try {
      await updateWorkspace(workspaceId, {
        connection_secret_arn: updatedRun.connection_secret_arn,
      })
      notifyWorkspacesChanged()
    } catch {
      /* best-effort — the sidebar just won't reflect this connection yet */
    }
  }

  /** Final step: run the prediction pipeline, then hand off to the workspace. */
  async function submitForAnalysis() {
    if (!run) return
    setError(null)
    let timer: ReturnType<typeof setInterval> | null = null
    try {
      setBusy("submit")
      const tick = async () => {
        try {
          setProgress(await getPipelineProgress(run.id))
        } catch {
          /* transient */
        }
      }
      await tick()
      timer = setInterval(() => void tick(), 1000)
      await predictRun(run.id)
      setCurrentRunId(run.id)
      router.push("/dashboard/migrations/current")
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      if (timer) clearInterval(timer)
      setBusy(null)
      setProgress(null)
    }
  }

  const columns = React.useMemo(
    () => schema?.tables.find((t) => t.name === table)?.columns ?? [],
    [schema, table]
  )
  const selectedTable = schema?.tables.find((t) => t.name === table)

  // Wide tables (real customer schemas can run to hundreds of columns) render
  // 10 at a time instead of one long scroll — resets to page 1 whenever the
  // selected table changes so switching tables never leaves you stranded on
  // a page past the new table's column count.
  const [columnsPage, setColumnsPage] = React.useState(0)
  React.useEffect(() => {
    setColumnsPage(0)
  }, [table])
  const columnsPageCount = Math.max(1, Math.ceil(columns.length / COLUMNS_PAGE_SIZE))
  const clampedColumnsPage = Math.min(columnsPage, columnsPageCount - 1)
  const pagedColumns = columns.slice(
    clampedColumnsPage * COLUMNS_PAGE_SIZE,
    clampedColumnsPage * COLUMNS_PAGE_SIZE + COLUMNS_PAGE_SIZE
  )

  // Whether enough connection info exists to even attempt step 2 — gates the
  // "Connect & discover schema" button itself, not just the ability to move
  // past it once connected. Demo needs nothing; the other two tabs need
  // either full field details or a URL/secret, mirroring the check inside
  // connectAndDiscover so the button's disabled state never lies about
  // whether clicking it can succeed.
  const canConnect =
    tab === "demo" ||
    (tab === "fields" ? Boolean(host.trim() && dbName.trim() && user.trim()) : false) ||
    (tab === "url" ? Boolean(rawUrl.trim() || secretArn.trim()) : false)

  const nextDisabled =
    (step === 0 && !sql.trim()) ||
    (step === 1 && !connected) ||
    (step === 2 && !table)

  return (
    <div className="mx-auto w-full max-w-[1500px] px-6 pb-10 lg:px-10">
      <PageHeader
        title="Analyze Migration"
        subtitle="Predict migration impact before executing against production."
      />

      {resumable && !run ? (
        <Panel className="mb-5 flex flex-wrap items-center justify-between gap-3 border-[var(--tone-warn-border)] bg-[var(--tone-warn-bg)] px-6 py-4">
          <div className="min-w-0">
            <div className="text-foreground text-[13.5px] font-semibold">
              You have an unfinished migration
            </div>
            <p className="text-muted-foreground mt-0.5 truncate font-mono text-[12px]">
              {resumable.migration_sql}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button type="button" size="sm" onClick={() => resume(resumable)}>
              Resume
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setResumable(null)}
            >
              Start fresh
            </Button>
          </div>
        </Panel>
      ) : null}

      <Panel className="mb-5 px-6 py-5">
        <div className="flex flex-wrap items-center gap-y-4">
          {STEPS.map(([t, s], i) => {
            const done = i < step
            const active = i === step
            return (
              <div key={t} className="flex flex-1 items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    if (i <= step) setStep(i)
                  }}
                  disabled={i > step}
                  className="flex items-center gap-3 text-left disabled:cursor-not-allowed"
                >
                  <span
                    className={cn(
                      "grid size-8 shrink-0 place-items-center rounded-full text-[13px] font-semibold transition-colors",
                      active
                        ? "bg-primary text-primary-foreground"
                        : done
                          ? "bg-[var(--tone-pass-bg)] text-[var(--tone-pass-fg)]"
                          : "bg-muted text-muted-foreground"
                    )}
                  >
                    {done ? <Check className="size-4" /> : i + 1}
                  </span>
                  <span className="hidden sm:block">
                    <span className="text-foreground block text-[13.5px] font-semibold">
                      {t}
                    </span>
                    <span className="text-muted-foreground block text-[12px]">
                      {s}
                    </span>
                  </span>
                </button>
                {i < STEPS.length - 1 ? (
                  <div
                    className={cn(
                      "h-px flex-1",
                      done ? "bg-[var(--tone-pass-border)]" : "bg-border"
                    )}
                  />
                ) : null}
              </div>
            )
          })}
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div>
          <input
            ref={fileRef}
            type="file"
            accept=".sql,text/plain"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) readFile(f)
            }}
          />

          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.2 }}
            >
              <Panel className="px-6 py-5">
                {/* ---------- Step 1: SQL ---------- */}
                {step === 0 ? (
                  <>
                    <div className="mb-3 flex items-center justify-between">
                      <Label>Migration SQL</Label>
                      <button
                        type="button"
                        onClick={() => fileRef.current?.click()}
                        className="border-border text-foreground hover:bg-muted inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12px] font-semibold transition-colors"
                      >
                        <UploadCloud className="size-3.5" /> Upload .sql
                      </button>
                    </div>
                    <textarea
                      value={sql}
                      onChange={(e) => setSql(e.target.value)}
                      rows={9}
                      spellCheck={false}
                      placeholder="ALTER TABLE customers ADD COLUMN loyalty_tier STRING NOT NULL DEFAULT 'standard';"
                      className="border-border bg-card text-foreground focus:border-primary w-full resize-y rounded-lg border p-3.5 font-mono text-[13px] leading-relaxed outline-none"
                    />
                    {fileName ? (
                      <div className="text-muted-foreground mt-2 flex items-center gap-2 text-[13px]">
                        <FileCode2 className="size-4" /> {fileName} loaded
                      </div>
                    ) : null}
                    <p className="text-muted-foreground mt-3 text-[12px] leading-relaxed">
                      Analyze one SQL statement at a time for the most accurate predictions.
                    </p>
                  </>
                ) : null}

                {/* ---------- Step 2: Connect ---------- */}
                {step === 1 ? (
                  <>
                    <div className="border-border bg-card mb-4 inline-flex rounded-lg border p-1">
                      {(
                        [
                          ["fields", "Connection details"],
                          ["url", "Paste URL"],
                          ["demo", "Demo database"],
                        ] as const
                      ).map(([k, l]) => (
                        <button
                          key={k}
                          type="button"
                          onClick={() => setTab(k)}
                          className={cn(
                            "rounded-md px-3.5 py-2 text-sm font-semibold transition-colors",
                            tab === k
                              ? "bg-primary text-primary-foreground"
                              : "text-foreground hover:bg-muted"
                          )}
                        >
                          {l}
                        </button>
                      ))}
                    </div>

                    {tab === "fields" ? (
                      <>
                        <Label className="mb-3">Database Type</Label>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                          {ENGINES.map((d) => (
                            <motion.button
                              key={d.name}
                              type="button"
                              whileTap={d.supported ? { scale: 0.98 } : undefined}
                              disabled={!d.supported}
                              onClick={() => {
                                setEngine(d.name)
                                setPort(d.port)
                              }}
                              className={cn(
                                "flex flex-col items-center gap-2 rounded-lg border px-4 py-5 transition-colors",
                                !d.supported
                                  ? "border-border cursor-not-allowed opacity-50"
                                  : engine === d.name
                                    ? "border-primary bg-primary/5"
                                    : "border-border bg-card hover:bg-muted/50"
                              )}
                            >
                              <Database
                                className={cn(
                                  "size-5",
                                  engine === d.name && d.supported
                                    ? "text-primary"
                                    : "text-muted-foreground"
                                )}
                                strokeWidth={1.75}
                              />
                              <span className="text-foreground text-[13.5px] font-medium">
                                {d.name}
                              </span>
                              {!d.supported ? (
                                <span className="text-muted-foreground text-[11px]">
                                  not supported
                                </span>
                              ) : null}
                            </motion.button>
                          ))}
                        </div>

                        <div className="mt-5 space-y-4">
                          <Field
                            label="Host"
                            placeholder="my-cluster.aws-us-east-1.cockroachlabs.cloud"
                            value={host}
                            onChange={setHost}
                          />
                          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                            <Field
                              label="Port"
                              placeholder="26257"
                              value={port}
                              onChange={setPort}
                            />
                            <Field
                              label="Database"
                              placeholder="defaultdb"
                              value={dbName}
                              onChange={setDbName}
                            />
                          </div>
                          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                            <Field
                              label="Read-only username"
                              placeholder="migration_oracle_ro"
                              value={user}
                              onChange={setUser}
                            />
                            <Field
                              label="Password"
                              placeholder="••••••••"
                              type="password"
                              value={pass}
                              onChange={setPass}
                            />
                          </div>
                          <div>
                            <Label className="mb-2">SSL mode</Label>
                            <select
                              value={sslMode}
                              onChange={(e) => setSslMode(e.target.value)}
                              className={fieldCls}
                            >
                              <option value="verify-full">verify-full</option>
                              <option value="require">require</option>
                            </select>
                          </div>
                        </div>
                      </>
                    ) : null}

                    {tab === "url" ? (
                      <div className="space-y-4">
                        <div>
                          <Label className="mb-2">Read-only database URL</Label>
                          <input
                            className={cn(fieldCls, "font-mono text-xs")}
                            placeholder="postgresql://readonly@host:26257/mydb?sslmode=verify-full"
                            value={rawUrl}
                            onChange={(e) => setRawUrl(e.target.value)}
                            autoComplete="off"
                            spellCheck={false}
                          />
                        </div>
                        <div>
                          <Label className="mb-2">
                            …or a Secrets Manager ARN
                          </Label>
                          <input
                            className={cn(fieldCls, "font-mono text-xs")}
                            placeholder="arn:aws:secretsmanager:… (JSON with database_url)"
                            value={secretArn}
                            onChange={(e) => setSecretArn(e.target.value)}
                            autoComplete="off"
                          />
                        </div>
                      </div>
                    ) : null}

                    {tab === "demo" ? (
                      <div className="border-border bg-muted/20 rounded-lg border p-4">
                        <p className="text-foreground text-[14px] font-semibold">
                          Use the prepared demo database
                        </p>
                        <p className="text-muted-foreground mt-2 text-[13px] leading-relaxed">
                          A real, read-only CockroachDB database with a sample
                          schema. Discovery runs for real against it — this is
                          not mocked data. It is{" "}
                          <span className="text-[var(--tone-warn-fg)]">
                            not your data
                          </span>
                          , so the migration SQL you wrote must reference its
                          tables to be meaningful.
                        </p>
                        <p className="text-muted-foreground mt-2 text-[12px]">
                          Note: this replaces your SQL with the demo migration.
                        </p>
                      </div>
                    ) : null}

                    <Button
                      type="button"
                      onClick={() => void connectAndDiscover()}
                      disabled={busy != null || !canConnect}
                      className="mt-5 h-11 w-full"
                    >
                      {busy === "connect" ? (
                        <>
                          <Loader2 className="size-4 animate-spin" /> Connecting…
                        </>
                      ) : (
                        <>
                          <Zap className="size-4" /> Connect &amp; discover schema
                        </>
                      )}
                    </Button>

                    {busy === "connect" ? (
                      <div className="mt-3 space-y-1.5">
                        <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
                          <div
                            className="bg-primary h-full rounded-full transition-all"
                            style={{
                              width: `${Math.max(0, Math.min(100, progress?.percent ?? 5))}%`,
                            }}
                          />
                        </div>
                        <p className="text-muted-foreground font-mono text-[11px]">
                          {progress?.message ?? "Connecting…"}
                        </p>
                      </div>
                    ) : !canConnect ? (
                      <p className="text-muted-foreground mt-2 text-[12px]">
                        {tab === "fields"
                          ? "Fill in host, database, and username to continue."
                          : "Provide a database URL or a Secrets Manager ARN to continue."}
                      </p>
                    ) : null}
                  </>
                ) : null}

                {/* ---------- Step 3: Schema ---------- */}
                {step === 2 ? (
                  <>
                    <Label className="mb-3">
                      Schema — {schema?.tables.length ?? 0} table
                      {schema?.tables.length === 1 ? "" : "s"} discovered
                    </Label>
                    {!schema || schema.tables.length === 0 ? (
                      <EmptyNote>
                        Discovery returned no tables. Check that the read-only
                        user can SELECT from the schema your migration targets.
                      </EmptyNote>
                    ) : (
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                        {schema.tables.map((t) => (
                          <button
                            key={t.name}
                            type="button"
                            onClick={() => setTable(t.name)}
                            className={cn(
                              "flex items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left transition-colors",
                              table === t.name
                                ? "border-primary bg-primary/5"
                                : "border-border hover:bg-muted/50"
                            )}
                          >
                            <span className="flex min-w-0 items-center gap-2.5">
                              <Table2
                                className="text-muted-foreground size-4 shrink-0"
                                strokeWidth={1.75}
                              />
                              <span className="text-foreground truncate font-mono text-[13px]">
                                {t.name}
                              </span>
                            </span>
                            <span className="text-muted-foreground shrink-0 text-[12px]">
                              {t.estimatedRowCount != null
                                ? `${t.estimatedRowCount.toLocaleString()} rows`
                                : "rows unknown"}{" "}
                              · {t.columns.length} cols
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                ) : null}

                {/* ---------- Step 4: Columns ---------- */}
                {step === 3 ? (
                  <>
                    <Label className="mb-3">Columns — {table}</Label>
                    {columns.length === 0 ? (
                      <EmptyNote>
                        No column metadata was returned for this table.
                      </EmptyNote>
                    ) : (
                      <div className="border-border overflow-x-auto rounded-lg border">
                        <table className="w-full min-w-[420px] text-left text-[13px]">
                          <thead className="bg-muted/60">
                            <tr className="section-label">
                              <th className="px-4 py-2.5">Column</th>
                              <th className="px-4 py-2.5">Type</th>
                              <th className="px-4 py-2.5">Nullable</th>
                              <th className="px-4 py-2.5">Key</th>
                            </tr>
                          </thead>
                          <tbody>
                            {pagedColumns.map((c) => (
                              <tr
                                key={c.name}
                                className="border-border border-t"
                              >
                                <td className="text-foreground px-4 py-2.5 font-mono">
                                  {c.name}
                                </td>
                                <td className="text-muted-foreground px-4 py-2.5 font-mono">
                                  {c.type}
                                </td>
                                <td className="text-muted-foreground px-4 py-2.5">
                                  {c.nullable == null
                                    ? "—"
                                    : c.nullable
                                      ? "YES"
                                      : "NO"}
                                </td>
                                <td className="px-4 py-2.5">
                                  {c.keyLabel ? (
                                    <span
                                      className={cn(
                                        "rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold",
                                        c.isPrimaryKey
                                          ? "border-[var(--tone-pass-border)] bg-[var(--tone-pass-bg)] text-[var(--tone-pass-fg)]"
                                          : "border-border bg-muted text-muted-foreground"
                                      )}
                                    >
                                      {c.keyLabel}
                                    </span>
                                  ) : (
                                    <span className="text-muted-foreground/50">
                                      —
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {columns.length > COLUMNS_PAGE_SIZE ? (
                          <div className="border-border bg-muted/60 flex items-center justify-between border-t px-4 py-2">
                            <span className="text-muted-foreground text-[12px]">
                              {clampedColumnsPage * COLUMNS_PAGE_SIZE + 1}–
                              {Math.min(
                                clampedColumnsPage * COLUMNS_PAGE_SIZE + COLUMNS_PAGE_SIZE,
                                columns.length
                              )}{" "}
                              of {columns.length} columns
                            </span>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => setColumnsPage((p) => Math.max(0, p - 1))}
                                disabled={clampedColumnsPage === 0}
                                className="border-border text-foreground grid size-7 place-items-center rounded-md border disabled:cursor-not-allowed disabled:opacity-40"
                                aria-label="Previous columns"
                              >
                                <ChevronLeft className="size-4" />
                              </button>
                              <span className="text-muted-foreground min-w-[64px] text-center text-[12px]">
                                Page {clampedColumnsPage + 1} of {columnsPageCount}
                              </span>
                              <button
                                type="button"
                                onClick={() =>
                                  setColumnsPage((p) => Math.min(columnsPageCount - 1, p + 1))
                                }
                                disabled={clampedColumnsPage >= columnsPageCount - 1}
                                className="border-border text-foreground grid size-7 place-items-center rounded-md border disabled:cursor-not-allowed disabled:opacity-40"
                                aria-label="Next columns"
                              >
                                <ChevronRight className="size-4" />
                              </button>
                            </div>
                          </div>
                        ) : null}
                      </div>
                    )}
                    {selectedTable && selectedTable.indexes.length > 0 ? (
                      <p className="text-muted-foreground mt-3 font-mono text-[11px]">
                        indexes: {selectedTable.indexes.join(", ")}
                      </p>
                    ) : null}
                    <p className="text-muted-foreground mt-4 text-[12px] leading-relaxed">
                    Only your database schema is inspected. Your table data is never read or stored.
                    </p>
                  </>
                ) : null}

                {/* ---------- Step 5: Review ---------- */}
                {step === 4 ? (
                  <>
                    <Label className="mb-3">Review &amp; submit</Label>
                    {demoReplacedSql ? (
                      <p className="mb-2 text-[12px] leading-relaxed text-[var(--tone-warn-fg)]">
                        The demo database supplies its own migration — this is
                        the SQL that was actually recorded, not the draft you
                        typed in step 1.
                      </p>
                    ) : null}
                    <div className="bg-muted/60 rounded-lg px-3 py-2.5">
                      <SqlBlock>{sql.trim()}</SqlBlock>
                    </div>
                    <dl className="mt-4 space-y-2 text-[13px]">
                      {[
                        ["Run", run ? run.id.slice(0, 8) : "—"],
                        [
                          "Schema discovery",
                          run?.schema_discovery_status ?? "—",
                        ],
                        ["Engine", schema?.engine ?? "—"],
                        [
                          "Tables discovered",
                          String(schema?.tables.length ?? 0),
                        ],
                        ["Target table", table ?? "—"],
                      ].map(([k, v]) => (
                        <div
                          key={k}
                          className="border-border flex items-center justify-between border-b pb-2 last:border-0"
                        >
                          <dt className="text-muted-foreground">{k}</dt>
                          <dd className="text-foreground font-mono">{v}</dd>
                        </div>
                      ))}
                    </dl>
                    <Button
                      type="button"
                      onClick={() => void submitForAnalysis()}
                      disabled={busy != null || !run}
                      className="mt-5 h-11 w-full"
                    >
                      {busy === "submit" ? (
                        <>
                          <Loader2 className="size-4 animate-spin" /> Analyzing
                          risk…
                        </>
                      ) : (
                        <>
                          <Zap className="size-4" /> Submit for AI analysis
                        </>
                      )}
                    </Button>
                    {busy === "submit" ? (
                      <div className="mt-3 space-y-1.5">
                        <div className="bg-muted h-1.5 w-full overflow-hidden rounded-full">
                          <div
                            className="bg-primary h-full rounded-full transition-all"
                            style={{
                              width: `${Math.max(0, Math.min(100, progress?.percent ?? 0))}%`,
                            }}
                          />
                        </div>
                        <p className="text-muted-foreground font-mono text-[11px]">
                          {progress?.message ?? "Working…"} ·{" "}
                          {Math.round(progress?.percent ?? 0)}%
                        </p>
                      </div>
                    ) : null}
                  </>
                ) : null}

                {error ? (
                  <div className="mt-4 space-y-2">
                    <ErrorNote>{error}</ErrorNote>
                    <div className="flex flex-wrap gap-2">
                      {step === 1 ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={busy != null}
                          onClick={() => void connectAndDiscover()}
                        >
                          Retry
                        </Button>
                      ) : null}
                      {/* A run created before a failed discovery would
                          otherwise linger in Past Migrations forever — there
                          is no other way for a user to remove it. */}
                      {run && run.status === "pending" ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          disabled={busy != null}
                          onClick={() => void discardRunAndReset()}
                        >
                          {busy === "discard"
                            ? "Discarding…"
                            : "Discard this run"}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </Panel>
            </motion.div>
          </AnimatePresence>

          <div className="mt-4 flex items-center justify-between">
            <button
              type="button"
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0}
              className="border-border text-foreground hover:bg-muted inline-flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm font-semibold transition-colors disabled:opacity-40"
            >
              <ArrowLeft className="size-4" /> Back
            </button>
            {step < 4 ? (
              <button
                type="button"
                onClick={() => {
                  if (step === 0) setStep(1)
                  else setStep((s) => Math.min(4, s + 1))
                }}
                disabled={nextDisabled || busy != null}
                className="bg-primary text-primary-foreground hover:bg-primary/90 disabled:bg-muted disabled:text-muted-foreground inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-all active:scale-[0.98]"
              >
                Continue <ArrowRight className="size-4" />
              </button>
            ) : null}
          </div>
        </div>

        <div className="space-y-5">
          <Panel className="px-6 py-5" delay={0.08}>
            <div className="flex items-center gap-2.5">
              <ShieldCheck className="text-primary size-5" strokeWidth={1.75} />
              <span className="text-foreground text-[15px] font-semibold">
                Secure Connection
              </span>
            </div>
            <p className="text-muted-foreground mt-3 text-[13.5px] leading-relaxed">
            Your credentials are encrypted with AWS Secrets Manager and used only to inspect your database schema. Migration Oracle never reads or stores your table data.
            </p>
            {connected ? (
              <div className="mt-4 flex items-center gap-2 rounded-lg border border-[var(--tone-pass-border)] bg-[var(--tone-pass-bg)] px-3 py-2 text-[13px] font-semibold text-[var(--tone-pass-fg)]">
                <Check className="size-4" />
                Connected — {schema?.tables.length ?? 0} tables discovered
              </div>
            ) : null}

            <div className="border-border/60 mt-4 rounded-md border border-dashed p-3">
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground w-full text-left font-mono text-[10px] tracking-[0.12em] uppercase"
                onClick={() => setShowGrantHelp((v) => !v)}
              >
                {showGrantHelp ? "▾" : "▸"} How do I create a read-only user?
              </button>
              {showGrantHelp ? (
                <div className="mt-2 space-y-2">
                  <pre className="border-border/50 bg-muted/30 max-h-56 overflow-auto rounded-md border p-2.5 font-mono text-[10px] leading-relaxed whitespace-pre-wrap">
                    {GRANT_HELP_SQL}
                  </pre>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void copyGrant()}
                  >
                    {grantCopied ? "Copied" : "Copy GRANT statements"}
                  </Button>
                </div>
              ) : null}
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.12}>
            <Label className="mb-4">What happens next</Label>
            <div className="space-y-3">
              {[
                "Your migration SQL is recorded as a run",
                "Read-only discovery snapshots the schema",
                "You pick the table the migration targets",
                "Columns and indexes are shown for review",
                "AI predicts duration, storage and risk",
              ].map((t, i) => {
                const done = i < step
                const active = i === step
                return (
                  <div key={t} className="flex gap-3 text-[13.5px]">
                    <span
                      className={cn(
                        "flex size-[18px] shrink-0 items-center justify-center font-mono text-[12px] font-bold",
                        done
                          ? "text-[var(--tone-pass-fg)]"
                          : active
                            ? "text-primary"
                            : "text-muted-foreground"
                      )}
                    >
                      {done ? (
                        <Check className="size-3.5" />
                      ) : (
                        String(i + 1).padStart(2, "0")
                      )}
                    </span>
                    <span
                      className={cn(
                        done
                          ? "text-muted-foreground"
                          : active
                            ? "text-foreground font-semibold"
                            : "text-foreground"
                      )}
                    >
                      {t}
                    </span>
                  </div>
                )
              })}
            </div>
            {run ? (
              <Link
                href="/dashboard/migrations/current"
                className="text-primary mt-4 inline-block text-[13px] font-semibold hover:underline"
              >
                Open this run in the workspace →
              </Link>
            ) : null}
          </Panel>
        </div>
      </div>
    </div>
  )
}
