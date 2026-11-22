/**
 * The inbox list's filter, page and the run being followed live in the URL, so a view can be shared or reloaded:
 *   ?class=payment_inquiry&page=2&job=3f2c9a1b7d0e
 * They map onto GET /intake/emails: class -> email_class ("untriaged" -> triaged=false), page -> limit/offset.
 */
import { EMAIL_CLASS } from '../common/labels'

export const PAGE_SIZE = 50

/** The filter value for emails no inbox run has sorted yet. */
export const UNTRIAGED = 'untriaged'

export interface InboxFilters {
  emailClass: string | null
  /** 1-based page number. */
  page: number
  /** The inbox run shown above the list, if any. */
  jobId: string | null
}

function isClassFilter(value: string): boolean {
  return value === UNTRIAGED || Object.hasOwn(EMAIL_CLASS, value)
}

/** The filters in a URL query string; an unknown class and a bad page number are ignored. */
export function filtersFromSearch(search: URLSearchParams): InboxFilters {
  const emailClass = search.get('class') ?? ''
  // Page is a small integer from the URL (not money), so parseInt is fine.
  const page = Number.parseInt(search.get('page') ?? '1', 10)
  return {
    emailClass: isClassFilter(emailClass) ? emailClass : null,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    jobId: search.get('job') || null,
  }
}

/** The URL query string for some filters; defaults are left out. */
export function searchFromFilters(filters: InboxFilters): URLSearchParams {
  const search = new URLSearchParams()
  if (filters.emailClass) search.set('class', filters.emailClass)
  if (filters.page > 1) search.set('page', String(filters.page))
  if (filters.jobId) search.set('job', filters.jobId)
  return search
}

/** The GET /intake/emails query for some filters. */
export function apiQuery(filters: InboxFilters) {
  return {
    ...(filters.emailClass === UNTRIAGED ? { triaged: false } : {}),
    ...(filters.emailClass && filters.emailClass !== UNTRIAGED ? { email_class: filters.emailClass } : {}),
    limit: PAGE_SIZE,
    offset: (filters.page - 1) * PAGE_SIZE,
  }
}
