import { Button, Group, Progress, Stack, Text } from '@mantine/core'
import { IconPlayerPlay } from '@tabler/icons-react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../../api/errors'
import type { Role } from '../../api/types'
import { useCurrentUser } from '../../auth/context'
import { ErrorAlert } from '../../api/ErrorAlert'
import { notifyError } from '../../api/notify'
import { DateText } from '../../ui/DataText'
import { Icon } from '../../ui/Icon'
import type { InboxJob } from '../common/types'
import { EMAILS_KEY, isJobActive, startInboxJob, useInboxJob } from './queries'

/** The roles that may start an inbox run, as the API's role gate decides it. */
const RUNNER_ROLES: readonly Role[] = ['ap_clerk']

/** The job id in a 409 intake.job_running answer (the run already going), if that is what the error is. */
function runningJobId(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.code !== 'intake.job_running') return null
  const details = error.details as { job_id?: unknown } | null
  return typeof details?.job_id === 'string' ? details.job_id : null
}

/** "12 of 59 emails" plus the progress bar, or the result once the run is over. */
function JobProgress({ job }: { job: InboxJob }) {
  const total = job.total_emails
  const done = job.processed_emails
  const files = job.items.length
  const unread = job.items.filter((item) => item.status === 'failed' || item.status === 'llm_skipped').length
  if (job.status === 'failed') {
    return <Text size="sm">The run stopped after {done} of {total} emails: {job.error ?? 'no reason was given.'}</Text>
  }
  if (job.status === 'done') {
    return (
      <Text size="sm">
        Run finished at <DateText value={job.finished_at ?? job.started_at} kind="timestamp" />: {done} of {total} emails,
        {` ${files} file${files === 1 ? '' : 's'} read`}{unread > 0 ? `, ${unread} could not be read` : ''}.
      </Text>
    )
  }
  const percent = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <Stack gap={6}>
      <Text size="sm">{`Processing emails: ${done} of ${total}`}</Text>
      <Progress value={percent} size="sm" aria-label={`Inbox run progress, ${done} of ${total} emails`} />
    </Stack>
  )
}

interface RunPanelProps {
  jobId: string | null
  /** Called with the run to follow (a new one, or the one already going). */
  onJob: (jobId: string) => void
}

/**
 * Starts an inbox run and follows it. POST /intake/inbox/jobs answers 202 with the new job, or 409 when a run is
 * already going (then that run is shown). The server decides who may start a run; a refusal shows its message.
 */
export function RunPanel({ jobId, onJob }: RunPanelProps) {
  const queryClient = useQueryClient()
  // Only AP starts a run (POST /intake/inbox/jobs: AP clerk); others may still follow one in progress.
  const mayRun = RUNNER_ROLES.includes(useCurrentUser().role)
  const job = useInboxJob(jobId)
  const [starting, setStarting] = useState(false)
  const [joined, setJoined] = useState(false)
  const active = isJobActive(job.data)

  // When the followed run ends, the inbox list is out of date.
  const lastStatus = useRef<string | undefined>(undefined)
  useEffect(() => {
    const status = job.data?.status
    if (status && status !== lastStatus.current && !isJobActive(job.data)) {
      void queryClient.invalidateQueries({ queryKey: EMAILS_KEY })
    }
    lastStatus.current = status
  }, [job.data, queryClient])

  async function start() {
    setStarting(true)
    try {
      const started = await startInboxJob()
      setJoined(false)
      onJob(started.job_id)
    } catch (error) {
      const running = runningJobId(error)
      if (running) {
        setJoined(true)
        onJob(running)
      } else {
        notifyError(error, "Can't start the inbox run")
      }
    } finally {
      setStarting(false)
    }
  }

  return (
    <Stack gap="sm">
      <Group gap="sm">
        {mayRun && (
          <Button leftSection={<Icon icon={IconPlayerPlay} />} onClick={() => void start()} disabled={starting || active}>
            Run inbox
          </Button>
        )}
        {joined && active && <Text size="sm">A run was already in progress, so it is shown here.</Text>}
      </Group>
      {job.data && <div aria-live="polite"><JobProgress job={job.data} /></div>}
      {job.isError && <ErrorAlert error={job.error} title="Can't follow the inbox run" onRetry={() => void job.refetch()} />}
    </Stack>
  )
}
