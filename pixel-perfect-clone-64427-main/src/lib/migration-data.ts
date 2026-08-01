export type Risk = "low" | "medium" | "high";

export const queueItems = [
  {
    sql: "ALTER TABLE customers ADD COLUMN demo_flag STRING;",
    risk: "medium" as Risk,
    confidence: "High confidence",
  },
  {
    sql: "CREATE INDEX idx_orders_created_at ON orders (created_at);",
    risk: "low" as Risk,
    confidence: "High confidence",
  },
  {
    sql: "ALTER TABLE sessions DROP COLUMN legacy_token;",
    risk: "high" as Risk,
    confidence: "Medium confidence",
  },
  {
    sql: "CREATE INDEX idx_events_user_id ON events (user_id);",
    risk: "low" as Risk,
    confidence: "High confidence",
  },
];

export const activity = [
  {
    time: "11:24",
    kind: "Completed",
    tone: "emerald",
    text: "Shadow execution finished for idx_users_email — no lock escalation.",
  },
  {
    time: "10:57",
    kind: "Learned",
    tone: "blue",
    text: "Agent Memory added 36 matching verified runs to this prediction.",
  },
  {
    time: "10:41",
    kind: "Predicted",
    tone: "violet",
    text: "Risk model classified the migration as low-impact.",
  },
  {
    time: "09:18",
    kind: "Shadow",
    tone: "blue",
    text: "Shadow run started for idx_orders_created_at on replica-03.",
  },
  {
    time: "08:52",
    kind: "Queued",
    tone: "amber",
    text: "ALTER TABLE customers ADD COLUMN demo_flag queued for review.",
  },
];

export const recentMigrations = [
  { sql: "CREATE INDEX idx_users_email ON users (email);", status: "COMPLETED" },
  {
    sql: "CREATE INDEX idx_orders_created_at ON orders (created_at);",
    status: "AWAITING APPROVAL",
  },
  { sql: "CREATE INDEX idx_sessions_user_id ON sessions (user_id);", status: "PENDING" },
  { sql: "CREATE INDEX idx_audit_log_ts ON audit_log (created_at);", status: "RUNNING SHADOW" },
];

export const shadowChecks = [
  {
    name: "Lock escalation",
    detail: "No lock escalation detected during shadow run.",
    state: "pass" as const,
  },
  {
    name: "Execution time",
    detail: "1m 47s — within acceptable 5m threshold.",
    state: "pass" as const,
  },
  {
    name: "Deadlock detection",
    detail: "0 deadlocks observed across 3 shadow replays.",
    state: "pass" as const,
  },
  {
    name: "Row count delta",
    detail: "Index covers 100% of rows (2,847,391).",
    state: "pass" as const,
  },
  {
    name: "Replica lag",
    detail: "Replica-03 lag spiked to 340ms during execution — within tolerance.",
    state: "warn" as const,
  },
  { name: "Memory usage", detail: "Peak 1.2 GB — below 4 GB limit.", state: "pass" as const },
];

export const timeline = [
  {
    title: "Shadow execution completed",
    by: "by Shadow Engine",
    detail: "Replica-03 — 1m 47s — no lock escalation — 0 deadlocks",
    at: "2026-07-31 11:24",
    tone: "blue",
  },
  {
    title: "Memory lookup completed",
    by: "by Agent Memory",
    detail: "36 verified matching runs found — confidence boosted to 94%",
    at: "2026-07-31 10:57",
    tone: "violet",
  },
  {
    title: "Risk classification: Low",
    by: "by Risk Model",
    detail: "B-Tree index on non-nullable column, table size within trained range",
    at: "2026-07-31 10:41",
    tone: "violet",
  },
  {
    title: "Shadow run started",
    by: "by Shadow Engine",
    detail: "Replica-03 selected — 3 replay passes queued",
    at: "2026-07-31 09:18",
    tone: "blue",
  },
];

export const riskFactors = [
  {
    name: "Table size",
    detail: "2.8M rows — within trained range of similar successful indexes",
  },
  { name: "Column nullability", detail: "email is NOT NULL — no sparse index risk" },
  {
    name: "Concurrent writes",
    detail: "Moderate write rate (180 inserts/sec) — CREATE INDEX CONCURRENTLY mitigates",
  },
  {
    name: "Lock mode",
    detail: "SHARE lock required — may briefly block writes during final index swap",
  },
  { name: "Memory pressure", detail: "work_mem set to 256MB — sufficient for sort-based index build" },
];

export type PastMigration = {
  sql: string;
  table: string;
  date: string;
  time: string;
  duration: string;
  risk: Risk;
  confidence: number;
  shadow: "pass" | "warn" | "fail";
  outcome: "COMPLETED" | "PROCEEDED" | "CANCELLED";
  approver: string;
  graded: "Graded" | "Ungraded";
};

export const pastMigrations: PastMigration[] = [
  {
    sql: "ALTER TABLE demo_items ADD COLUMN notes STRING;",
    table: "demo_items",
    date: "2026-07-31",
    time: "11:24",
    duration: "1m 47s",
    risk: "low",
    confidence: 94,
    shadow: "pass",
    outcome: "COMPLETED",
    approver: "Samved M.",
    graded: "Graded",
  },
  {
    sql: "CREATE INDEX idx_users_email ON users (email);",
    table: "users",
    date: "2026-07-30",
    time: "15:03",
    duration: "3m 22s",
    risk: "low",
    confidence: 91,
    shadow: "pass",
    outcome: "COMPLETED",
    approver: "Priya N.",
    graded: "Graded",
  },
  {
    sql: "ALTER TABLE orders ADD COLUMN fulfillment_eta TIMESTAMP;",
    table: "orders",
    date: "2026-07-30",
    time: "09:41",
    duration: "2m 05s",
    risk: "medium",
    confidence: 78,
    shadow: "warn",
    outcome: "PROCEEDED",
    approver: "Arjun K.",
    graded: "Graded",
  },
  {
    sql: "CREATE INDEX idx_orders_created_at ON orders (created_at);",
    table: "orders",
    date: "2026-07-29",
    time: "17:55",
    duration: "5m 12s",
    risk: "medium",
    confidence: 82,
    shadow: "pass",
    outcome: "COMPLETED",
    approver: "Samved M.",
    graded: "Graded",
  },
  {
    sql: "ALTER TABLE sessions DROP COLUMN legacy_token;",
    table: "sessions",
    date: "2026-07-29",
    time: "11:18",
    duration: "0m 38s",
    risk: "high",
    confidence: 61,
    shadow: "fail",
    outcome: "CANCELLED",
    approver: "Leila H.",
    graded: "Graded",
  },
  {
    sql: "CREATE INDEX idx_events_user_id ON events (user_id);",
    table: "events",
    date: "2026-07-28",
    time: "14:30",
    duration: "8m 44s",
    risk: "low",
    confidence: 88,
    shadow: "pass",
    outcome: "COMPLETED",
    approver: "Priya N.",
    graded: "Graded",
  },
  {
    sql: "ALTER TABLE customers ADD COLUMN tier VARCHAR(20);",
    table: "customers",
    date: "2026-07-28",
    time: "10:05",
    duration: "1m 14s",
    risk: "low",
    confidence: 96,
    shadow: "pass",
    outcome: "COMPLETED",
    approver: "Arjun K.",
    graded: "Ungraded",
  },
  {
    sql: "CREATE INDEX idx_audit_log_ts ON audit_log (created_at);",
    table: "audit_log",
    date: "2026-07-27",
    time: "16:47",
    duration: "12m 03s",
    risk: "medium",
    confidence: 74,
    shadow: "warn",
    outcome: "PROCEEDED",
    approver: "Samved M.",
    graded: "Graded",
  },
  {
    sql: "ALTER TABLE payments ADD COLUMN refund_ref STRING;",
    table: "payments",
    date: "2026-07-26",
    time: "13:12",
    duration: "0m 54s",
    risk: "low",
    confidence: 92,
    shadow: "pass",
    outcome: "COMPLETED",
    approver: "Leila H.",
    graded: "Graded",
  },
  {
    sql: "ALTER TABLE events DROP COLUMN legacy_payload;",
    table: "events",
    date: "2026-07-25",
    time: "08:29",
    duration: "1m 02s",
    risk: "high",
    confidence: 58,
    shadow: "fail",
    outcome: "CANCELLED",
    approver: "Priya N.",
    graded: "Ungraded",
  },
];

export const dailyVolume = [
  { day: "Jul 25", a: 1, b: 2 },
  { day: "Jul 26", a: 1, b: 0 },
  { day: "Jul 27", a: 1, b: 1 },
  { day: "Jul 28", a: 2, b: 3 },
  { day: "Jul 29", a: 2, b: 1 },
  { day: "Jul 30", a: 2, b: 3 },
  { day: "Jul 31", a: 1, b: 2 },
];

export const memoryReasons = [
  {
    title: "Strong historical match",
    detail:
      "36 verified migrations with matching table size (1M–5M rows), B-Tree index type, and non-nullable column — all succeeded.",
    tone: "ok" as const,
  },
  {
    title: "Low lock risk profile",
    detail:
      "SHARE lock mode with CONCURRENTLY flag. Historical runs show no lock escalation events in this configuration.",
    tone: "ok" as const,
  },
  {
    title: "Predictable runtime",
    detail:
      "Average runtime of 1m 58s across 36 similar runs. Shadow execution on replica-03 completed in 1m 47s — within expected range.",
    tone: "ok" as const,
  },
  {
    title: "One historical failure noted",
    detail:
      "A single failure occurred on a table with 180+ inserts/sec during peak traffic. Current write rate is within safe bounds.",
    tone: "warn" as const,
  },
];
