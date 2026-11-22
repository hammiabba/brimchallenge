import { Anchor, Group, Pagination, Select, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import { useCallback, useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'

import { ApiError } from '../../api/errors'
import { ErrorAlert } from '../../api/ErrorAlert'
import { DateText, Id } from '../../ui/DataText'
import { EmailClassBadge } from '../common/IntakeBadges'
import { EMAIL_CLASS } from '../common/labels'
import type { EmailSummary } from '../common/types'
import { PAGE_SIZE, UNTRIAGED, apiQuery, filtersFromSearch, searchFromFilters, type InboxFilters } from './listQuery'
import { useEmails } from './queries'
import { RunPanel } from './RunPanel'

const COLUMNS = ['Email', 'From', 'Subject', 'Received', 'Class', 'Reason', 'Suggested action', 'Bills'] as const
type Column = (typeof COLUMNS)[number]
/** The columns an inbox run fills in; empty for every email that hasn't been triaged yet. */
const TRIAGE_COLUMNS: ReadonlySet<Column> = new Set(['Class', 'Reason', 'Suggested action', 'Bills'])
/**
 * Below these widths the table scrolls sideways, with a visible scrollbar (the theme's native Table.ScrollContainer).
 * Without the triage columns the four left fit the 1008 px content column at 1280 px; with them, eight columns of
 * free text need more.
 */
const MIN_WIDTH = { withTriage: 1100, withoutTriage: 700 } as const
/** GET /intake/emails for the untriaged count only: one row is enough, the total is what counts. */
const UNTRIAGED_COUNT_QUERY = { triaged: false, limit: 1, offset: 0 }
const SKELETON_ROWS = 8
const CLASS_OPTIONS = [
  ...Object.entries(EMAIL_CLASS).map(([value, style]) => ({ value, label: style.label })),
  { value: UNTRIAGED, label: 'Not triaged' },
]

/** "Showing 51 to 100 of 59 emails": the range on this page of the server's total. */
function rangeLine(page: number, shown: number, total: number): string {
  if (total === 0) return ''
  const first = (page - 1) * PAGE_SIZE + 1
  return `Showing ${first} to ${first + shown - 1} of ${total} email${total === 1 ? '' : 's'}`
}

/** One line of text, cut with an ellipsis; the full text is in the email's detail. */
function OneLine({ children }: { children: string | null | undefined }) {
  if (!children) return null
  return <Text size="sm" lineClamp={1} title={children}>{children}</Text>
}

/** One email row, with the triage cells only when the table shows those columns. */
function EmailRow({ email, showTriage }: { email: EmailSummary; showTriage: boolean }) {
  const billIds = [...new Set(email.items.flatMap((item) => (item.bill_id ? [item.bill_id] : [])))]
  return (
    <Table.Tr>
      <Table.Td>
        <Anchor component={Link} to={`/inbox/${email.email_id}`} underline="hover" fw={500}>
          <Id>{email.email_id}</Id>
        </Anchor>
      </Table.Td>
      <Table.Td maw={220}>
        <Text size="sm" lineClamp={1}>{email.from_name ?? email.from_address}</Text>
        {email.from_name && <Text size="xs" c="dimmed" lineClamp={1}>{email.from_address}</Text>}
      </Table.Td>
      <Table.Td maw={280}><OneLine>{email.subject}</OneLine></Table.Td>
      <Table.Td><DateText value={email.received_at} kind="timestamp" /></Table.Td>
      {showTriage && (
        <>
          <Table.Td><EmailClassBadge emailClass={email.email_class} /></Table.Td>
          <Table.Td maw={260}><OneLine>{email.triage_reason}</OneLine></Table.Td>
          <Table.Td maw={260}><OneLine>{email.suggested_action?.message}</OneLine></Table.Td>
          <Table.Td>
            <Stack gap={2}>
              {billIds.map((billId) => (
                <Anchor key={billId} component={Link} to={`/bills/${billId}`} underline="hover"><Id>{billId}</Id></Anchor>
              ))}
            </Stack>
          </Table.Td>
        </>
      )}
    </Table.Tr>
  )
}

/** "59 emails not triaged yet. Run the inbox to sort them." */
function untriagedLine(count: number): string {
  return `${count} email${count === 1 ? '' : 's'} not triaged yet. Run the inbox to sort them.`
}

/**
 * /inbox: run the AP inbox and see what happened to every email (GET /intake/emails): its class, why, the suggested
 * next step and the bills made from it. The class filter, page and the run being followed are in the URL.
 */
export default function InboxPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(() => filtersFromSearch(searchParams), [searchParams])
  const query = useMemo(() => apiQuery(filters), [filters])
  const emails = useEmails(query)
  const untriaged = useEmails(UNTRIAGED_COUNT_QUERY)

  const setFilters = useCallback(
    (next: InboxFilters) => setSearchParams(searchFromFilters(next), { replace: true }),
    [setSearchParams],
  )
  const onJob = useCallback((jobId: string) => setFilters({ ...filters, jobId }), [filters, setFilters])

  // A 403 on the list means this role can't use the inbox at all: show only the server's answer.
  const forbidden = emails.error instanceof ApiError && emails.error.status === 403
  const total = emails.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const loading = emails.isPending
  const untriagedCount = untriaged.data?.total ?? 0
  // Until an inbox run sorts them, the class, reason, suggested action and bills are empty for every email: while no
  // email on this page has been triaged, those columns are left out (and the line above the table says why).
  const items = emails.data?.items
  const showTriage = !items || items.length === 0 || items.some((email) => email.email_class != null)
  const columns = COLUMNS.filter((column) => showTriage || !TRIAGE_COLUMNS.has(column))

  return (
    <Stack gap="md">
      <Title order={1}>Inbox</Title>
      {!forbidden && <RunPanel jobId={filters.jobId} onJob={onJob} />}
      {!forbidden && (
        <Group gap="sm" align="flex-end">
          <Select
            label="Class"
            placeholder="Any class"
            data={CLASS_OPTIONS}
            value={filters.emailClass}
            onChange={(value) => setFilters({ ...filters, emailClass: value, page: 1 })}
            clearable
            w={240}
          />
        </Group>
      )}
      {!forbidden && untriagedCount > 0 && <Text size="sm">{untriagedLine(untriagedCount)}</Text>}
      {emails.isError && !emails.data ? (
        <ErrorAlert error={emails.error} title="Can't load the inbox" onRetry={forbidden ? undefined : () => void emails.refetch()} />
      ) : (
        <>
          <Table.ScrollContainer minWidth={showTriage ? MIN_WIDTH.withTriage : MIN_WIDTH.withoutTriage}>
            <Table aria-label="Inbox emails" bg="white" withTableBorder>
              <Table.Thead>
                <Table.Tr>{columns.map((column) => <Table.Th key={column}>{column}</Table.Th>)}</Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {loading && Array.from({ length: SKELETON_ROWS }, (_, row) => (
                  <Table.Tr key={`skeleton-${row}`} aria-hidden>
                    {columns.map((column) => <Table.Td key={column}><Skeleton animate={false} height={12} /></Table.Td>)}
                  </Table.Tr>
                ))}
                {!loading && emails.data?.items.length === 0 && (
                  <Table.Tr>
                    <Table.Td colSpan={columns.length}>
                      <Text size="sm" c="dimmed" py="xs">
                        {filters.emailClass ? 'No emails match this filter.' : 'The inbox is empty.'}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                )}
                {!loading && emails.data?.items.map((email) => (
                  <EmailRow key={email.email_id} email={email} showTriage={showTriage} />
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Group justify="space-between">
            <Text size="sm" c="dimmed">{rangeLine(filters.page, emails.data?.items.length ?? 0, total)}</Text>
            {pages > 1 && (
              <Pagination
                total={pages}
                value={Math.min(filters.page, pages)}
                onChange={(page) => setSearchParams(searchFromFilters({ ...filters, page }))}
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
