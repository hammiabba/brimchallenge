/** TanStack Query hook for the bank reconciliation. Key: ['reconciliation', 'bank', onlyIssues]. */
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'

/**
 * GET /reconciliation/bank: every statement line matched to its payment or explained (controls.reconciliation).
 * With onlyIssues, the lines and payments are cut to the ones someone has to act on; the summary always covers
 * the whole statement. While the other view loads, the previous one stays on screen.
 */
export function useBankReconciliation(onlyIssues: boolean) {
  return useQuery({
    queryKey: ['reconciliation', 'bank', onlyIssues],
    queryFn: () => unwrap(api.GET('/reconciliation/bank', { params: { query: { only_issues: onlyIssues } } })),
    placeholderData: keepPreviousData,
  })
}
