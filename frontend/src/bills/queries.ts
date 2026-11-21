/** TanStack Query hooks for bills, one key per resource: ['bills', 'list', query] and ['bills', 'detail', id]. */
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { apiQuery } from './listQuery'

/** GET /bills for one set of filters. While a new filter loads, the previous rows stay on screen. */
export function useBillsPage(query: ReturnType<typeof apiQuery>) {
  return useQuery({
    queryKey: ['bills', 'list', query],
    queryFn: () => unwrap(api.GET('/bills', { params: { query } })),
    placeholderData: keepPreviousData,
  })
}

/** GET /bills/{bill_id}: the one-screen detail. A 404 (missing, or outside the caller's scope) isn't retried. */
export function useBill(billId: string) {
  return useQuery({
    queryKey: ['bills', 'detail', billId],
    queryFn: () => unwrap(api.GET('/bills/{bill_id}', { params: { path: { bill_id: billId } } })),
  })
}
