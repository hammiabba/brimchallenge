import { Anchor, Group, Pagination, Select, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { ErrorAlert } from '../../api/ErrorAlert'
import { useBill } from '../../bills/queries'
import { StatusBadge } from '../../ui/Badges'
import { DateText, Id, MoneyText } from '../../ui/DataText'
import { IntakeStatusBadge } from '../common/IntakeBadges'
import { INTAKE_STATUS } from '../common/labels'
import { REQUESTED_PAGE_SIZE, alreadyReceivedBill, useMyRequestedBills, useMySubmissions } from '../common/queries'
import type { IntakeItem, IntakeItemStatus } from '../common/types'
import { PAGE_SIZE, filterItems, filtersFromSearch, pageOf, searchFromFilters, type SubmissionFilters } from './listQuery'

const COLUMNS = ['File', 'Submitted', 'Status', 'Vendor', 'Total', 'Bill'] as const
const SKELETON_ROWS = 5
const STATUS_OPTIONS = Object.entries(INTAKE_STATUS).map(([value, style]) => ({ value, label: style.label }))

/** The vendor and total of the bill a file became, from GET /bills/{bill_id} (shared with the bill screen's cache). */
function BillCells({ billId }: { billId: string }) {
  const bill = useBill(billId)
  if (bill.isPending) {
    return (
      <>
        <Table.Td><Skeleton animate={false} height={12} /></Table.Td>
        <Table.Td><Skeleton animate={false} height={12} /></Table.Td>
      </>
    )
  }
  if (!bill.data) return <><Table.Td /><Table.Td /></>
  return (
    <>
      <Table.Td>{bill.data.vendor_name ?? <Text span size="sm" c="dimmed">No vendor matched</Text>}</Table.Td>
      <Table.Td data-numeric><MoneyText value={bill.data.total} currency={bill.data.currency} align="right" /></Table.Td>
    </>
  )
}

/** One submitted file. A failed or unread file shows why, in one line. */
function SubmissionRow({ item }: { item: IntakeItem }) {
  const existing = alreadyReceivedBill(item)
  const reason = item.status === 'failed' || item.status === 'llm_skipped' ? (item.error ?? 'The file could not be read.') : null
  return (
    <Table.Tr>
      <Table.Td maw={360}>
        <Text size="sm" style={{ overflowWrap: 'anywhere' }}>{item.file_name}</Text>
        {reason && <Text size="xs" c="dimmed" lineClamp={1} title={reason}>{reason}</Text>}
      </Table.Td>
      <Table.Td><DateText value={item.created_at} kind="timestamp" /></Table.Td>
      <Table.Td><IntakeStatusBadge status={item.status} /></Table.Td>
      <BillCellsWhenReady item={item} />
      <Table.Td>
        {item.bill_id && (
          <Anchor component={Link} to={`/bills/${item.bill_id}`} underline="hover" fw={500}>
            <Id>{item.bill_id}</Id>
          </Anchor>
        )}
        {existing && <Text size="xs" c="dimmed">Already received</Text>}
      </Table.Td>
    </Table.Tr>
  )
}

/** Vendor and total once the file has a bill; empty cells before. */
function BillCellsWhenReady({ item }: { item: IntakeItem }) {
  if (!item.bill_id) return <><Table.Td /><Table.Td /></>
  return <BillCells billId={item.bill_id} />
}

const REQUESTED_COLUMNS = ['Bill', 'Vendor', 'Invoice number', 'Received', 'Status', 'Total'] as const

/**
 * "Bills where you're the requester": every bill naming the signed-in user as requester (GET /bills?mine=true),
 * including the ones AP created for them from an emailed invoice, which never appear in the files table above.
 */
function RequestedBills() {
  const [page, setPage] = useState(1)
  const bills = useMyRequestedBills(page)
  const total = bills.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / REQUESTED_PAGE_SIZE))

  return (
    <Stack gap="sm">
      <Title order={2} size="h3">Bills where you're the requester</Title>
      {bills.isError && !bills.data ? (
        <ErrorAlert error={bills.error} title="Can't load your bills" onRetry={() => void bills.refetch()} />
      ) : (
        <>
          <Table.ScrollContainer minWidth={900}>
            <Table aria-label="Bills where you're the requester" bg="white" withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  {REQUESTED_COLUMNS.map((column) => (
                    <Table.Th key={column} data-numeric={column === 'Total' || undefined}>{column}</Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {bills.isPending && Array.from({ length: SKELETON_ROWS }, (_, row) => (
                  <Table.Tr key={`skeleton-${row}`} aria-hidden>
                    {REQUESTED_COLUMNS.map((column) => <Table.Td key={column}><Skeleton animate={false} height={12} /></Table.Td>)}
                  </Table.Tr>
                ))}
                {bills.data && bills.data.items.length === 0 && (
                  <Table.Tr>
                    <Table.Td colSpan={REQUESTED_COLUMNS.length}>
                      <Text size="sm" c="dimmed" py="xs">No bill names you as the requester yet.</Text>
                    </Table.Td>
                  </Table.Tr>
                )}
                {bills.data?.items.map((bill) => (
                  <Table.Tr key={bill.bill_id}>
                    <Table.Td>
                      <Anchor component={Link} to={`/bills/${bill.bill_id}`} underline="hover" fw={500}>
                        <Id>{bill.bill_id}</Id>
                      </Anchor>
                    </Table.Td>
                    <Table.Td>{bill.vendor_name ?? <Text span size="sm" c="dimmed">No vendor matched</Text>}</Table.Td>
                    <Table.Td><Id>{bill.vendor_invoice_number}</Id></Table.Td>
                    <Table.Td><DateText value={bill.received_date} /></Table.Td>
                    <Table.Td><StatusBadge kind="bill" status={bill.status} /></Table.Td>
                    <Table.Td data-numeric><MoneyText value={bill.total} currency={bill.currency} align="right" /></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {pages > 1 && (
            <Group justify="flex-end">
              <Pagination
                total={pages}
                value={Math.min(page, pages)}
                onChange={setPage}
                size="sm"
                getControlProps={(control) => ({ 'aria-label': `${control} page of your bills` })}
              />
            </Group>
          )}
        </>
      )}
    </Stack>
  )
}

/**
 * /submissions: every file the signed-in user submitted (GET /submissions, newest first), with its status and the
 * bill it became. The list is asked again every few seconds while a file is queued or processing. Below it, the bills
 * where the user is the requester (RequestedBills), so a bill AP created for them is listed too.
 */
export default function SubmissionsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(() => filtersFromSearch(searchParams), [searchParams])
  const submissions = useMySubmissions()

  const setFilters = (next: SubmissionFilters) => setSearchParams(searchFromFilters(next), { replace: true })
  const matching = filterItems(submissions.data ?? [], filters)
  const pages = Math.max(1, Math.ceil(matching.length / PAGE_SIZE))
  const shown = pageOf(matching, Math.min(filters.page, pages))
  const loading = submissions.isPending

  return (
    <Stack gap="md">
      <Title order={1}>My submissions</Title>
      <Title order={2} size="h3">Files you submitted</Title>
      <Group gap="sm" align="flex-end">
        <Select
          label="Status"
          placeholder="Any status"
          data={STATUS_OPTIONS}
          value={filters.status}
          onChange={(value) => setFilters({ status: value as IntakeItemStatus | null, page: 1 })}
          clearable
          w={220}
        />
      </Group>
      {submissions.isError && !submissions.data ? (
        <ErrorAlert error={submissions.error} title="Can't load your submissions" onRetry={() => void submissions.refetch()} />
      ) : (
        <>
          <Table.ScrollContainer minWidth={900}>
            <Table aria-label="My submissions" bg="white" withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  {COLUMNS.map((column) => <Table.Th key={column} data-numeric={column === 'Total' || undefined}>{column}</Table.Th>)}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {loading && Array.from({ length: SKELETON_ROWS }, (_, row) => (
                  <Table.Tr key={`skeleton-${row}`} aria-hidden>
                    {COLUMNS.map((column) => <Table.Td key={column}><Skeleton animate={false} height={12} /></Table.Td>)}
                  </Table.Tr>
                ))}
                {!loading && shown.length === 0 && (
                  <Table.Tr>
                    <Table.Td colSpan={COLUMNS.length}>
                      {filters.status ? (
                        <Text size="sm" c="dimmed" py="xs">No submissions match this filter.</Text>
                      ) : (
                        <Text size="sm" c="dimmed" py="xs">
                          You haven't submitted a file yet. <Anchor component={Link} to="/submit" inherit>Submit an invoice.</Anchor>
                        </Text>
                      )}
                    </Table.Td>
                  </Table.Tr>
                )}
                {!loading && shown.map((item) => <SubmissionRow key={item.item_id} item={item} />)}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {pages > 1 && (
            <Group justify="flex-end">
              <Pagination
                total={pages}
                value={Math.min(filters.page, pages)}
                onChange={(page) => setSearchParams(searchFromFilters({ ...filters, page }))}
                size="sm"
                getControlProps={(control) => ({ 'aria-label': `${control} page` })}
              />
            </Group>
          )}
        </>
      )}
      <RequestedBills />
    </Stack>
  )
}
