import { Button, Group, Pagination, Progress, Select, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import { IconPlayerPlay } from '@tabler/icons-react'
import { useMemo } from 'react'
import { useSearchParams } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import { personName, usePeople } from '../api/reference'
import type { InboxEmail, InboxJob } from '../api/types'
import { DateText } from '../ui/DataText'
import { Icon } from '../ui/Icon'
import { IntakeStatusBadge } from './IntakeStatusBadge'
import { BillLink, ItemNotes } from './ItemCells'
import { useEmails, useInboxJob, useStartInboxJob, type EmailQuery } from './queries'
import { isPending } from './status'

const PAGE_SIZE = 25

/** The triage classes (EmailClass in backend/app/intake/classifier.py) in words. */
const CLASS_LABELS: Record<string, string> = {
  invoice: 'Invoice',
  credit_note: 'Credit note',
  statement: 'Statement',
  payment_inquiry: 'Payment inquiry',
  missing_attachment: 'Missing attachment',
  not_ap: 'Not for AP',
}
/** The class filter: every class, plus emails the inbox hasn't triaged yet. */
const UNTRIAGED = 'untriaged'
const CLASS_OPTIONS = [
  ...Object.entries(CLASS_LABELS).map(([value, label]) => ({ value, label })),
  { value: UNTRIAGED, label: 'Not triaged yet' },
]

const JOB_STATUS_LABELS: Record<InboxJob['status'], string> = {
  queued: 'Queued',
  running: 'Running',
  done: 'Finished',
  failed: 'Failed',
}

/** The running or last inbox job: progress through the emails, who started it, and its error if it failed. */
function JobPanel({ jobId }: { jobId: string }) {
  const job = useInboxJob(jobId)
  const people = usePeople()
  if (job.isPending) return <Skeleton animate={false} height={56} />
  if (job.isError) return <ErrorAlert error={job.error} title="Can't load the inbox run" onRetry={() => void job.refetch()} />

  const { status, processed_emails: processed = 0, total_emails: total = 0 } = job.data
  // Email counts, not money: plain integer arithmetic is fine.
  const percent = total > 0 ? Math.round((processed / total) * 100) : status === 'done' ? 100 : 0
  return (
    <Stack gap={6} aria-label="Inbox run" role="region">
      <Group justify="space-between">
        <Text size="sm" fw={600}>{`Inbox run: ${JOB_STATUS_LABELS[status]}`}</Text>
        <Text size="sm">{`${processed} of ${total} emails`}</Text>
      </Group>
      <Progress value={percent} aria-label={`${processed} of ${total} emails processed`} />
      <Text size="xs" c="dimmed">
        {`Started by ${personName(job.data.started_by, people.data)} `}
        <DateText value={job.data.started_at} kind="timestamp" />
      </Text>
      {status === 'failed' && job.data.error && <Text size="sm">{job.data.error}</Text>}
    </Stack>
  )
}

/** The files read from one email: name, status, the bill it became and any note. */
function EmailFiles({ email }: { email: InboxEmail }) {
  const items = email.items ?? []
  if (items.length === 0) {
    return <Text size="sm" c="dimmed">{email.attachments.length === 0 ? 'No attachments' : `${email.attachments.length} not read`}</Text>
  }
  return (
    <Stack gap={6}>
      {items.map((item) => (
        <Stack key={item.item_id} gap={2}>
          <Group gap="xs" wrap="nowrap">
            <Text size="sm">{item.file_name}</Text>
            <IntakeStatusBadge status={item.status} />
            <BillLink billId={item.bill_id} pending={isPending(item.status)} />
          </Group>
          <ItemNotes item={item} />
        </Stack>
      ))}
    </Stack>
  )
}

const COLUMNS = ['Received', 'From', 'Subject', 'Class', 'Why', 'Files'] as const

function EmailsTable({ emails, loading, emptyMessage }: { emails: readonly InboxEmail[] | undefined; loading: boolean; emptyMessage: string }) {
  return (
    <Table.ScrollContainer minWidth={1100}>
      <Table aria-label="Inbox emails" bg="white" withTableBorder verticalSpacing="sm">
        <Table.Thead>
          <Table.Tr>{COLUMNS.map((column) => <Table.Th key={column}>{column}</Table.Th>)}</Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {loading && Array.from({ length: 6 }, (_, row) => (
            <Table.Tr key={`skeleton-${row}`} aria-hidden>
              {COLUMNS.map((column) => <Table.Td key={column}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>)}
            </Table.Tr>
          ))}
          {!loading && emails?.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={COLUMNS.length}><Text size="sm" c="dimmed" py="xs">{emptyMessage}</Text></Table.Td>
            </Table.Tr>
          )}
          {!loading && emails?.map((email) => (
            <Table.Tr key={email.email_id}>
              <Table.Td><DateText value={email.received_at} kind="timestamp" /></Table.Td>
              <Table.Td>
                <Stack gap={0}>
                  <Text size="sm">{email.from_name ?? email.from_address}</Text>
                  {email.from_name && <Text size="xs" c="dimmed">{email.from_address}</Text>}
                </Stack>
              </Table.Td>
              <Table.Td><Text size="sm">{email.subject}</Text></Table.Td>
              <Table.Td>
                {email.email_class
                  ? <Text size="sm" fw={500}>{CLASS_LABELS[email.email_class] ?? email.email_class}</Text>
                  : <Text size="sm" c="dimmed">Not triaged yet</Text>}
              </Table.Td>
              <Table.Td>
                <Stack gap={2}>
                  {email.triage_reason && <Text size="sm">{email.triage_reason}</Text>}
                  {email.suggested_action && <Text size="xs" c="dimmed">{email.suggested_action.message}</Text>}
                </Stack>
              </Table.Td>
              <Table.Td><EmailFiles email={email} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}

/**
 * /inbox: run the AP mailbox and follow the run. Every email is listed with its class and the reason, and the files
 * read from it, so nothing is dropped silently. The run's id stays in the URL (?job=...) so a reload keeps following it.
 * Starting a run is AP's (the server enforces it).
 */
export default function InboxPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const jobId = searchParams.get('job')
  const emailClass = searchParams.get('class')
  const pageParam = Number.parseInt(searchParams.get('page') ?? '1', 10)
  const page = Number.isInteger(pageParam) && pageParam >= 1 ? pageParam : 1
  const start = useStartInboxJob()
  const job = useInboxJob(jobId)
  const running = job.data !== undefined && (job.data.status === 'queued' || job.data.status === 'running')

  const query = useMemo<EmailQuery>(() => ({
    ...(emailClass === UNTRIAGED ? { triaged: false } : emailClass ? { email_class: emailClass } : {}),
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  }), [emailClass, page])
  const emails = useEmails(query)

  /** Changes some URL params, keeping the others; null removes one. */
  function setParams(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    setSearchParams(next, { replace: true })
  }

  const total = emails.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <Title order={1}>Inbox</Title>
        <Button
          leftSection={<Icon icon={IconPlayerPlay} />}
          loading={start.isPending}
          disabled={running}
          onClick={() => start.mutate(undefined, { onSuccess: (started) => setParams({ job: started.job_id }) })}
        >
          {running ? 'Inbox run in progress' : 'Run inbox'}
        </Button>
      </Group>
      {start.isError && <ErrorAlert error={start.error} title="Can't start the inbox run" />}
      {jobId && <JobPanel jobId={jobId} />}
      <Group gap="sm" align="flex-end">
        <Select
          label="Class"
          placeholder="Any class"
          data={CLASS_OPTIONS}
          value={emailClass}
          onChange={(value) => setParams({ class: value, page: null })}
          clearable
          w={240}
        />
      </Group>
      {emails.isError && !emails.data ? (
        <ErrorAlert error={emails.error} title="Can't load the inbox" onRetry={() => void emails.refetch()} />
      ) : (
        <>
          <EmailsTable
            emails={emails.data?.items}
            loading={emails.isPending}
            emptyMessage={emailClass ? 'No emails in this class.' : 'The inbox is empty.'}
          />
          <Group justify="space-between">
            <Text size="sm" c="dimmed">{total > 0 ? `${total} email${total === 1 ? '' : 's'}` : ''}</Text>
            {pages > 1 && (
              <Pagination
                total={pages}
                value={Math.min(page, pages)}
                onChange={(next) => setParams({ page: next > 1 ? String(next) : null })}
                size="sm"
                getControlProps={(control) => ({ 'aria-label': `${control} page` })}
              />
            )}
          </Group>
        </>
      )}
    </Stack>
  )
}
