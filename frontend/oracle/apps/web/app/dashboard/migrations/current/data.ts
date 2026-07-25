export type ProcessStageState = "complete" | "current" | "pending"

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH"

export type MigrationAssessment = {
  recommendation: string
  overallRisk: RiskLevel
  confidence: string
  summary: string
  benefits: string[]
  concerns: string[]
  expectedImpact: {
    predictedRuntime: string
    expectedStorage: string
    tablesAffected: number
    indexesCreated: number
    constraintsAdded: number
  }
  riskBreakdown: {
    lockRisk: RiskLevel
    rollbackRisk: RiskLevel
    dataLossRisk: RiskLevel
    performanceRisk: RiskLevel
  }
  recommendedActions: string[]
  reasoning: string
}

export type MigrationRun = {
  id: string
  filename: string
  sourceDb: string
  targetDb: string
  status: "EXECUTING" | "VERIFIED" | "FAILED" | "APPROVED" | "REJECTED"
  submittedAgo: string
  process: {
    id: string
    label: string
    state: ProcessStageState
  }[]
  sql: string
  metadata: {
    tablesAffected: number
    indexes: number
    statements: number
  }
  /** Structured Bedrock/model assessment preview — replace with API response later. */
  assessment: MigrationAssessment
  shadow: {
    id: string
    engine: string
    status: "READY" | "PROVISIONING" | "DESTROYED"
    lifecycle: string
    region?: string
    events: { time: string; message: string }[]
    observed: {
      runtime: string
      storage: string
      statementsCompleted: number
      statementsTotal: number
      blockingLocks: number
      failures: number
      rollbackTest: string
    }
  }
  decision: {
    verdict: string
    recommendation: string
    confidence: string
    comparisons: {
      label: string
      predicted: string
      actual: string
      delta?: string
    }[]
  }
}

export const CURRENT_MIGRATION: MigrationRun = {
  id: "mig_2026_07_24",
  filename: "migration_2026_07_24.sql",
  sourceDb: "PostgreSQL",
  targetDb: "CockroachDB",
  status: "EXECUTING",
  submittedAgo: "2m ago",
  process: [
    { id: "analyze", label: "Analyze", state: "complete" },
    { id: "predict", label: "Predict", state: "complete" },
    { id: "provision", label: "Provision Shadow", state: "complete" },
    { id: "execute", label: "Execute", state: "complete" },
    { id: "verify", label: "Verify", state: "current" },
    { id: "learn", label: "Learn", state: "pending" },
  ],
  sql: `-- Track order authorship and enforce referential integrity
ALTER TABLE orders
  ADD COLUMN created_by UUID;

ALTER TABLE orders
  ADD CONSTRAINT orders_created_by_fkey
  FOREIGN KEY (created_by) REFERENCES users (id);

CREATE INDEX CONCURRENTLY idx_orders_created_by
  ON orders (created_by);`,
  metadata: {
    tablesAffected: 2,
    indexes: 1,
    statements: 12,
  },
  assessment: {
    recommendation: "PROCEED WITH CAUTION",
    overallRisk: "MEDIUM",
    confidence: "97%",
    summary:
      "Adds ownership tracking to orders by introducing created_by, linking it to users, and creating an index for ownership lookups.",
    benefits: [
      "Enforces referential integrity between orders and users",
      "Adds explicit ownership information to orders",
      "Improves created_by lookup performance",
    ],
    concerns: [
      "CREATE INDEX requires scanning the orders table",
      "Foreign-key validation may add execution cost",
      "Index creation increases temporary resource usage",
    ],
    expectedImpact: {
      predictedRuntime: "3.6s",
      expectedStorage: "+18 MB",
      tablesAffected: 2,
      indexesCreated: 1,
      constraintsAdded: 1,
    },
    riskBreakdown: {
      lockRisk: "MEDIUM",
      rollbackRisk: "LOW",
      dataLossRisk: "LOW",
      performanceRisk: "MEDIUM",
    },
    recommendedActions: [
      "Monitor index creation",
      "Verify existing created_by values before enforcing the foreign key",
      "Review the shadow execution before approval",
    ],
    reasoning:
      "The foreign-key attach is cheap against a warm users primary key, but the concurrent index build must scan orders. Similar migrations in this schema finished near 3.6s with modest storage growth and no prolonged lock contention.",
  },
  shadow: {
    id: "SHADOW-7F2A",
    engine: "CockroachDB",
    status: "READY",
    lifecycle: "ephemeral",
    region: "us-east-1",
    events: [
      { time: "03:46:21", message: "Shadow cluster provisioned" },
      { time: "03:46:23", message: "Schema replicated" },
      { time: "03:46:24", message: "Migration started" },
      { time: "03:46:25", message: "ALTER TABLE completed" },
      { time: "03:46:27", message: "CREATE INDEX completed" },
      { time: "03:46:28", message: "Constraints validated" },
      { time: "03:46:29", message: "Measurements captured" },
      { time: "03:46:31", message: "Verification completed" },
    ],
    observed: {
      runtime: "3.8s",
      storage: "+17 MB",
      statementsCompleted: 12,
      statementsTotal: 12,
      blockingLocks: 0,
      failures: 0,
      rollbackTest: "Passed",
    },
  },
  decision: {
    verdict: "SAFE TO MIGRATE",
    confidence: "97%",
    recommendation:
      "Shadow execution matched the prediction within expected range. Index build completed without blocking locks, rollback validation passed, and storage growth stayed under the forecast. Approve to proceed against the target cluster.",
    comparisons: [
      {
        label: "Runtime",
        predicted: "3.6s",
        actual: "3.8s",
        delta: "Δ +0.2s",
      },
      {
        label: "Storage",
        predicted: "+18 MB",
        actual: "+17 MB",
        delta: "Δ -1 MB",
      },
      {
        label: "Rollback",
        predicted: "Low Risk",
        actual: "Passed",
      },
      {
        label: "Lock Risk",
        predicted: "Medium",
        actual: "No blocking locks observed",
      },
    ],
  },
}
