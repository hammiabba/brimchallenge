/** Labels and status tones for intake items and inbox email classes. */
import type { StatusTone } from '../../theme'
import type { IntakeItemStatus } from './types'

export interface IntakeStyle {
  label: string
  tone: StatusTone
}

/** Where one uploaded or emailed file is in intake. "Not read" means the invoice reader was off (no bill made). */
export const INTAKE_STATUS: Record<IntakeItemStatus, IntakeStyle> = {
  queued: { label: 'Queued', tone: 'neutral' },
  processing: { label: 'Processing', tone: 'progress' },
  ok: { label: 'Done', tone: 'success' },
  llm_skipped: { label: 'Not read', tone: 'attention' },
  failed: { label: 'Failed', tone: 'danger' },
}

/** How intake sorted an inbox email (backend EmailClass). An unknown class falls back to its code as words. */
export const EMAIL_CLASS: Record<string, IntakeStyle> = {
  invoice: { label: 'Invoice', tone: 'progress' },
  credit_note: { label: 'Credit note', tone: 'progress' },
  statement: { label: 'Statement', tone: 'neutral' },
  payment_inquiry: { label: 'Payment inquiry', tone: 'attention' },
  missing_attachment: { label: 'Missing attachment', tone: 'attention' },
  not_ap: { label: 'Not AP', tone: 'neutral' },
}

/** A status string from the API as an intake status, or null if it isn't one. */
export function asIntakeStatus(value: string): IntakeItemStatus | null {
  return Object.hasOwn(INTAKE_STATUS, value) ? (value as IntakeItemStatus) : null
}

/** Statuses that won't change any more, so polling can stop. */
export function isFinalStatus(status: IntakeItemStatus): boolean {
  return status !== 'queued' && status !== 'processing'
}
