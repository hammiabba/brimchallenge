import { describe, expect, it } from 'vitest'

import { PAGE_SIZE, apiQuery, filtersFromSearch, searchFromFilters } from './listQuery'

describe('bills list query', () => {
  it('reads filters from the URL, ignoring unknown statuses and bad page numbers', () => {
    const filters = filtersFromSearch(new URLSearchParams(
      'status=needs_review&status=bogus&status=on_hold&status=needs_review&vendor=V011&department=D01&q=000804&page=x'))
    expect(filters).toEqual({
      status: ['needs_review', 'on_hold'], vendorId: 'V011', departmentId: 'D01', q: '000804', page: 1,
    })
  })

  it('writes only the filters that are set', () => {
    const empty = { status: [], vendorId: null, departmentId: null, q: '', page: 1 }
    expect(searchFromFilters(empty).toString()).toBe('')
    expect(searchFromFilters({ ...empty, status: ['paid', 'void'], q: ' acme ', page: 3 }).toString())
      .toBe('status=paid&status=void&q=acme&page=3')
  })

  it('round-trips through the URL', () => {
    const filters = { status: ['approved' as const], vendorId: 'V004', departmentId: 'D02', q: 'AP-004', page: 2 }
    expect(filtersFromSearch(searchFromFilters(filters))).toEqual(filters)
  })

  it('maps onto the parameters GET /bills supports, with offset paging', () => {
    const filters = { status: ['paid' as const], vendorId: 'V011', departmentId: null, q: '', page: 3 }
    expect(apiQuery(filters)).toEqual({ status: ['paid'], vendor_id: 'V011', limit: PAGE_SIZE, offset: 2 * PAGE_SIZE })
  })

  it('uses the fixed statuses for the review queue', () => {
    const filters = { status: ['paid' as const], vendorId: null, departmentId: null, q: '', page: 1 }
    expect(apiQuery(filters, ['needs_review', 'on_hold'])).toEqual({
      status: ['needs_review', 'on_hold'], limit: PAGE_SIZE, offset: 0,
    })
  })
})
