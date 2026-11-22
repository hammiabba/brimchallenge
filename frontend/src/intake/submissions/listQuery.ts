/**
 * My submissions' filter and page live in the URL (?status=failed&page=2), as on the bills list. GET /submissions
 * has no filter or paging parameters yet (it returns all of the user's own files, newest first), so both are applied
 * to that list here. When the API adds them, apiQuery-style mapping replaces filterItems/pageOf.
 */
import { INTAKE_STATUS } from '../common/labels'
import type { IntakeItem, IntakeItemStatus } from '../common/types'

export const PAGE_SIZE = 50

export interface SubmissionFilters {
  status: IntakeItemStatus | null
  /** 1-based page number. */
  page: number
}

function isIntakeStatus(value: string): value is IntakeItemStatus {
  return Object.hasOwn(INTAKE_STATUS, value)
}

/** The filters in a URL query string; an unknown status and a bad page number are ignored. */
export function filtersFromSearch(search: URLSearchParams): SubmissionFilters {
  const status = search.get('status') ?? ''
  // Page is a small integer from the URL (not money), so parseInt is fine.
  const page = Number.parseInt(search.get('page') ?? '1', 10)
  return {
    status: isIntakeStatus(status) ? status : null,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  }
}

/** The URL query string for some filters; defaults are left out. */
export function searchFromFilters(filters: SubmissionFilters): URLSearchParams {
  const search = new URLSearchParams()
  if (filters.status) search.set('status', filters.status)
  if (filters.page > 1) search.set('page', String(filters.page))
  return search
}

/** The items with the chosen status, in the server's order. */
export function filterItems(items: readonly IntakeItem[], filters: SubmissionFilters): IntakeItem[] {
  return filters.status ? items.filter((item) => item.status === filters.status) : [...items]
}

/** One page of a list. */
export function pageOf<T>(items: readonly T[], page: number): T[] {
  return items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
}
