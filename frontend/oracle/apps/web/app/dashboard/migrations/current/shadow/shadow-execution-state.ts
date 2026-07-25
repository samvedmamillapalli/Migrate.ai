export type ShadowExecutionPhase =
  | "provisioning"
  | "cloning"
  | "executing"
  | "measuring"
  | "rollback_test"
  | "verifying"
  | "completed"

export function isLiveShadowPhase(
  phase: ShadowExecutionPhase
): phase is Exclude<ShadowExecutionPhase, "completed"> {
  return phase !== "completed"
}

export type LifecycleStageState = "complete" | "current" | "pending"

export type SchemaMutation = {
  name: string
  detail: string
}

export type ExecutionEvent = {
  time: string
  message: string
}

export type LiveShadowExecutionData = {
  clusterId: string
  engine: string
  lifecycle: string
  phase: Exclude<ShadowExecutionPhase, "completed">
  statusLabel: string
  nodes: { id: string; label: string }[]
  lifecycleStages: {
    id: string
    label: string
    state: LifecycleStageState
  }[]
  schemaChanges: {
    table: string
    mutations: SchemaMutation[]
  }
  currentOperation: {
    sql: string
    statementsCompleted: number
    statementsTotal: number
  }
  events: ExecutionEvent[]
  telemetry: {
    runtime: string
    storage: string
    locks: number
    failures: number
  }
}

/**
 * Temporary local phase for live execution window state.
 * Later: FastAPI shadow run status opens/updates ShadowExecutionWindow.
 * Completed results stay on the underlying Shadow Execution page.
 */
export const SHADOW_EXECUTION_PHASE: ShadowExecutionPhase = "executing"

export const LIVE_SHADOW_EXECUTION: LiveShadowExecutionData = {
  clusterId: "SHADOW-7F2A",
  engine: "CockroachDB",
  lifecycle: "ephemeral",
  phase: "executing",
  statusLabel: "EXECUTING",
  nodes: [
    { id: "n1", label: "node-1" },
    { id: "n2", label: "node-2" },
    { id: "n3", label: "node-3" },
  ],
  lifecycleStages: [
    { id: "create", label: "Create Cluster", state: "complete" },
    { id: "clone", label: "Clone Schema", state: "complete" },
    { id: "apply", label: "Apply Migration", state: "current" },
    { id: "measure", label: "Measure", state: "pending" },
    { id: "rollback", label: "Rollback Test", state: "pending" },
    { id: "verify", label: "Verify", state: "pending" },
  ],
  schemaChanges: {
    table: "orders",
    mutations: [
      { name: "created_by", detail: "UUID" },
      { name: "fk_created_by", detail: "FK → users.id" },
      { name: "idx_orders_created_at", detail: "INDEX" },
    ],
  },
  currentOperation: {
    sql: `CREATE INDEX CONCURRENTLY idx_orders_created_at
ON orders (created_by);`,
    statementsCompleted: 8,
    statementsTotal: 12,
  },
  events: [
    { time: "03:46:21", message: "shadow cluster provisioned" },
    { time: "03:46:23", message: "schema cloned" },
    { time: "03:46:24", message: "migration started" },
    { time: "03:46:25", message: "scanning orders..." },
    { time: "03:46:26", message: "index backfill started" },
    { time: "03:46:27", message: "validating index..." },
    { time: "03:46:28", message: "no blocking locks detected" },
  ],
  telemetry: {
    runtime: "2.8s",
    storage: "+14 MB",
    locks: 0,
    failures: 0,
  },
}
