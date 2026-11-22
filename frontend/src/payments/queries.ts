/**
 * TanStack Query hooks for payments. Keys: ['payments', 'summary'] for the dashboard totals, ['payments', 'page', query]
 * for one page of the list and ['payments', 'detail', id] for one payment. Approved bills waiting to be scheduled are
 * a bills list, so they live under ['bills', 'list', query] like every other bills list.
 *
 * Every write answers with the payment's new detail, which goes straight into its detail key; then payments and bills
 * are refreshed, since scheduling, releasing or cancelling also changes the bill's status.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import type { PaymentDetail, PaymentStatus, PaymentsPage, ScheduleInput } from '../api/types'

/** Rows per page on the payments list (GET /payments serves up to 200). */
export const PAYMENTS_PAGE_SIZE = 50

/** GET /payments/summary: totals by status, due in the next 7 days and overdue, as of the business date. */
export function usePaymentsSummary() {
  return useQuery({
    queryKey: ['payments', 'summary'],
    queryFn: () => unwrap(api.GET('/payments/summary')),
  })
}

/** GET /payments for some statuses (all when empty), one page at a time, newest scheduled date first. */
export function usePaymentsPage(statuses: readonly PaymentStatus[], page: number) {
  const query = {
    ...(statuses.length > 0 ? { status: [...statuses] } : {}),
    limit: PAYMENTS_PAGE_SIZE,
    offset: (page - 1) * PAYMENTS_PAGE_SIZE,
  }
  return useQuery<PaymentsPage>({
    queryKey: ['payments', 'page', query],
    queryFn: () => unwrap(api.GET('/payments', { params: { query } })),
    placeholderData: keepPreviousData,
  })
}

/** GET /payments/{id}: the payment with its bill, approval chain, coding, audit and allowed_actions. */
export function usePayment(paymentId: string) {
  return useQuery({
    queryKey: ['payments', 'detail', paymentId],
    queryFn: () => unwrap(api.GET('/payments/{payment_id}', { params: { path: { payment_id: paymentId } } })),
  })
}

/** GET /bills?status=approved: bills approved and not yet scheduled for payment (up to 200, the server's order). */
export function useApprovedBills() {
  const query = { status: ['approved' as const], limit: 200 }
  return useQuery({
    queryKey: ['bills', 'list', query],
    queryFn: () => unwrap(api.GET('/bills', { params: { query } })),
  })
}

/** Stores the payment a write returned and refreshes every payments and bills query. */
function useApplyPayment() {
  const queryClient = useQueryClient()
  return (payment: PaymentDetail) => {
    queryClient.setQueryData(['payments', 'detail', payment.payment_id], payment)
    return Promise.all([
      queryClient.invalidateQueries({ queryKey: ['payments'] }),
      queryClient.invalidateQueries({ queryKey: ['bills'] }),
    ])
  }
}

/** POST /bills/{id}/payments: AP prepares the payment of an approved bill (method and date). */
export function useSchedulePayment(billId: string) {
  const apply = useApplyPayment()
  return useMutation({
    mutationFn: (body: ScheduleInput) =>
      unwrap(api.POST('/bills/{bill_id}/payments', { params: { path: { bill_id: billId } }, body })),
    onSuccess: apply,
  })
}

/**
 * POST /payments/{id}/release with an Idempotency-Key. The caller passes the same key when it retries the same
 * attempt, so a release that reached the server but lost its answer is never paid twice.
 */
export function useReleasePayment(paymentId: string) {
  const apply = useApplyPayment()
  return useMutation({
    mutationFn: (idempotencyKey: string) => unwrap(api.POST('/payments/{payment_id}/release', {
      params: { path: { payment_id: paymentId }, header: { 'Idempotency-Key': idempotencyKey } },
    })),
    onSuccess: apply,
  })
}

/** POST /payments/{id}/cancel with an optional comment: the bill goes back to approved. */
export function useCancelPayment(paymentId: string) {
  const apply = useApplyPayment()
  return useMutation({
    mutationFn: (comment: string | null) => unwrap(api.POST('/payments/{payment_id}/cancel', {
      params: { path: { payment_id: paymentId } }, body: { comment },
    })),
    onSuccess: apply,
  })
}

/** A new Idempotency-Key for one release attempt ("release-" and a random UUID, as the API's pattern allows). */
export function newIdempotencyKey(): string {
  return `release-${crypto.randomUUID()}`
}
