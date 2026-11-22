/**
 * TanStack Query hooks for vendors and bank changes. Keys: ['vendors', 'page', query] for the list screen,
 * ['vendors', 'detail', id] (shared with useVendor in api/reference.ts) and ['bankChanges', status].
 * Every write invalidates both prefixes, since a bank change shows on the vendor page and in the queue.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { BankChangeInput, BankChangeStatus, VendorInput } from '../api/types'
import type { apiQuery } from './listQuery'

/** GET /vendors for one set of filters. While a new filter loads, the previous rows stay on screen. */
export function useVendorsPage(query: ReturnType<typeof apiQuery>) {
  return useQuery({
    queryKey: ['vendors', 'page', query],
    queryFn: () => unwrap(api.GET('/vendors', { params: { query } })),
    placeholderData: keepPreviousData,
  })
}

/** GET /bank-changes, optionally for one status. The server scopes it to AP, finance, the controller and auditors. */
export function useBankChanges(status: BankChangeStatus | null) {
  return useQuery({
    queryKey: ['bankChanges', status],
    queryFn: () => unwrap(api.GET('/bank-changes', { params: { query: status ? { status } : {} } })),
  })
}

/** Refreshes every vendor and bank-change query after a write. */
function useInvalidateVendors() {
  const queryClient = useQueryClient()
  return () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['vendors'] }),
    queryClient.invalidateQueries({ queryKey: ['bankChanges'] }),
  ])
}

/** POST /vendors: onboard a vendor (it starts as pending review). */
export function useOnboardVendor() {
  const invalidate = useInvalidateVendors()
  return useMutation({
    mutationFn: (body: VendorInput) => unwrap(api.POST('/vendors', { body })),
    onSuccess: invalidate,
  })
}

/** POST /vendors/{id}/approve or /hold, with an optional comment. */
export function useVendorDecision(vendorId: string, action: 'approve' | 'hold') {
  const invalidate = useInvalidateVendors()
  return useMutation({
    mutationFn: (comment: string | null) => {
      const params = { path: { vendor_id: vendorId } }
      return unwrap(action === 'approve'
        ? api.POST('/vendors/{vendor_id}/approve', { params, body: { comment } })
        : api.POST('/vendors/{vendor_id}/hold', { params, body: { comment } }))
    },
    onSuccess: invalidate,
  })
}

/** POST /vendors/{id}/bank-changes: ask for new bank details (verified later by someone else). */
export function useRequestBankChange(vendorId: string) {
  const invalidate = useInvalidateVendors()
  return useMutation({
    mutationFn: (body: BankChangeInput) =>
      unwrap(api.POST('/vendors/{vendor_id}/bank-changes', { params: { path: { vendor_id: vendorId } }, body })),
    onSuccess: invalidate,
  })
}

/** POST /bank-changes/{id}/verify or /reject, with an optional comment. */
export function useBankChangeDecision(changeId: string, action: 'verify' | 'reject') {
  const invalidate = useInvalidateVendors()
  return useMutation({
    mutationFn: (comment: string | null) => {
      const params = { path: { change_id: changeId } }
      return unwrap(action === 'verify'
        ? api.POST('/bank-changes/{change_id}/verify', { params, body: { comment } })
        : api.POST('/bank-changes/{change_id}/reject', { params, body: { comment } }))
    },
    onSuccess: invalidate,
  })
}
