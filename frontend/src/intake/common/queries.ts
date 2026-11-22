/**
 * TanStack Query hooks for the signed-in user's own submissions (['intake', 'submissions']) and the bills they are
 * the requester on.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { api, unwrap } from '../../api/client'
import { isFinalStatus } from './labels'
import type { IntakeItem } from './types'

export const SUBMISSIONS_KEY = ['intake', 'submissions'] as const

/** How often a list with queued or processing files is asked again. */
export const POLL_MS = 2_000

/** True while any file is still queued or processing. */
export function hasPending(items: readonly IntakeItem[] | undefined): boolean {
  return (items ?? []).some((item) => !isFinalStatus(item.status))
}

/**
 * GET /submissions: every file the signed-in user submitted, newest first. While one is queued or processing the
 * list is asked again every POLL_MS; it stops once all are final. TanStack Query skips intervals while the tab is
 * hidden (refetchIntervalInBackground is off).
 */
export function useMySubmissions(enabled = true) {
  return useQuery({
    queryKey: SUBMISSIONS_KEY,
    queryFn: () => unwrap(api.GET('/submissions')),
    enabled,
    refetchInterval: (query) => (hasPending(query.state.data) ? POLL_MS : false),
  })
}

/** How many of the user's requested bills one page of "Bills where you're the requester" shows. */
export const REQUESTED_PAGE_SIZE = 20

/**
 * GET /bills?mine=true: the bills where the signed-in user is the requester (including ones AP created for them
 * from an emailed invoice), newest first, one page at a time. Shares the ['bills', 'list'] key prefix, so the cache
 * is refreshed whenever bills change.
 */
export function useMyRequestedBills(page: number) {
  const query = { mine: true, limit: REQUESTED_PAGE_SIZE, offset: (page - 1) * REQUESTED_PAGE_SIZE }
  return useQuery({
    queryKey: ['bills', 'list', query],
    queryFn: () => unwrap(api.GET('/bills', { params: { query } })),
    placeholderData: keepPreviousData,
  })
}

/** POST /submissions with one file as multipart form data (field "file"). Resolves to the queued item. */
export function submitFile(file: File): Promise<IntakeItem> {
  const form = new FormData()
  form.append('file', file, file.name)
  return unwrap(api.POST('/submissions', {
    body: { file: file.name },
    bodySerializer: () => form,
  }))
}

const ALREADY_RECEIVED = 'already_received'

/** The bill this exact file was already received as, when intake linked it to an existing bill instead of a new one. */
export function alreadyReceivedBill(item: IntakeItem): string | null {
  return item.bill_id && item.warnings.some((w) => w.startsWith(ALREADY_RECEIVED)) ? item.bill_id : null
}
