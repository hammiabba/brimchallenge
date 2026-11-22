/**
 * TanStack Query hooks for intake: submissions, the inbox job and the triaged emails. Keys: ['intake', 'submissions'],
 * ['intake', 'job', id] and ['intake', 'emails', query]. Work happens in the background on the server, so the
 * screens poll while something is still queued or running.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from '../api/client'
import { isPending } from './status'

/** How often a screen asks again while the server is still working. */
export const POLL_MS = 2000

/** GET /submissions: the signed-in user's own submissions, polled while any is queued or processing. */
export function useMySubmissions() {
  return useQuery({
    queryKey: ['intake', 'submissions'],
    queryFn: () => unwrap(api.GET('/submissions')),
    refetchInterval: (query) => (query.state.data?.some((item) => isPending(item.status)) ? POLL_MS : false),
  })
}

/** POST /submissions: upload one invoice file, optionally for a department. Returns the queued item (202). */
export function useSubmitInvoice() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ file, departmentId }: { file: File; departmentId: string | null }) =>
      unwrap(api.POST('/submissions', {
        body: { file: file as unknown as string, department_id: departmentId },
        bodySerializer: () => {
          const form = new FormData()
          form.append('file', file)
          if (departmentId) form.append('department_id', departmentId)
          return form
        },
      })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['intake', 'submissions'] }),
  })
}

/** POST /intake/inbox/jobs: start processing the AP inbox. Returns the job (202) to poll. */
export function useStartInboxJob() {
  return useMutation({ mutationFn: () => unwrap(api.POST('/intake/inbox/jobs')) })
}

/** GET /intake/inbox/jobs/{id}, polled until the job is done or failed. Disabled without an id. */
export function useInboxJob(jobId: string | null) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: ['intake', 'job', jobId],
    queryFn: async () => {
      const job = await unwrap(api.GET('/intake/inbox/jobs/{job_id}', { params: { path: { job_id: jobId ?? '' } } }))
      // New triage results arrive as the job works: refresh the email list alongside.
      await queryClient.invalidateQueries({ queryKey: ['intake', 'emails'] })
      return job
    },
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'done' || status === 'failed' ? false : POLL_MS
    },
  })
}

export interface EmailQuery {
  email_class?: string
  triaged?: boolean
  limit: number
  offset: number
}

/** GET /intake/emails: every inbox email with its class, reason and the files read from it. */
export function useEmails(query: EmailQuery) {
  return useQuery({
    queryKey: ['intake', 'emails', query],
    queryFn: () => unwrap(api.GET('/intake/emails', { params: { query } })),
    placeholderData: keepPreviousData,
  })
}
