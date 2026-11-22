/**
 * The audit log's filters live in the URL query string, so a filtered view can be shared:
 *   ?entity_type=bill&entity_id=AP-00407&actor=U005&action=bill.approved&from=2026-10-01&to=2026-10-31
 * They map onto GET /audit (and GET /audit/export): entity_type, entity_id, actor, action, since and until. Dates are
 * whole UTC days (the API stores UTC timestamps): `from` is sent as since 00:00:00Z, `to` as until 23:59:59Z.
 * The keyset cursor (after_seq) is not in the URL; it is page state that resets whenever a filter changes.
 */

/** The entity types events are recorded against (entity_type in backend/app/services and app/db/audit.py). */
export const ENTITY_TYPES = ['bill', 'payment', 'vendor', 'user', 'policy', 'intake_item', 'intake_run', 'email',
  'audit_log', 'system'] as const

/** Every action the backend records (AuditAction in backend/app/db/audit.py), for the action filter. */
export const ACTIONS = [
  'bill.created', 'bill.updated', 'bill.coding_changed', 'bill.flag_overridden', 'bill.flag_resolved',
  'bill.submitted', 'bill.approved', 'bill.rejected', 'bill.voided',
  'payment.scheduled', 'payment.released', 'payment.cancelled',
  'vendor.created', 'vendor.approved', 'vendor.status_changed', 'vendor.bank_change_requested',
  'vendor.bank_change_verified', 'vendor.bank_change_rejected',
  'policy.updated', 'absence.created', 'absence.ended', 'user.updated',
  'auth.login', 'auth.logout',
  'intake.item_created', 'intake.run_started', 'intake.run_finished',
  'audit.exported',
] as const

export interface AuditFilters {
  entityType: string | null
  entityId: string
  actor: string | null
  action: string | null
  /** YYYY-MM-DD or empty. */
  from: string
  to: string
}

const DATE = /^\d{4}-\d{2}-\d{2}$/

/** The filters in a URL query string; malformed dates are ignored. */
export function filtersFromSearch(search: URLSearchParams): AuditFilters {
  const date = (key: string) => {
    const value = search.get(key) ?? ''
    return DATE.test(value) ? value : ''
  }
  return {
    entityType: search.get('entity_type') || null,
    entityId: search.get('entity_id') ?? '',
    actor: search.get('actor') || null,
    action: search.get('action') || null,
    from: date('from'),
    to: date('to'),
  }
}

/** The URL query string for some filters; empty filters are left out. */
export function searchFromFilters(filters: AuditFilters): URLSearchParams {
  const search = new URLSearchParams()
  if (filters.entityType) search.set('entity_type', filters.entityType)
  if (filters.entityId.trim()) search.set('entity_id', filters.entityId.trim())
  if (filters.actor) search.set('actor', filters.actor)
  if (filters.action) search.set('action', filters.action)
  if (filters.from) search.set('from', filters.from)
  if (filters.to) search.set('to', filters.to)
  return search
}

/** The query GET /audit and GET /audit/export take for some filters (without paging). */
export function apiFilters(filters: AuditFilters) {
  return {
    ...(filters.entityType ? { entity_type: filters.entityType } : {}),
    ...(filters.entityId.trim() ? { entity_id: filters.entityId.trim() } : {}),
    ...(filters.actor ? { actor: filters.actor } : {}),
    ...(filters.action ? { action: filters.action } : {}),
    ...(filters.from ? { since: `${filters.from}T00:00:00Z` } : {}),
    ...(filters.to ? { until: `${filters.to}T23:59:59Z` } : {}),
  }
}

/** True when any filter is set. */
export function hasFilters(filters: AuditFilters): boolean {
  return searchFromFilters(filters).toString() !== ''
}
