/**
 * Which tone and label each status gets, for the status enums in the API (src/api/schema.d.ts). The colours of each
 * tone are in src/theme.ts (STATUS_TONES, SEVERITY_STYLES); StatusBadge and SeverityBadge render them.
 */
import type {
  BankChangeStatus,
  BillStatus,
  FlagResolution,
  PaymentStatus,
  UserStatus,
  VendorStatus,
} from '../api/types'
import type { StatusTone } from '../theme'

interface StatusStyle {
  label: string
  tone: StatusTone
}

export const BILL_STATUS: Record<BillStatus, StatusStyle> = {
  needs_review: { label: 'Needs review', tone: 'attention' },
  on_hold: { label: 'On hold', tone: 'attention' },
  pending_approval: { label: 'Pending approval', tone: 'progress' },
  approved: { label: 'Approved', tone: 'success' },
  rejected: { label: 'Rejected', tone: 'danger' },
  scheduled: { label: 'Scheduled', tone: 'progress' },
  paid: { label: 'Paid', tone: 'success' },
  credit_open: { label: 'Credit open', tone: 'neutral' },
  void: { label: 'Void', tone: 'neutral' },
}

export const PAYMENT_STATUS: Record<PaymentStatus, StatusStyle> = {
  scheduled: { label: 'Scheduled', tone: 'progress' },
  released: { label: 'Released', tone: 'progress' },
  settled: { label: 'Settled', tone: 'success' },
  outstanding: { label: 'Outstanding', tone: 'attention' },
  failed: { label: 'Failed', tone: 'danger' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
}

export const VENDOR_STATUS: Record<VendorStatus, StatusStyle> = {
  active: { label: 'Active', tone: 'success' },
  on_hold: { label: 'On hold', tone: 'attention' },
  pending_review: { label: 'Pending review', tone: 'attention' },
}

export const BANK_CHANGE_STATUS: Record<BankChangeStatus, StatusStyle> = {
  pending_verification: { label: 'Pending verification', tone: 'attention' },
  verified: { label: 'Verified', tone: 'success' },
  rejected: { label: 'Rejected', tone: 'danger' },
}

/** A person's status (users.status); "On leave" matters when picking or assigning someone. */
export const USER_STATUS: Record<UserStatus, StatusStyle> = {
  active: { label: 'Active', tone: 'success' },
  on_leave: { label: 'On leave', tone: 'neutral' },
  terminated: { label: 'Terminated', tone: 'neutral' },
}

/** Whether a flag still needs a person: open, or overridden / resolved (with who, when and why). */
export const FLAG_RESOLUTION: Record<FlagResolution, StatusStyle> = {
  // Neutral, not attention: the severity badge beside it already says how urgent the flag is.
  open: { label: 'Open', tone: 'neutral' },
  overridden: { label: 'Overridden', tone: 'neutral' },
  resolved: { label: 'Resolved', tone: 'success' },
}

/** The status tables by kind, for <StatusBadge kind=... status=...>. */
export const STATUS_STYLES = {
  bill: BILL_STATUS,
  payment: PAYMENT_STATUS,
  vendor: VENDOR_STATUS,
  bankChange: BANK_CHANGE_STATUS,
  user: USER_STATUS,
  flag: FLAG_RESOLUTION,
} as const

export type StatusKind = keyof typeof STATUS_STYLES

/** Severity labels for flags. */
export const SEVERITY_LABELS = { block: 'Blocking', warn: 'Warning', info: 'Info' } as const
