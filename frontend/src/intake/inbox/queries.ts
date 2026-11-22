/**
 * TanStack Query hooks for the AP inbox: ['intake', 'emails', query], ['intake', 'email', id] and
 * ['intake', 'job', id]. An inbox run is a background job on the server: POST starts it (202) and GET is polled
 * for progress until it is done or failed.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { api, unwrap } from '../../api/client'
import type { InboxJob } from '../common/types'
import type { apiQuery } from './listQuery'

export const EMAILS_KEY = ['intake', 'emails'] as const

/** How often a running inbox job is asked for progress. */
export const JOB_POLL_MS = 1_000

/** True while a job may still change. */
export function isJobActive(job: InboxJob | undefined): boolean {
  return job?.status === 'queued' || job?.status === 'running'
}

/** GET /intake/emails for one filter and page. While a new page loads, the previous rows stay on screen. */
export function useEmails(query: ReturnType<typeof apiQuery>) {
  return useQuery({
    queryKey: [...EMAILS_KEY, query],
    queryFn: () => unwrap(api.GET('/intake/emails', { params: { query } })),
    placeholderData: keepPreviousData,
  })
}

/** GET /intake/emails/{email_id}: one email with its triage, suggested action, files and bills. */
export function useEmail(emailId: string) {
  return useQuery({
    queryKey: ['intake', 'email', emailId],
    queryFn: () => unwrap(api.GET('/intake/emails/{email_id}', { params: { path: { email_id: emailId } } })),
  })
}

/** GET /intake/inbox/jobs/{job_id}, polled every JOB_POLL_MS while the run is queued or running. */
export function useInboxJob(jobId: string | null) {
  return useQuery({
    queryKey: ['intake', 'job', jobId],
    queryFn: () => unwrap(api.GET('/intake/inbox/jobs/{job_id}', { params: { path: { job_id: jobId ?? '' } } })),
    enabled: jobId !== null,
    staleTime: 0,
    refetchInterval: (query) => (isJobActive(query.state.data) ? JOB_POLL_MS : false),
  })
}

/** POST /intake/inbox/jobs: starts a run. A run already going is a 409 (intake.job_running) naming its job id. */
export function startInboxJob(): Promise<InboxJob> {
  return unwrap(api.POST('/intake/inbox/jobs'))
}
