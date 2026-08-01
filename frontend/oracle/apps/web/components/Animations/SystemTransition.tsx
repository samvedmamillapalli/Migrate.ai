/**
 * @deprecated Import from `@/components/system` instead.
 * Thin re-export so existing ProductPreview imports keep working.
 */
export {
  StatusTransition as SystemStatusBlock,
  StatusTransition,
  type StatusTransitionProps as SystemStatusBlockProps,
  type StatusTransitionState as SystemStatusState,
  type StatusDetail as SystemStatusDetail,
} from "@/components/system/StatusTransition"

import StatusTransition from "@/components/system/StatusTransition"
export default StatusTransition
