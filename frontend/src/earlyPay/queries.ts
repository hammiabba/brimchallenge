/** TanStack Query hook for early-payment discounts. Key: ['earlyPay', includePending]. */
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'

/**
 * GET /early-pay: the best pay date and saving for approved and scheduled bills (controls.early_pay), plus the
 * discounts the history took and missed. includePending adds bills still in review or awaiting approval.
 */
export function useEarlyPay(includePending: boolean) {
  return useQuery({
    queryKey: ['earlyPay', includePending],
    queryFn: () => unwrap(api.GET('/early-pay', { params: { query: { include_pending: includePending } } })),
    placeholderData: keepPreviousData,
  })
}
