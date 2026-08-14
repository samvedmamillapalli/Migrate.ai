import path from "node:path"
import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  transpilePackages: ["@workspace/ui"],
  // Container deploys: emit a self-contained server bundle so the runtime image
  // does not need the full monorepo node_modules tree.
  output: "standalone",
  // This app is one workspace inside frontend/oracle. Without pointing file
  // tracing at the monorepo root, Next traces only apps/web and omits the
  // hoisted node_modules and @workspace/ui — producing a standalone build that
  // starts and then crashes on a missing module.
  outputFileTracingRoot: path.join(import.meta.dirname, "../../"),
}

export default nextConfig
