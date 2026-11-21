/**
 * Words for the codes the bill screens show: approval step roles, payment methods, vendor match methods,
 * department sources, duplicate kinds, bank-change channels and audit actions.
 */
import type { AuditEvent, DepartmentSource } from '../api/types'
import { codeAsWords } from '../api/reference'

/** Approval step roles (RouteStepOut.role), which are policy step names, not user roles. */
const STEP_ROLES: Record<string, string> = {
  dept_manager: 'Department manager',
  finance_manager: 'Finance manager',
  controller_admin: 'Controller',
  cfo: 'CFO',
}

/** "Department manager" for dept_manager; unknown roles as words. */
export function stepRoleLabel(role: string): string {
  return STEP_ROLES[role] ?? codeAsWords(role.toUpperCase())
}

/** Payment methods (PaymentSummary.method). */
export const PAYMENT_METHOD_LABELS: Record<string, string> = { EFT: 'EFT', CHEQUE: 'Cheque', CARD: 'Card' }

/** How intake matched the invoice to a vendor (DraftBill.vendor.match_method). */
const MATCH_METHODS: Record<string, string> = {
  gst_number: 'GST number',
  bank_account: 'bank account',
  email_domain: 'email domain',
  fuzzy_name: 'similar name',
}

/** "Matched by GST number (score 0.92)", or "Not matched to a vendor". */
export function vendorMatchLine(method: unknown, score: unknown): string {
  const label = typeof method === 'string' ? MATCH_METHODS[method] : undefined
  if (!label) return 'Not matched to a vendor'
  // The score is a 0..1 similarity, not money: showing it with two decimals is fine.
  return typeof score === 'number' ? `Matched by ${label} (score ${score.toFixed(2)})` : `Matched by ${label}`
}

/** Where the bill's department came from (BillDetail.department_source). `unconfirmed` marks a suggestion. */
export const DEPARTMENT_SOURCES: Record<DepartmentSource, { label: string; unconfirmed: boolean }> = {
  invoice: { label: 'from the invoice', unconfirmed: false },
  submitter: { label: "from the submitter's department", unconfirmed: false },
  coding: { label: 'suggested from the line coding', unconfirmed: true },
  user: { label: 'set by a person', unconfirmed: false },
  history: { label: 'from the dataset history', unconfirmed: false },
}

/** Duplicate match kinds (DuplicateOut.kind). */
const DUPLICATE_KINDS: Record<string, string> = {
  exact: 'Exact duplicate',
  normalized: 'Same invoice number after normalizing',
  near: 'Near duplicate',
  card_paid: 'Already paid by card',
  cross_vendor: 'Same invoice under another vendor',
}

/** "Exact duplicate" for exact; unknown kinds as words. */
export function duplicateKindLabel(kind: string): string {
  return DUPLICATE_KINDS[kind] ?? codeAsWords(kind.toUpperCase())
}

/** How a bank change request came in (bank change request_channel). */
const BANK_CHANNELS: Record<string, string> = {
  phone_callback_verified: 'Phone, verified by callback',
  vendor_portal: 'Vendor portal',
  email_request: 'Email request',
}

/** "Email request" for email_request; unknown channels as words. */
export function bankChannelLabel(channel: string): string {
  return BANK_CHANNELS[channel] ?? codeAsWords(channel.toUpperCase())
}

/** An audit action as words: "bill.flag_overridden" -> "Flag overridden", "auth.login" -> "Auth login". */
export function auditActionLabel(action: string): string {
  const [entity, ...rest] = action.split('.')
  const words = (entity === 'bill' && rest.length > 0 ? rest.join(' ') : action.replace('.', ' ')).replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** A before/after value as short text (objects and lists as JSON, which the server already redacted). */
function short(value: unknown): string {
  if (value === null || value === undefined) return 'none'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

/** "status: pending_approval -> approved; comment" for one event, from its before/after and comment. */
export function auditDetails(event: AuditEvent): string {
  const before = event.before ?? {}
  const after = event.after ?? {}
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])]
  const changes = keys.map((key) => (key in before
    ? `${key}: ${short(before[key])} → ${short(after[key])}`
    : `${key}: ${short(after[key])}`))
  return [...changes, ...(event.comment ? [`"${event.comment}"`] : [])].join('; ')
}
