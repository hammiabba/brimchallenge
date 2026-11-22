/**
 * Plain-language audit events for the bill and payment screens: who acted ("Jordan Okafor (U004)", or "System, for
 * Aiden Grant (U013)" for work the system did on someone's behalf), one sentence for the common actions, and the
 * before/after values as "label: value" rows with readable labels. Pure functions; names come in through `context`.
 */
import type { AuditEvent } from '../api/types'
import { formatDate, parseDateOnly } from '../lib/dates'
import { formatMoney, isMoney } from '../lib/money'
import { BILL_STATUS, PAYMENT_STATUS } from '../ui/statusStyles'
import { PAYMENT_METHOD_LABELS, stepRoleLabel } from './labels'

export interface AuditContext {
  /** "Aiden Grant (U013)" for a user id (the id alone when the name isn't known). */
  personLabel: (userId: string) => string
  /** A flag code's title from flag help ("Duplicate invoice"), or the code in words. */
  flagTitle: (code: string) => string
}

/** One "label: value" row; `before` is set when the value changed from something. Values may span several lines. */
export interface AuditChange {
  key: string
  label: string
  before?: string[]
  after?: string[]
}

type Payload = Record<string, unknown>

const ACTOR_SYSTEM = 'system'

/** Readable labels for the keys the services write. Anything else: "_id" dropped, words capitalised. */
const FIELD_LABELS: Record<string, string> = {
  department_id: 'Department',
  department_source: 'Department from',
  vendor_id: 'Vendor',
  vendor_invoice_number: 'Invoice number',
  requester_user_id: 'Requester',
  po_id: 'PO',
  contract_id: 'Contract',
  gl_account: 'GL account',
  suggested_gl_account: 'Suggested GL account',
  coding_status: 'Coding',
  step_no: 'Step',
  step_role: 'Step role',
  user_id: 'Approver',
  started_by: 'Started by',
  intake_item_id: 'Intake item',
  email_id: 'Email',
  file_name: 'File',
  bill_id: 'Bill',
  bank_account_id: 'Bank account',
  amount_cad: 'Amount (CAD)',
  flag_id: 'Flag',
  final: 'Final approval',
  ship_to_province: 'Ship-to province',
  fx_rate_to_cad: 'FX rate',
  rule: 'Rule',
}

/** "department_id" -> "Department", "due_date" -> "Due date", "line_no" -> "Line". */
export function auditFieldLabel(key: string): string {
  const known = FIELD_LABELS[key]
  if (known) return known
  const words = key.replace(/_(id|no)$/, '').split('_').join(' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** True for a value not worth showing: missing, empty text, an empty list or an empty object. */
function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return true
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'object') return Object.keys(value as object).length === 0
  return false
}

/** A status code as its badge label ("pending_approval" -> "Pending approval"), else as sent. */
function statusLabel(value: string): string {
  return (BILL_STATUS as Record<string, { label: string }>)[value]?.label
    ?? (PAYMENT_STATUS as Record<string, { label: string }>)[value]?.label
    ?? value
}

/** One value as text lines, by key and type: statuses, people, dates and money in words; lists one item per line. */
export function auditValueText(key: string, value: unknown, context: AuditContext, currency = 'CAD'): string[] {
  if (isEmpty(value)) return []
  if (Array.isArray(value)) return value.flatMap((item) => auditValueText(key, item, context, currency))
  if (typeof value === 'boolean') return [value ? 'Yes' : 'No']
  if (typeof value === 'object') {
    const item = value as Payload
    // An approval step ({step_no, role, user_id}): "Step 1, Department manager: Dev Malhotra (U007)".
    if ('step_no' in item && 'role' in item) {
      const who = typeof item.user_id === 'string' ? context.personLabel(item.user_id) : 'unassigned'
      return [`Step ${String(item.step_no)}, ${stepRoleLabel(String(item.role))}: ${who}`]
    }
    const parts = Object.entries(item).filter(([, v]) => !isEmpty(v))
      .map(([k, v]) => `${auditFieldLabel(k)} ${auditValueText(k, v, context, currency).join(', ')}`)
    return parts.length > 0 ? [parts.join(', ')] : []
  }
  const text = String(value)
  if (key === 'status' || key === 'bill_status') return [statusLabel(text)]
  if (/^U\d{3,}$/.test(text)) return [context.personLabel(text)]
  if (key === 'method') return [PAYMENT_METHOD_LABELS[text] ?? text]
  if (/(^|_)(amount|total|subtotal)(_|$)/.test(key) && isMoney(text)) {
    return [formatMoney(text, key.endsWith('_cad') ? 'CAD' : currency)]
  }
  if (parseDateOnly(text)) return [formatDate(text)]
  return [text]
}

/**
 * The before/after values as rows: every key in either, minus empty values and values that didn't change.
 * Before is shown only when it held something.
 */
export function auditChanges(event: AuditEvent, context: AuditContext): AuditChange[] {
  const before = (event.before ?? {}) as Payload
  const after = (event.after ?? {}) as Payload
  const currency = typeof after.currency === 'string' ? after.currency : 'CAD'
  const rows: AuditChange[] = []
  for (const key of [...new Set([...Object.keys(before), ...Object.keys(after)])]) {
    if (key === 'currency') continue // shown inside the amounts
    const was = auditValueText(key, before[key], context, currency)
    const now = auditValueText(key, after[key], context, currency)
    if (was.length === 0 && now.length === 0) continue
    if (was.join('\n') === now.join('\n')) continue
    rows.push({ key, label: auditFieldLabel(key), ...(was.length > 0 ? { before: was } : {}), ...(now.length > 0 ? { after: now } : {}) })
  }
  return rows
}

/** "a", "a and b", "a, b and c". */
function naturalJoin(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/** A field label inside a sentence: "Due date" -> "due date", but "GL account" and "PO" keep their capitals. */
function inSentence(label: string): string {
  return /^[A-Z]{2}/.test(label) ? label : label.charAt(0).toLowerCase() + label.slice(1)
}

/** The value under `key` as text, or '' when absent. */
function str(payload: Payload, key: string): string {
  const value = payload[key]
  return value === null || value === undefined ? '' : String(value)
}

/**
 * One sentence for the common actions (bill created, updated, coded, flags overridden or resolved, submitted,
 * approved, rejected, voided, step assigned; payment scheduled, released or cancelled), or null for any other action:
 * those show their "label: value" rows instead.
 */
export function auditSentence(event: AuditEvent, context: AuditContext): string | null {
  const before = (event.before ?? {}) as Payload
  const after = (event.after ?? {}) as Payload
  const currency = str(after, 'currency') || 'CAD'
  const money = (key: string, cur = currency): string => {
    const value = str(after, key)
    return isMoney(value) ? formatMoney(value, cur) : value
  }
  switch (event.action) {
    case 'bill.created': {
      const file = str(after, 'file_name')
      const email = str(after, 'email_id')
      if (email) return `Created from email ${email}${file ? ` (${file})` : ''}.`
      return file ? `Created from an upload (${file}).` : 'Created.'
    }
    case 'bill.updated': {
      const fields = Object.keys(after).map((key) => inSentence(auditFieldLabel(key)))
      return fields.length > 0 ? `Updated the ${naturalJoin(fields)}.` : 'Updated the bill.'
    }
    case 'bill.coding_changed': {
      const how = str(after, 'coding_status') === 'accepted' ? ', accepting the suggestion'
        : str(after, 'coding_status') === 'overridden' ? ', changing the suggestion' : ''
      return `Coded line ${str(after, 'line_no') || str(before, 'line_no')} to GL ${str(after, 'gl_account')} and `
        + `department ${str(after, 'department_id')}${how}.`
    }
    case 'bill.flag_overridden':
    case 'bill.flag_resolved': {
      const verb = event.action === 'bill.flag_overridden' ? 'Overrode' : 'Resolved'
      const code = str(after, 'code') || str(before, 'code')
      return code ? `${verb} the "${context.flagTitle(code)}" flag.` : `${verb} a flag.`
    }
    case 'bill.submitted': {
      const route = Array.isArray(after.route) ? (after.route as Payload[]) : []
      const first = route[0]
      const firstUser = first && typeof first.user_id === 'string' ? first.user_id : null
      return firstUser ? `Submitted for approval; step 1 goes to ${context.personLabel(firstUser)}.`
        : 'Submitted for approval.'
    }
    case 'bill.approved': {
      const step = str(after, 'step_no') || str(before, 'step_no')
      const role = str(after, 'step_role')
      const final = after.final === true ? ' Final approval: the bill is approved.' : ''
      return `Approved step ${step}${role ? ` (${stepRoleLabel(role)})` : ''}.${final}`
    }
    case 'bill.rejected':
      return `Rejected at step ${str(after, 'step_no') || str(before, 'step_no')}.`
    case 'bill.voided':
      return 'Voided the bill.'
    case 'bill.step_assigned': {
      const user = str(after, 'user_id')
      return `Assigned step ${str(after, 'step_no')} to ${user ? context.personLabel(user) : 'nobody'}.`
    }
    case 'payment.scheduled': {
      const method = PAYMENT_METHOD_LABELS[str(after, 'method')] ?? str(after, 'method')
      const date = str(after, 'scheduled_date')
      return `Scheduled a payment of ${money('amount')}${method ? ` by ${method}` : ''}`
        + `${date && parseDateOnly(date) ? ` for ${formatDate(date)}` : ''}.`
    }
    case 'payment.released': {
      const reference = str(after, 'reference')
      return `Released the payment of ${money('amount_cad', 'CAD')}${reference ? ` (reference ${reference})` : ''}.`
    }
    case 'payment.cancelled':
      return 'Cancelled the payment.'
    default:
      return null
  }
}

/** The user an event names, for work the system did on someone's behalf (who started the intake, or on whose behalf). */
function namedUser(event: AuditEvent): string | null {
  const before = (event.before ?? {}) as Payload
  const after = (event.after ?? {}) as Payload
  for (const value of [after.started_by, event.on_behalf_of, after.on_behalf_of, before.started_by]) {
    if (typeof value === 'string' && value) return value
  }
  return null
}

/**
 * Who acted: "Jordan Okafor (U004)", with "on behalf of Liam O'Connor (U012)" when a delegate acted; for the system,
 * "System, for Aiden Grant (U013)" when the event names the user it acted for, else "System".
 */
export function auditActor(event: AuditEvent, context: AuditContext): { who: string; onBehalfOf: string | null } {
  if (event.actor_user_id === ACTOR_SYSTEM) {
    const user = namedUser(event)
    return { who: user ? `System, for ${context.personLabel(user)}` : 'System', onBehalfOf: null }
  }
  return {
    who: context.personLabel(event.actor_user_id),
    onBehalfOf: event.on_behalf_of ? context.personLabel(event.on_behalf_of) : null,
  }
}
