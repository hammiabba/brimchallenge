import type { IntakeItemStatus } from '../api/types'
import type { StatusTone } from '../theme'

/** Each intake item status as a label and one of the theme's status tones (DESIGN.md, Status badges). */
export const INTAKE_STATUS: Record<IntakeItemStatus, { label: string; tone: StatusTone }> = {
  queued: { label: 'Queued', tone: 'neutral' },
  processing: { label: 'Processing', tone: 'progress' },
  ok: { label: 'Done', tone: 'success' },
  llm_skipped: { label: 'Read without LLM', tone: 'attention' },
  failed: { label: 'Failed', tone: 'danger' },
}

/** True while the server is still working on the item, so the screen keeps polling. */
export function isPending(status: IntakeItemStatus): boolean {
  return status === 'queued' || status === 'processing'
}
