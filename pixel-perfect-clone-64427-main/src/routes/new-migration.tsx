import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Database,
  ShieldCheck,
  Zap,
  UploadCloud,
  Table2,
  Check,
  ArrowLeft,
  ArrowRight,
  Loader2,
  FileCode2,
} from "lucide-react";
import { PageHeader, Panel, Label, SqlBlock } from "@/components/ui-kit";

export const Route = createFileRoute("/new-migration")({
  head: () => ({
    meta: [
      { title: "New Migration — Migration Oracle" },
      {
        name: "description",
        content:
          "Connect your database, explore the schema, and submit a migration for AI risk analysis.",
      },
      { property: "og:title", content: "New Migration — Migration Oracle" },
      {
        property: "og:description",
        content: "Connect a database, browse the schema and submit SQL for AI risk analysis.",
      },
    ],
  }),
  component: NewMigration,
});

const steps = [
  ["Connect", "Database or file"],
  ["Schema", "Browse tables"],
  ["Columns", "Inspect structure"],
  ["Preview", "Validate data"],
  ["SQL", "Submit migration"],
];

const dbs = [
  { name: "PostgreSQL", port: "5432", color: "text-blue-600" },
  { name: "MySQL", port: "3306", color: "text-amber-600" },
  { name: "CockroachDB", port: "26257", color: "text-primary" },
];

const schemaTables = [
  { name: "users", rows: "1.24M", cols: 9 },
  { name: "orders", rows: "4.81M", cols: 12 },
  { name: "sessions", rows: "820K", cols: 6 },
  { name: "payments", rows: "2.05M", cols: 11 },
  { name: "events", rows: "9.62M", cols: 7 },
  { name: "audit_log", rows: "3.11M", cols: 8 },
];

const columnsByTable: Record<string, { name: string; type: string; nullable: boolean; key?: string }[]> = {
  users: [
    { name: "id", type: "uuid", nullable: false, key: "PK" },
    { name: "email", type: "text", nullable: false, key: "UNIQUE" },
    { name: "full_name", type: "text", nullable: true },
    { name: "created_at", type: "timestamptz", nullable: false },
    { name: "last_login_at", type: "timestamptz", nullable: true },
  ],
  orders: [
    { name: "id", type: "uuid", nullable: false, key: "PK" },
    { name: "user_id", type: "uuid", nullable: false, key: "FK" },
    { name: "status", type: "text", nullable: false },
    { name: "total_cents", type: "integer", nullable: false },
    { name: "created_at", type: "timestamptz", nullable: false },
  ],
};

const defaultColumns = [
  { name: "id", type: "uuid", nullable: false, key: "PK" },
  { name: "ref_id", type: "uuid", nullable: false, key: "FK" },
  { name: "payload", type: "jsonb", nullable: true },
  { name: "created_at", type: "timestamptz", nullable: false },
];

const previewRows = [
  ["8f2a…c41", "ada@acme.io", "Ada Lovelace", "2026-02-11 09:14"],
  ["1b7d…9e0", "grace@acme.io", "Grace Hopper", "2026-03-02 16:41"],
  ["c30f…52a", "alan@acme.io", "Alan Turing", "2026-04-19 11:07"],
  ["77e1…ab8", "katherine@acme.io", "Katherine J.", "2026-05-28 08:22"],
  ["4a90…d13", "linus@acme.io", "Linus T.", "2026-06-30 19:55"],
];

const fieldCls =
  "h-11 w-full rounded-lg border border-border bg-card px-3.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary";

function Field({
  label,
  placeholder,
  type,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
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
      />
    </div>
  );
}

function NewMigration() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);

  const [tab, setTab] = useState<"db" | "file">("db");
  const [db, setDb] = useState("PostgreSQL");
  const [step, setStep] = useState(0);
  const [connecting, setConnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [table, setTable] = useState<string | null>(null);
  const [sql, setSql] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [host, setHost] = useState("db.example.com");
  const [port, setPort] = useState("5432");
  const [dbName, setDbName] = useState("production_db");
  const [user, setUser] = useState("postgres");
  const [pass, setPass] = useState("••••••••");

  const canConnect = Boolean(host && port && dbName && user && pass) && !connecting;
  const columns = table ? (columnsByTable[table] ?? defaultColumns) : [];

  function connect() {
    if (!canConnect) return;
    setConnecting(true);
    setTimeout(() => {
      setConnecting(false);
      setConnected(true);
      setStep(1);
    }, 1100);
  }

  function readFile(f: File) {
    setFileName(f.name);
    const reader = new FileReader();
    reader.onload = () => {
      setSql(String(reader.result ?? "").slice(0, 4000));
      setConnected(true);
      setStep(1);
    };
    reader.readAsText(f);
  }

  function submit() {
    setSubmitting(true);
    setTimeout(() => navigate({ to: "/current-migration" }), 1000);
  }

  const nextDisabled =
    (step === 1 && !table) || (step === 4 && (!sql.trim() || submitting));

  return (
    <>
      <PageHeader
        title="New Migration"
        subtitle="Connect your database, explore the schema, and submit a migration for AI analysis."
      />

      <Panel className="mb-5 px-6 py-5">
        <div className="flex flex-wrap items-center gap-y-4">
          {steps.map(([t, s], i) => {
            const done = i < step;
            const active = i === step;
            return (
              <div key={t} className="flex flex-1 items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    if (i <= step) setStep(i);
                  }}
                  disabled={i > step}
                  className="flex items-center gap-3 text-left disabled:cursor-not-allowed"
                >
                  <span
                    className={
                      "grid h-8 w-8 shrink-0 place-items-center rounded-full text-[13px] font-semibold transition-colors " +
                      (active
                        ? "bg-primary text-primary-foreground"
                        : done
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-muted text-muted-foreground")
                    }
                  >
                    {done ? <Check className="h-4 w-4" /> : i + 1}
                  </span>
                  <span>
                    <span className="block text-[13.5px] font-semibold text-foreground">{t}</span>
                    <span className="block text-[12px] text-muted-foreground">{s}</span>
                  </span>
                </button>
                {i < steps.length - 1 ? (
                  <div className={"h-px flex-1 " + (done ? "bg-emerald-300" : "bg-border")} />
                ) : null}
              </div>
            );
          })}
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div>
          {step === 0 ? (
            <div className="mb-4 inline-flex rounded-lg border border-border bg-card p-1">
              {(
                [
                  ["db", "Connect Database"],
                  ["file", "Upload SQL File"],
                ] as const
              ).map(([k, l]) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setTab(k)}
                  className={
                    "rounded-md px-4 py-2 text-sm font-semibold transition-colors " +
                    (tab === k
                      ? "bg-primary text-primary-foreground"
                      : "text-foreground hover:bg-muted")
                  }
                >
                  {l}
                </button>
              ))}
            </div>
          ) : null}

          <input
            ref={fileRef}
            type="file"
            accept=".sql,text/plain"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) readFile(f);
            }}
          />

          <AnimatePresence mode="wait">
            <motion.div
              key={step + tab}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.2 }}
            >
              <Panel className="px-6 py-5">
                {step === 0 && tab === "db" ? (
                  <>
                    <Label className="mb-3">Database Type</Label>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      {dbs.map((d) => (
                        <motion.button
                          key={d.name}
                          type="button"
                          whileTap={{ scale: 0.98 }}
                          onClick={() => {
                            setDb(d.name);
                            setPort(d.port);
                          }}
                          className={
                            "flex flex-col items-center gap-2 rounded-lg border px-4 py-5 transition-colors " +
                            (db === d.name
                              ? "border-primary bg-primary/5"
                              : "border-border bg-card hover:bg-muted/50")
                          }
                        >
                          <Database className={"h-5 w-5 " + d.color} strokeWidth={1.75} />
                          <span className="text-[13.5px] font-medium text-foreground">{d.name}</span>
                        </motion.button>
                      ))}
                    </div>

                    <div className="mt-5 space-y-4">
                      <Field label="Host" placeholder="db.example.com" value={host} onChange={setHost} />
                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <Field label="Port" placeholder="5432" value={port} onChange={setPort} />
                        <Field
                          label="Database"
                          placeholder="production_db"
                          value={dbName}
                          onChange={setDbName}
                        />
                      </div>
                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <Field label="Username" placeholder="postgres" value={user} onChange={setUser} />
                        <Field
                          label="Password"
                          placeholder="••••••••"
                          type="password"
                          value={pass}
                          onChange={setPass}
                        />
                      </div>
                      <button
                        type="button"
                        onClick={connect}
                        disabled={!canConnect}
                        className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 active:scale-[0.99] disabled:bg-muted disabled:text-muted-foreground"
                      >
                        {connecting ? (
                          <>
                            <Loader2 className="h-4 w-4 animate-spin" /> Connecting…
                          </>
                        ) : (
                          <>
                            <Zap className="h-4 w-4" /> Connect &amp; Fetch Schema
                          </>
                        )}
                      </button>
                    </div>
                  </>
                ) : null}

                {step === 0 && tab === "file" ? (
                  <div className="space-y-4">
                    <button
                      type="button"
                      onClick={() => fileRef.current?.click()}
                      className="grid w-full place-items-center gap-3 rounded-lg border border-dashed border-border bg-muted/40 px-6 py-16 text-center transition-colors hover:bg-muted/70"
                    >
                      <UploadCloud className="h-7 w-7 text-muted-foreground" strokeWidth={1.5} />
                      <span className="text-[14px] font-semibold text-foreground">
                        Drop a .sql file here
                      </span>
                      <span className="text-[13px] text-muted-foreground">
                        or click to browse — max 2 MB, single statement per line
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => fileRef.current?.click()}
                      className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 active:scale-[0.99]"
                    >
                      <UploadCloud className="h-4 w-4" /> Upload SQL
                    </button>
                    {fileName ? (
                      <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
                        <FileCode2 className="h-4 w-4" /> {fileName} loaded
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {step === 1 ? (
                  <>
                    <Label className="mb-3">Schema — {schemaTables.length} tables</Label>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      {schemaTables.map((t) => (
                        <button
                          key={t.name}
                          type="button"
                          onClick={() => setTable(t.name)}
                          className={
                            "flex items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left transition-colors " +
                            (table === t.name
                              ? "border-primary bg-primary/5"
                              : "border-border hover:bg-muted/50")
                          }
                        >
                          <span className="flex items-center gap-2.5">
                            <Table2 className="h-4 w-4 text-muted-foreground" strokeWidth={1.75} />
                            <span className="font-mono text-[13px] text-foreground">{t.name}</span>
                          </span>
                          <span className="text-[12px] text-muted-foreground">
                            {t.rows} rows · {t.cols} cols
                          </span>
                        </button>
                      ))}
                    </div>
                  </>
                ) : null}

                {step === 2 ? (
                  <>
                    <Label className="mb-3">Columns — {table}</Label>
                    <div className="overflow-hidden rounded-lg border border-border">
                      <table className="w-full text-left text-[13px]">
                        <thead className="bg-muted/60">
                          <tr className="section-label">
                            <th className="px-4 py-2.5">Column</th>
                            <th className="px-4 py-2.5">Type</th>
                            <th className="px-4 py-2.5">Nullable</th>
                            <th className="px-4 py-2.5">Key</th>
                          </tr>
                        </thead>
                        <tbody>
                          {columns.map((c) => (
                            <tr key={c.name} className="border-t border-border">
                              <td className="px-4 py-2.5 font-mono text-foreground">{c.name}</td>
                              <td className="px-4 py-2.5 font-mono text-muted-foreground">{c.type}</td>
                              <td className="px-4 py-2.5 text-muted-foreground">
                                {c.nullable ? "YES" : "NO"}
                              </td>
                              <td className="px-4 py-2.5 text-muted-foreground">{c.key ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : null}

                {step === 3 ? (
                  <>
                    <Label className="mb-3">Preview — first 5 of 20 rows</Label>
                    <div className="overflow-x-auto rounded-lg border border-border">
                      <table className="w-full text-left text-[13px]">
                        <thead className="bg-muted/60">
                          <tr className="section-label">
                            {["id", "email", "full_name", "created_at"].map((h) => (
                              <th key={h} className="whitespace-nowrap px-4 py-2.5">
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {previewRows.map((r) => (
                            <tr key={r[0]} className="border-t border-border">
                              {r.map((cell) => (
                                <td
                                  key={cell}
                                  className="whitespace-nowrap px-4 py-2.5 font-mono text-muted-foreground"
                                >
                                  {cell}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : null}

                {step === 4 ? (
                  <>
                    <div className="mb-3 flex items-center justify-between">
                      <Label>Migration SQL</Label>
                      <button
                        type="button"
                        onClick={() => fileRef.current?.click()}
                        className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-[12px] font-semibold text-foreground transition-colors hover:bg-muted"
                      >
                        <UploadCloud className="h-3.5 w-3.5" /> Upload SQL
                      </button>
                    </div>
                    <textarea
                      value={sql}
                      onChange={(e) => setSql(e.target.value)}
                      rows={8}
                      spellCheck={false}
                      placeholder={`CREATE INDEX CONCURRENTLY idx_${table ?? "users"}_email ON ${table ?? "users"} (email);`}
                      className="w-full resize-y rounded-lg border border-border bg-card p-3.5 font-mono text-[13px] leading-relaxed text-foreground outline-none focus:border-primary"
                    />
                    {sql.trim() ? (
                      <div className="mt-3 rounded-lg bg-muted/60 px-3 py-2.5">
                        <SqlBlock>{sql.trim()}</SqlBlock>
                      </div>
                    ) : null}
                    <button
                      type="button"
                      onClick={submit}
                      disabled={!sql.trim() || submitting}
                      className="mt-4 inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 active:scale-[0.99] disabled:bg-muted disabled:text-muted-foreground"
                    >
                      {submitting ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" /> Analyzing risk…
                        </>
                      ) : (
                        <>
                          <Zap className="h-4 w-4" /> Submit for AI Analysis
                        </>
                      )}
                    </button>
                  </>
                ) : null}
              </Panel>
            </motion.div>
          </AnimatePresence>

          {step > 0 ? (
            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setStep((s) => Math.max(0, s - 1))}
                className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
              >
                <ArrowLeft className="h-4 w-4" /> Back
              </button>
              {step < 4 ? (
                <button
                  type="button"
                  onClick={() => setStep((s) => Math.min(4, s + 1))}
                  disabled={nextDisabled}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 active:scale-[0.98] disabled:bg-muted disabled:text-muted-foreground"
                >
                  Continue <ArrowRight className="h-4 w-4" />
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="space-y-5">
          <Panel className="px-6 py-5" delay={0.08}>
            <div className="flex items-center gap-2.5">
              <ShieldCheck className="h-5 w-5 text-primary" strokeWidth={1.75} />
              <span className="text-[15px] font-semibold text-foreground">Secure Connection</span>
            </div>
            <p className="mt-3 text-[13.5px] leading-relaxed text-muted-foreground">
              Credentials are used only for schema introspection and are never stored. All
              connections use TLS encryption.
            </p>
            {connected ? (
              <div className="mt-4 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[13px] font-semibold text-emerald-700">
                <Check className="h-4 w-4" />
                {fileName ? `${fileName} loaded` : `Connected to ${dbName}`}
              </div>
            ) : null}
          </Panel>

          <Panel className="px-6 py-5" delay={0.1}>
            <Label className="mb-4">Supported Databases</Label>
            <div className="space-y-3">
              {dbs.map((d) => (
                <div key={d.name} className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-[13.5px] font-semibold text-foreground">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    {d.name}
                  </span>
                  <span className="font-mono text-[12.5px] text-muted-foreground">:{d.port}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="px-6 py-5" delay={0.12}>
            <Label className="mb-4">What happens next</Label>
            <div className="space-y-3">
              {[
                "Schema is fetched and all tables are listed",
                "Select a table to inspect columns and types",
                "Preview the first 20 rows for validation",
                "Paste or upload your migration SQL",
                "AI analyzes risk and generates a recommendation",
              ].map((t, i) => (
                <div key={t} className="flex gap-3 text-[13.5px]">
                  <span
                    className={
                      "font-mono text-[12px] font-bold " +
                      (i < step ? "text-emerald-600" : "text-muted-foreground")
                    }
                  >
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className={i < step ? "text-muted-foreground line-through" : "text-foreground"}>
                    {t}
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
