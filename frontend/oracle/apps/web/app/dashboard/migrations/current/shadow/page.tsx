import { CURRENT_MIGRATION } from "../data"
import { ShadowExecutionWorkspace } from "./shadow-execution-workspace"
import { LIVE_SHADOW_EXECUTION } from "./shadow-execution-state"

export default function ShadowExecutionPage() {
  return (
    <ShadowExecutionWorkspace
      migration={CURRENT_MIGRATION}
      liveData={LIVE_SHADOW_EXECUTION}
    />
  )
}
