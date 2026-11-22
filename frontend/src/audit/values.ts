/**
 * How the audit page shows one before/after value of an expanded event, in the words the rest of the app uses.
 * Display only: the stored events, the API and the CSV export keep the raw values.
 *
 * Every mapping comes from where the app already keeps it (status badges, role and step-role words, channel,
 * severity, payment-method and email-class labels, flag help, the money and date formatters); nothing is copied
 * here. A field this file doesn't know keeps its raw value; objects and arrays are pretty-printed JSON.
 */
import { codeAsWords } from '../api/reference'
import type { Role } from '../api/types'
import { ROLE_LABELS } from '../auth/roles'
import { DEPARTMENT_SOURCES, PAYMENT_METHOD_LABELS, bankChannelLabel, stepRoleLabel } from '../bills/labels'
import { EMAIL_CLASS, INTAKE_STATUS } from '../intake/common/labels'
import { formatDate, formatTimestamp, parseDateOnly } from '../lib/dates'
import { formatMoney, isMoney } from '../lib/money'
import { SEVERITY_LABELS, STATUS_STYLES, type StatusKind } from '../ui/statusStyles'

/** One value as shown: lines of words, or a JSON block in the monospace style. */
export type AuditValueView = { kind: 'text'; lines: string[] } | { kind: 'json'; text: string }

/** What the formatter needs from the page: the event's entity type and currency, and how to name people and flags. */
export interface AuditValueContext {
  /** The event's entity_type: picks which status words apply ("bill", "payment", "vendor", ...). */
  entityType: string
  /** The event's currency (after.currency, else before.currency), for money fields not named "_cad". */
  currency: string
  /** "Sam Rivera (U012)" for a known user, the id alone ("U099") when the name can't be found. */
  personLabel: (userId: string) => string
  /** A flag code's title from flag help, or the code in words. */
  flagTitle: (code: string) => string
}

/** Shown for a missing or empty value, so no cell is ever blank. */
export const EMPTY_VALUE = '—'

type StatusTable = Record<string, { label: string }>

/** The status words for an entity type: the badge labels of that kind (intake items have their own). */
const STATUS_BY_ENTITY: Record<string, StatusTable> = {
  bill: STATUS_STYLES.bill,
  payment: STATUS_STYLES.payment,
  vendor: STATUS_STYLES.vendor,
  user: STATUS_STYLES.user,
  intake_item: INTAKE_STATUS,
}

/** Status fields whose name says which kind they are, whatever the event's entity type. */
const STATUS_BY_KEY: Record<string, StatusTable> = {
  bill_status: STATUS_STYLES.bill,
  vendor_status: STATUS_STYLES.vendor,
  resolution: STATUS_STYLES.flag,
}

/** A user id field: "user_id", "requester_user_id", "started_by", "verified_by", "manager_id", "on_behalf_of". */
const PERSON_KEY = /(^|_)user_id$|_by$|^manager_id$|^on_behalf_of$/
/** A money field: "amount", "amount_cad", "total", "approval_limit_cad" (and the value must be a money string). */
const MONEY_KEY = /(^|_)(amount|total|subtotal|limit)(_|$)/
/** An ISO timestamp ("2026-10-30T14:00:00Z"); date-only values are handled by parseDateOnly. */
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/

/** True for a value with nothing to show: missing, null, empty text, an empty list or an empty object. */
function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'object') return Object.keys(value as object).length === 0
  return false
}

/** A status code in the badge's words: the entity's kind first, then a kind named by the field, then any kind. */
function statusWords(key: string, code: string, entityType: string): string {
  const tables = [STATUS_BY_KEY[key], STATUS_BY_ENTITY[entityType],
    ...(Object.keys(STATUS_STYLES) as StatusKind[]).map((kind) => STATUS_STYLES[kind] as StatusTable)]
  for (const table of tables) {
    const found = table?.[code]
    if (found) return found.label
  }
  return code
}

/** A role code: a user role in the role words ("Finance manager"), else an approval-step role ("Department manager"). */
function roleWords(code: string): string {
  return (ROLE_LABELS as Record<string, string>)[code as Role] ?? stepRoleLabel(code)
}

/** One approval step of a route: "Step 1: Department manager, Sam Rivera (U012)". */
function routeStep(step: Record<string, unknown>, context: AuditValueContext): string {
  const who = typeof step.user_id === 'string' && step.user_id ? context.personLabel(step.user_id) : 'unassigned'
  return `Step ${String(step.step_no)}: ${stepRoleLabel(String(step.role))}, ${who}`
}

/** True when `value` is a route: a list of steps, each with a step number and a role. */
function isRoute(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.every((step) =>
    typeof step === 'object' && step !== null && 'step_no' in step && 'role' in step)
}

/** A string value by its field: known codes in words, people by name, money, dates and timestamps; else as stored. */
function stringWords(key: string, value: string, context: AuditValueContext): string {
  switch (key) {
    case 'status':
    case 'bill_status':
    case 'vendor_status':
    case 'resolution':
      return statusWords(key, value, context.entityType)
    case 'role':
    case 'actor_role':
      return roleWords(value)
    case 'step_role':
      return stepRoleLabel(value)
    case 'request_channel':
    case 'channel':
      return bankChannelLabel(value)
    case 'severity':
      return (SEVERITY_LABELS as Record<string, string>)[value] ?? value
    case 'code':
    case 'flag_code':
    case 'top_flag_code':
      return context.flagTitle(value)
    case 'entity_type':
      return codeAsWords(value)
    case 'method':
      return PAYMENT_METHOD_LABELS[value] ?? value
    case 'email_class':
      return EMAIL_CLASS[value]?.label ?? value
    case 'department_source':
      return (DEPARTMENT_SOURCES as Record<string, { label: string }>)[value]?.label ?? value
  }
  if (PERSON_KEY.test(key)) return context.personLabel(value)
  if (MONEY_KEY.test(key) && isMoney(value)) return formatMoney(value, key.endsWith('_cad') ? 'CAD' : context.currency)
  if (parseDateOnly(value)) return formatDate(value)
  if (TIMESTAMP.test(value)) {
    try {
      return formatTimestamp(value, { timeZone: 'UTC' })
    } catch {
      return value // not a real timestamp after all: show it as stored
    }
  }
  return value
}

/**
 * One before or after value as shown on the audit page:
 * - empty or missing: an em dash;
 * - booleans: Yes / No;
 * - a route: one line per step, "Step N: <role>, <name> (<id>)", or the id alone when the name isn't known;
 * - other objects and arrays: pretty-printed JSON;
 * - strings: known code fields in words, people, money, dates (timestamps in UTC); anything else as stored;
 * - numbers: as stored.
 */
export function formatAuditValue(key: string, value: unknown, context: AuditValueContext): AuditValueView {
  if (isEmpty(value)) return { kind: 'text', lines: [EMPTY_VALUE] }
  if (typeof value === 'boolean') return { kind: 'text', lines: [value ? 'Yes' : 'No'] }
  if (key === 'route' && isRoute(value)) return { kind: 'text', lines: value.map((step) => routeStep(step, context)) }
  if (typeof value === 'object') return { kind: 'json', text: JSON.stringify(value, null, 2) }
  if (typeof value === 'string') return { kind: 'text', lines: [stringWords(key, value, context)] }
  return { kind: 'text', lines: [String(value)] }
}

/** The currency an event's money is in: after.currency, else before.currency, else CAD. */
export function eventCurrency(before: Record<string, unknown>, after: Record<string, unknown>): string {
  for (const value of [after.currency, before.currency]) {
    if (typeof value === 'string' && value) return value
  }
  return 'CAD'
}
