/**
 * The vendor list's filters live in the URL query string, like the bills list:
 *   ?status=pending_review&q=cartage&page=2
 * They map one to one onto what GET /vendors supports server-side: status (repeatable), q (name or vendor id),
 * limit and offset. The server sorts (vendor id).
 */
import type { VendorStatus } from '../api/types'
import { VENDOR_STATUS } from '../ui/statusStyles'

export const PAGE_SIZE = 50

export interface VendorListFilters {
  status: VendorStatus[]
  q: string
  /** 1-based page number. */
  page: number
}

/** True for a value the API accepts as a vendor status. */
function isVendorStatus(value: string): value is VendorStatus {
  return Object.hasOwn(VENDOR_STATUS, value)
}

/** The filters in a URL query string; unknown statuses and a bad page number are ignored. */
export function filtersFromSearch(search: URLSearchParams): VendorListFilters {
  // Page is a small integer from the URL (not money), so parseInt is fine.
  const page = Number.parseInt(search.get('page') ?? '1', 10)
  return {
    status: [...new Set(search.getAll('status').filter(isVendorStatus))],
    q: search.get('q') ?? '',
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  }
}

/** The URL query string for some filters; defaults (no filter, page 1) are left out. */
export function searchFromFilters(filters: VendorListFilters): URLSearchParams {
  const search = new URLSearchParams()
  for (const status of filters.status) search.append('status', status)
  if (filters.q.trim()) search.set('q', filters.q.trim())
  if (filters.page > 1) search.set('page', String(filters.page))
  return search
}

/** The GET /vendors query for some filters. */
export function apiQuery(filters: VendorListFilters) {
  return {
    ...(filters.status.length > 0 ? { status: filters.status } : {}),
    ...(filters.q.trim() ? { q: filters.q.trim() } : {}),
    limit: PAGE_SIZE,
    offset: (filters.page - 1) * PAGE_SIZE,
  }
}
