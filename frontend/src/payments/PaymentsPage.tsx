import { Anchor, Button, Group, Pagination, SegmentedControl, SimpleGrid, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import { personName, usePeople } from '../api/reference'
import type { BillSummary, Payment, PaymentStatus } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { PAYMENT_METHOD_LABELS } from '../bills/labels'
import { useBill } from '../bills/queries'
import { StatusBadge } from '../ui/Badges'
import { DateText, Id, MoneyText } from '../ui/DataText'
import { PAYMENT_STATUS } from '../ui/statusStyles'
import { PAYMENTS_PAGE_SIZE, useApprovedBills, usePaymentsPage, usePaymentsSummary } from './queries'
import { ScheduleModal } from './ScheduleModal'

/** The status tabs over the payments list; "all" is no filter. The list opens on what is still to be released. */
const TABS = [
  { value: 'scheduled', label: PAYMENT_STATUS.scheduled.label },
  { value: 'released', label: PAYMENT_STATUS.released.label },
  { value: 'settled', label: PAYMENT_STATUS.settled.label },
  { value: 'outstanding', label: PAYMENT_STATUS.outstanding.label },
  { value: 'cancelled', label: PAYMENT_STATUS.cancelled.label },
  { value: 'all', label: 'All' },
] as const
type Tab = (typeof TABS)[number]['value']

const SKELETON_ROWS = 5

/** The tab in the URL (?status=released); anything unknown falls back to scheduled. */
function tabFromSearch(search: URLSearchParams): Tab {
  const value = search.get('status')
  return TABS.find((tab) => tab.value === value)?.value ?? 'scheduled'
}

/** The page in the URL (?page=2), at least 1. */
function pageFromSearch(search: URLSearchParams): number {
  const page = Number(search.get('page'))
  return Number.isInteger(page) && page > 1 ? page : 1
}

/** One label and value in the overview grid. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="sm" component="div">{children}</Text>
    </Stack>
  )
}

/** "3 payments, $12,000.00". */
function CountAndTotal({ count, total }: { count: number; total: string }) {
  return <>{`${count} payment${count === 1 ? '' : 's'}, `}<MoneyText value={total} /></>
}

/** A table's skeleton rows and empty line, shared by the tables on this screen. */
function TableState({ loading, empty, columns, message }: {
  loading: boolean; empty: boolean; columns: number; message: string
}) {
  if (loading) {
    return Array.from({ length: SKELETON_ROWS }, (_, row) => (
      <Table.Tr key={`skeleton-${row}`} aria-hidden>
        {Array.from({ length: columns }, (_, cell) => (
          <Table.Td key={cell}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>
        ))}
      </Table.Tr>
    ))
  }
  if (!empty) return null
  return (
    <Table.Tr>
      <Table.Td colSpan={columns}><Text size="sm" c="dimmed" py="xs">{message}</Text></Table.Td>
    </Table.Tr>
  )
}

/** The dashboard: due in the next 7 days, overdue, and every status with its count and total (GET /payments/summary). */
function Overview() {
  const summary = usePaymentsSummary()
  if (summary.isError) {
    return <ErrorAlert error={summary.error} title="Can't load the payment totals" onRetry={() => void summary.refetch()} />
  }
  const data = summary.data
  return (
    <Stack component="section" aria-label="Overview" gap="sm">
      <Title order={2}>Overview</Title>
      {!data ? (
        <Skeleton animate={false} height={48} />
      ) : (
        <>
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
            <Field label="Due in the next 7 days">
              <CountAndTotal count={data.due_next_7_days_count} total={data.due_next_7_days_cad} />
            </Field>
            <Field label="Overdue">
              <CountAndTotal count={data.overdue_count} total={data.overdue_cad} />
            </Field>
            <Field label="As of"><DateText value={data.as_of} /></Field>
          </SimpleGrid>
          <Table.ScrollContainer minWidth={420}>
            <Table aria-label="Payments by status" bg="white" withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Status</Table.Th>
                  <Table.Th data-numeric>Payments</Table.Th>
                  <Table.Th data-numeric>Total (CAD)</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.by_status.map((row) => (
                  <Table.Tr key={row.status}>
                    <Table.Td><StatusBadge kind="payment" status={row.status} /></Table.Td>
                    <Table.Td data-numeric>{row.count}</Table.Td>
                    <Table.Td data-numeric><MoneyText value={row.total_cad} align="right" /></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}
    </Stack>
  )
}

/**
 * Schedule, when the bill's allowed_actions (GET /bills/{id}) says the signed-in user may schedule it now. For AP, a
 * bill they can't schedule shows the server's reason instead (a pending bank change, an inactive vendor).
 */
function ScheduleCell({ bill, asOf }: { bill: BillSummary; asOf: string }) {
  const user = useCurrentUser()
  const detail = useBill(bill.bill_id)
  const [open, setOpen] = useState(false)
  const action = detail.data?.allowed_actions?.schedule_payment
  if (!action) return null
  if (!action.allowed) {
    return user.role === 'ap_clerk' && action.reason ? <Text size="sm" c="dimmed">{action.reason}</Text> : null
  }
  return (
    <>
      <Button size="xs" onClick={() => setOpen(true)}>Schedule</Button>
      <ScheduleModal bill={bill} asOf={asOf} opened={open} onClose={() => setOpen(false)} />
    </>
  )
}

/** One approved bill waiting for its payment to be scheduled. */
function ApprovedRow({ bill, asOf, actions }: { bill: BillSummary; asOf: string; actions: boolean }) {
  return (
    <Table.Tr>
      <Table.Td>
        <Anchor component={Link} to={`/bills/${bill.bill_id}`} underline="hover" fw={500}><Id>{bill.bill_id}</Id></Anchor>
      </Table.Td>
      <Table.Td>{bill.vendor_name ?? <Text span c="dimmed" size="sm">No vendor matched</Text>}</Table.Td>
      <Table.Td>{bill.due_date ? <DateText value={bill.due_date} /> : <Text span c="dimmed" size="sm">None</Text>}</Table.Td>
      <Table.Td data-numeric><MoneyText value={bill.total_cad} align="right" /></Table.Td>
      {actions && <Table.Td><ScheduleCell bill={bill} asOf={asOf} /></Table.Td>}
    </Table.Tr>
  )
}

/** Approved bills with no payment yet (GET /bills?status=approved). AP schedules them; the server decides who may. */
function ApprovedBills() {
  const user = useCurrentUser()
  const bills = useApprovedBills()
  const summary = usePaymentsSummary()
  const asOf = summary.data?.as_of ?? ''
  // Only AP schedules payments, so other roles don't get an empty Actions column. The buttons still need the server's yes.
  const actions = user.role === 'ap_clerk'
  const columns = ['Bill', 'Vendor', 'Due date', 'Total (CAD)', ...(actions ? ['Actions'] : [])]
  return (
    <Stack component="section" aria-label="Approved, not scheduled" gap="sm">
      <Title order={2}>Approved, not scheduled</Title>
      {bills.isError ? (
        <ErrorAlert error={bills.error} title="Can't load approved bills" onRetry={() => void bills.refetch()} />
      ) : (
        <Table.ScrollContainer minWidth={640}>
          <Table aria-label="Approved bills" bg="white" withTableBorder>
            <Table.Thead>
              <Table.Tr>
                {columns.map((c) => <Table.Th key={c} data-numeric={c === 'Total (CAD)' || undefined}>{c}</Table.Th>)}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              <TableState loading={bills.isPending} empty={bills.data?.items.length === 0} columns={columns.length}
                message="No approved bill is waiting for a payment." />
              {bills.data?.items.map((bill) => <ApprovedRow key={bill.bill_id} bill={bill} asOf={asOf} actions={actions} />)}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  )
}

/** One payment in the list. */
function PaymentRow({ payment }: { payment: Payment }) {
  const people = usePeople()
  return (
    <Table.Tr>
      <Table.Td><Id>{payment.payment_id}</Id></Table.Td>
      <Table.Td>
        <Anchor component={Link} to={`/bills/${payment.bill_id}`} underline="hover"><Id>{payment.bill_id}</Id></Anchor>
      </Table.Td>
      <Table.Td>{payment.vendor_name ?? payment.vendor_id}</Table.Td>
      <Table.Td>{PAYMENT_METHOD_LABELS[payment.method] ?? payment.method}</Table.Td>
      <Table.Td><DateText value={payment.scheduled_date} /></Table.Td>
      <Table.Td>{payment.paid_date ? <DateText value={payment.paid_date} /> : <Text span c="dimmed" size="sm">Not yet</Text>}</Table.Td>
      <Table.Td data-numeric>
        <MoneyText value={payment.amount_cad} align="right" />
        {payment.currency !== 'CAD' && (
          <Text size="xs" c="dimmed" ta="right"><MoneyText value={payment.amount} currency={payment.currency} /></Text>
        )}
      </Table.Td>
      <Table.Td><StatusBadge kind="payment" status={payment.status} /></Table.Td>
      <Table.Td>{payment.prepared_by ? personName(payment.prepared_by, people.data) : <Text span c="dimmed" size="sm">None</Text>}</Table.Td>
      <Table.Td>{payment.released_by ? personName(payment.released_by, people.data) : <Text span c="dimmed" size="sm">Not released</Text>}</Table.Td>
    </Table.Tr>
  )
}

/** The payments list by status, newest scheduled date first, paged (GET /payments). Tab and page are in the URL. */
function PaymentsList() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = tabFromSearch(searchParams)
  const page = pageFromSearch(searchParams)
  const payments = usePaymentsPage(tab === 'all' ? [] : [tab as PaymentStatus], page)
  const columns = ['Payment', 'Bill', 'Vendor', 'Method', 'Scheduled', 'Paid', 'Amount (CAD)', 'Status', 'Prepared by',
    'Released by']
  const total = payments.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAYMENTS_PAGE_SIZE))
  const empty = tab === 'all' ? 'No payments yet.' : `No ${PAYMENT_STATUS[tab].label.toLowerCase()} payments.`

  function setTab(value: string) {
    setSearchParams(value === 'scheduled' ? {} : { status: value }, { replace: true })
  }

  return (
    <Stack component="section" aria-label="Payment list" gap="sm">
      <Title order={2}>Payments</Title>
      <Group>
        <SegmentedControl aria-label="Status" data={TABS.map((t) => ({ value: t.value, label: t.label }))} value={tab}
          onChange={setTab} />
      </Group>
      {payments.isError && !payments.data ? (
        <ErrorAlert error={payments.error} title="Can't load payments" onRetry={() => void payments.refetch()} />
      ) : (
        <>
          <Table.ScrollContainer minWidth={1100}>
            <Table aria-label="Payments" bg="white" withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  {columns.map((c) => <Table.Th key={c} data-numeric={c === 'Amount (CAD)' || undefined}>{c}</Table.Th>)}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                <TableState loading={payments.isPending} empty={payments.data?.items.length === 0} columns={columns.length}
                  message={empty} />
                {payments.data?.items.map((p) => <PaymentRow key={p.payment_id} payment={p} />)}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Group justify="space-between">
            <Text size="sm" c="dimmed">{total > 0 ? `${total} payment${total === 1 ? '' : 's'}` : ''}</Text>
            {pages > 1 && (
              <Pagination
                total={pages}
                value={Math.min(page, pages)}
                onChange={(next) => setSearchParams({ ...(tab === 'scheduled' ? {} : { status: tab }), page: String(next) })}
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

/** "You can release payments up to $100,000.00." for releasers; nothing for roles that can't release. */
function ReleaseLimit() {
  const user = useCurrentUser()
  const limit = user.release_limit_cad
  if (limit === '0.00' || limit === undefined) return null
  return (
    <Text size="sm" c="dimmed">
      {limit === null ? 'You can release payments of any amount.' : <>{'You can release payments up to '}<MoneyText value={limit} />.</>}
    </Text>
  )
}

/**
 * /payments: the payments dashboard. The totals, the approved bills waiting for a payment, and the payments by status.
 * AP, finance, the controller and auditors see it; who may schedule, release or cancel is the server's call.
 */
export default function PaymentsPage() {
  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Title order={1}>Payments</Title>
        <ReleaseLimit />
      </Stack>
      <Overview />
      <ApprovedBills />
      <PaymentsList />
    </Stack>
  )
}
