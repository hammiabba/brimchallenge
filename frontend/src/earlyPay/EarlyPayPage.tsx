import { Anchor, Group, SegmentedControl, SimpleGrid, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import type { ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import type { BillStatus, EarlyPayReport, EarlyPaySuggestion, PastDiscount, Role } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { StatusBadge } from '../ui/Badges'
import { DateText, Id, MoneyText } from '../ui/DataText'
import { useEarlyPay } from './queries'

/** Which bills: approved and scheduled (the default), or those plus bills still in review. Kept in the URL. */
const VIEWS = [
  { value: 'open', label: 'Approved and scheduled' },
  { value: 'pending', label: 'Include bills in review' },
] as const

/** What to do with each bill, in words. */
const ACTIONS: Record<EarlyPaySuggestion['action'], string> = {
  take_discount: 'Pay early for the discount',
  pay_on_due_date: 'Pay on the due date',
  pay_now: 'Pay now',
  reschedule: 'Reschedule',
}

/** Roles that only read this page: the last column is a suggestion to them, not their to-do. */
const READ_ONLY_ROLES: readonly Role[] = ['auditor']

/** One label and value in the summary grid. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="sm" component="div">{children}</Text>
    </Stack>
  )
}

/**
 * A table with headers (numeric ones right-aligned) and a one-line empty state. The tables here fit the 752 px
 * content column at 1024 px (secondary details sit under the main value), and scroll sideways below that.
 */
function SimpleTable({ label, columns, numeric, empty, rows }: {
  label: string; columns: readonly string[]; numeric: readonly string[]; empty: string; rows: ReactNode[]
}) {
  return (
    <Table.ScrollContainer minWidth={700}>
      <Table aria-label={label} bg="white" withTableBorder>
        <Table.Thead>
          <Table.Tr>
            {columns.map((c) => <Table.Th key={c} data-numeric={numeric.includes(c) || undefined}>{c}</Table.Th>)}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.length === 0
            ? <Table.Tr><Table.Td colSpan={columns.length}><Text size="sm" c="dimmed" py="xs">{empty}</Text></Table.Td></Table.Tr>
            : rows}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}

/** The suggestion tables' columns; the last one is "Suggestion" for roles that only read. */
function suggestionColumns(readOnly: boolean): string[] {
  return ['Bill', 'Terms', 'Dates', 'Best pay date', 'Saving', readOnly ? 'Suggestion' : 'What to do']
}

/**
 * One bill: the bill with its vendor and status under it, its terms, its due and scheduled dates, the suggested pay
 * date and saving, and what to do with the reason (and any notes).
 */
function SuggestionRow({ s }: { s: EarlyPaySuggestion }) {
  const urgent = s.action === 'reschedule' || s.action === 'pay_now'
  return (
    <Table.Tr>
      <Table.Td>
        <Stack gap={2} align="flex-start">
          <Anchor component={Link} to={`/bills/${s.bill_id}`} underline="hover" fw={500}><Id>{s.bill_id}</Id></Anchor>
          <Text size="xs">{s.vendor_name ?? s.vendor_id}</Text>
          {/* The API types the status as a string; it is a bill status, and an unknown one shows no badge. */}
          <StatusBadge kind="bill" status={s.status as BillStatus} />
        </Stack>
      </Table.Td>
      <Table.Td>{s.terms}</Table.Td>
      <Table.Td>
        <Text size="sm">{'Due '}<DateText value={s.due_date} /></Text>
        <Text size="xs" c="dimmed">
          {s.scheduled_date ? <>{'Scheduled '}<DateText value={s.scheduled_date} /></> : 'Not scheduled'}
        </Text>
      </Table.Td>
      <Table.Td>
        <DateText value={s.pay_on} />
        {s.discount_deadline && <Text size="xs" c="dimmed">{'Discount ends '}<DateText value={s.discount_deadline} /></Text>}
      </Table.Td>
      <Table.Td data-numeric>
        <MoneyText value={s.saving_cad} align="right" />
        {s.currency !== 'CAD' && s.saving !== '0.00' && (
          <Text size="xs" c="dimmed" ta="right"><MoneyText value={s.saving} currency={s.currency} /></Text>
        )}
      </Table.Td>
      <Table.Td>
        <Text size="sm" fw={urgent ? 600 : undefined}>{ACTIONS[s.action]}</Text>
        <Text size="xs" c="dimmed">{s.reason}</Text>
        {s.notes.map((note) => <Text key={note} size="xs" c="dimmed">{note}</Text>)}
      </Table.Td>
    </Table.Tr>
  )
}

/** One past payment that missed its discount. */
function MissedRow({ m }: { m: PastDiscount }) {
  return (
    <Table.Tr>
      <Table.Td>
        <Anchor component={Link} to={`/payments/${m.payment_id}`} underline="hover"><Id>{m.payment_id}</Id></Anchor>
      </Table.Td>
      <Table.Td><Anchor component={Link} to={`/bills/${m.bill_id}`} underline="hover"><Id>{m.bill_id}</Id></Anchor></Table.Td>
      <Table.Td>{m.vendor_name ?? <Id>{m.vendor_id}</Id>}</Table.Td>
      <Table.Td><DateText value={m.invoice_date} /></Table.Td>
      <Table.Td><DateText value={m.paid_date} /></Table.Td>
      <Table.Td data-numeric>{m.days_to_pay}</Table.Td>
      <Table.Td data-numeric><MoneyText value={m.discount_cad} align="right" /></Table.Td>
    </Table.Tr>
  )
}

/**
 * The summary, the bills to reschedule (or pay now), the best pay dates of the other bills, and the history. A bill
 * is listed once: an urgent one only in the first table.
 */
function Report({ data, includePending }: { data: EarlyPayReport; includePending: boolean }) {
  const s = data.summary
  const readOnly = READ_ONLY_ROLES.includes(useCurrentUser().role)
  const columns = suggestionColumns(readOnly)
  const isUrgent = (x: EarlyPaySuggestion) => x.action === 'reschedule' || x.action === 'pay_now'
  const urgent = data.suggestions.filter(isUrgent)
  const others = data.suggestions.filter((x) => !isUrgent(x))
  const h = data.history
  return (
    <Stack gap="lg">
      <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} spacing="md" verticalSpacing="sm" aria-label="Summary">
        <Field label="Bills">{`${s.bills} ${includePending ? 'approved, scheduled or in review' : 'approved or scheduled'}`}</Field>
        <Field label="Saving if paid on the suggested dates">
          <Text size="sm" fw={600} span><MoneyText value={s.saving_cad} /></Text>
          <Text size="xs" c="dimmed">
            {`${s.with_discount_open} bill${s.with_discount_open === 1 ? '' : 's'} with a discount still open`}
          </Text>
        </Field>
        <Field label="To reschedule">{`${s.to_reschedule}`}</Field>
        <Field label="To pay now">{`${s.pay_now}`}</Field>
      </SimpleGrid>

      <Stack component="section" aria-label="To reschedule or pay now" gap="sm">
        <Title order={2}>To reschedule or pay now</Title>
        <SimpleTable label="To reschedule or pay now" columns={columns} numeric={['Saving']}
          empty="Every payment is on its best date." rows={urgent.map((x) => <SuggestionRow key={x.bill_id} s={x} />)} />
      </Stack>

      <Stack component="section" aria-label="Best pay dates" gap="sm">
        <Title order={2}>Best pay dates</Title>
        <Text size="sm" c="dimmed">
          The other bills. A discount open: pay in time to arrive by its last day. Otherwise: pay on the due date, since
          paying earlier saves nothing. Biggest saving first.
        </Text>
        <SimpleTable label="Best pay dates" columns={columns} numeric={['Saving']}
          empty={data.suggestions.length > 0 ? 'Every bill is listed above.'
            : includePending ? 'No bill is approved, scheduled or in review.' : 'No bill is approved or scheduled.'}
          rows={others.map((x) => <SuggestionRow key={x.bill_id} s={x} />)} />
      </Stack>

      <Stack component="section" aria-label="Discounts in the history" gap="sm">
        <Title order={2}>Discounts in the history</Title>
        <Text size="sm">
          {`${h.taken} taken, `}<MoneyText value={h.taken_cad} />{` saved. ${h.missed} missed, `}<MoneyText value={h.missed_cad} />
          {' lost by paying after the discount window.'}
        </Text>
        <SimpleTable label="Missed discounts" columns={['Payment', 'Bill', 'Vendor', 'Invoice date', 'Paid', 'Days to pay', 'Missed']}
          numeric={['Days to pay', 'Missed']} empty="No discount was missed."
          rows={h.missed_payments.map((m) => <MissedRow key={m.payment_id} m={m} />)} />
      </Stack>
    </Stack>
  )
}

/**
 * /early-pay: when to pay each bill under its vendor's terms ("2/10 net 30"), what paying early saves, which payments
 * should move, and the discounts the history took and missed (GET /early-pay). AP, finance, the controller and
 * auditors; the server enforces it.
 */
export default function EarlyPayPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const includePending = searchParams.get('include') === 'pending'
  const report = useEarlyPay(includePending)

  return (
    <Stack gap="lg">
      <Stack gap={2}>
        <Title order={1}>Early payment</Title>
        {report.data && <Text size="sm" c="dimmed">{'As of '}<DateText value={report.data.as_of} /></Text>}
      </Stack>
      <Group>
        <SegmentedControl aria-label="Bills" data={VIEWS.map((v) => ({ value: v.value, label: v.label }))}
          value={includePending ? 'pending' : 'open'}
          onChange={(value) => setSearchParams(value === 'pending' ? { include: 'pending' } : {}, { replace: true })} />
      </Group>
      {report.isError && !report.data ? (
        <ErrorAlert error={report.error} title="Can't load early payment" onRetry={() => void report.refetch()} />
      ) : !report.data ? (
        <Stack gap="md" aria-busy="true" aria-label="Loading early payment">
          <Skeleton animate={false} height={48} />
          <Skeleton animate={false} height={240} />
        </Stack>
      ) : (
        <Report data={report.data} includePending={includePending} />
      )}
    </Stack>
  )
}
