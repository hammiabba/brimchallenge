/**
 * The bills list's filters live in the URL query string, so a filtered view can be shared or bookmarked:
 *   ?status=needs_review&status=on_hold&vendor=V011&department=D01&q=000804&page=2
 * They map one to one onto what GET /bills supports server-side: status (repeatable), vendor_id, department_id,
 * q (bill id, invoice number or vendor name), limit and offset. The server sorts (received date, newest first).
 */
import type { BillStatus } from '../api/types'
import { BILL_STATUS } from '../ui/statusStyles'

export const PAGE_SIZE = 50

/** The statuses the review queue shows: the bills waiting for AP. */
export const REVIEW_STATUSES: readonly BillStatus[] = ['needs_review', 'on_hold']

export interface BillListFilters {
  status: BillStatus[]
  vendorId: string | null
  departmentId: string | null
  q: string
  /** 1-based page number. */
  page: number
}

/** True for a value the API accepts as a bill status. */
function isBillStatus(value: string): value is BillStatus {
  return Object.hasOwn(BILL_STATUS, value)
}

/** The filters in a URL query string; unknown statuses and a bad page number are ignored. */
export function filtersFromSearch(search: URLSearchParams): BillListFilters {
  // Page is a small integer from the URL (not money), so parseInt is fine.
  const page = Number.parseInt(search.get('page') ?? '1', 10)
  return {
    status: [...new Set(search.getAll('status').filter(isBillStatus))],
    vendorId: search.get('vendor') || null,
    departmentId: search.get('department') || null,
    q: search.get('q') ?? '',
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  }
}

/** The URL query string for some filters; defaults (no filter, page 1) are left out. */
export function searchFromFilters(filters: BillListFilters): URLSearchParams {
  const search = new URLSearchParams()
  for (const status of filters.status) search.append('status', status)
  if (filters.vendorId) search.set('vendor', filters.vendorId)
  if (filters.departmentId) search.set('department', filters.departmentId)
  if (filters.q.trim()) search.set('q', filters.q.trim())
  if (filters.page > 1) search.set('page', String(filters.page))
  return search
}

/** The GET /bills query for some filters. `fixedStatus` (the review queue) replaces the status filter. */
export function apiQuery(filters: BillListFilters, fixedStatus?: readonly BillStatus[]) {
  const status = fixedStatus ? [...fixedStatus] : filters.status
  return {
    ...(status.length > 0 ? { status } : {}),
    ...(filters.vendorId ? { vendor_id: filters.vendorId } : {}),
    ...(filters.departmentId ? { department_id: filters.departmentId } : {}),
    ...(filters.q.trim() ? { q: filters.q.trim() } : {}),
    limit: PAGE_SIZE,
    offset: (filters.page - 1) * PAGE_SIZE,
  }
}
