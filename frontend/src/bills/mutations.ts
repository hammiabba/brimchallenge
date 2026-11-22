/**
 * TanStack Query mutations for the AP review of one bill. Every write answers with the bill's new detail (with the
 * controls run the write triggered), which goes straight into ['bills', 'detail', id]; then every bills query is
 * refreshed, since the bill's flags, status or queue may have changed. Each write sends the bill's row_version, so a
 * bill changed by someone else in the meantime is refused (409) instead of overwritten.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { components } from '../api/schema'
import type { BillDetail } from '../api/types'

type Schemas = components['schemas']

/** Stores the bill a write returned and refreshes every bills query. */
function useApplyBill() {
  const queryClient = useQueryClient()
  return (bill: BillDetail) => {
    queryClient.setQueryData(['bills', 'detail', bill.bill_id], bill)
    return queryClient.invalidateQueries({ queryKey: ['bills'] })
  }
}

/** PATCH /bills/{id}/lines/{line}: set a line's GL account and department (accepting or changing the suggestion). */
export function useCodeLine(bill: BillDetail, lineNo: number) {
  const apply = useApplyBill()
  return useMutation({
    mutationFn: (coding: { gl_account: string; department_id: string }) => unwrap(api.PATCH('/bills/{bill_id}/lines/{line_no}', {
      params: { path: { bill_id: bill.bill_id, line_no: lineNo } },
      body: { row_version: bill.row_version, ...coding },
    })),
    onSuccess: apply,
  })
}

/** The header fields AP can change (PATCH /bills/{id}), without the row version the hook adds. */
export type HeaderChanges = Omit<Schemas['BillHeaderPatch'], 'row_version'>

/**
 * PATCH /bills/{id}: change header fields (only the ones given). The server re-checks the extraction confidence and
 * re-runs the controls, and records who changed what. Setting the department, even to the same value, confirms it.
 */
export function useEditBill(bill: BillDetail) {
  const apply = useApplyBill()
  return useMutation({
    mutationFn: (changes: HeaderChanges) => unwrap(api.PATCH('/bills/{bill_id}', {
      params: { path: { bill_id: bill.bill_id } },
      body: { row_version: bill.row_version, ...changes },
    })),
    onSuccess: apply,
  })
}
