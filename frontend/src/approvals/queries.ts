/**
 * TanStack Query hooks for approvals. Keys stay under the bills prefix: ['bills', 'approvals'] for the signed-in
 * user's queue and ['bills', 'unassigned'] for steps with no approver. Every decision or assignment answers with the
 * bill's new detail, which goes straight into ['bills', 'detail', id]; then every bills query is refreshed, since the
 * bill leaves one queue and may enter another.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { BillDetail, BillSummary } from '../api/types'

/** The largest page GET /bills serves. */
const MAX_PAGE = 200

/** GET /approvals/queue: bills whose current step is assigned to the signed-in user, delegated steps included. */
export function useApprovalQueue() {
  return useQuery({
    queryKey: ['bills', 'approvals'],
    queryFn: () => unwrap(api.GET('/approvals/queue')),
  })
}

/**
 * Pending bills whose current step has no approver (routing found nobody eligible to sign). The API has no filter for
 * this yet, so every pending bill is read (page by page) and the unassigned ones are kept, in the server's order.
 */
export function useUnassignedSteps() {
  return useQuery({
    queryKey: ['bills', 'unassigned'],
    queryFn: async () => {
      const pending: BillSummary[] = []
      for (let offset = 0; ; offset += MAX_PAGE) {
        const page = await unwrap(api.GET('/bills', {
          params: { query: { status: ['pending_approval'], limit: MAX_PAGE, offset } },
        }))
        pending.push(...page.items)
        if (page.items.length === 0 || offset + page.items.length >= page.total) break
      }
      return pending.filter((bill) => bill.current_step && !bill.current_step.user_id)
    },
  })
}

/** Stores the bill a write returned and refreshes every bills query. */
function useApplyBill() {
  const queryClient = useQueryClient()
  return (bill: BillDetail) => {
    queryClient.setQueryData(['bills', 'detail', bill.bill_id], bill)
    return queryClient.invalidateQueries({ queryKey: ['bills'] })
  }
}

/**
 * POST /bills/{id}/approve or /reject for the bill at `rowVersion`, with a comment (required to reject; the server
 * refuses an empty one). The server checks the permission again (can_approve), so a refusal comes back as an error.
 */
export function useBillDecision(billId: string, rowVersion: number, decision: 'approve' | 'reject') {
  const apply = useApplyBill()
  return useMutation({
    mutationFn: (comment: string | null) => {
      const params = { path: { bill_id: billId } }
      return unwrap(decision === 'approve'
        ? api.POST('/bills/{bill_id}/approve', { params, body: { row_version: rowVersion, comment } })
        : api.POST('/bills/{bill_id}/reject', { params, body: { row_version: rowVersion, comment: comment ?? '' } }))
    },
    onSuccess: apply,
  })
}

/** POST /bills/{id}/route/{step}/assign: name who signs a step that has no approver. */
export function useAssignStep(billId: string, stepNo: number, rowVersion: number) {
  const apply = useApplyBill()
  return useMutation({
    mutationFn: (userId: string) => unwrap(api.POST('/bills/{bill_id}/route/{step_no}/assign', {
      params: { path: { bill_id: billId, step_no: stepNo } },
      body: { row_version: rowVersion, user_id: userId },
    })),
    onSuccess: apply,
  })
}
