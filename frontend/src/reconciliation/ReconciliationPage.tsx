import { Anchor, Group, SegmentedControl, SimpleGrid, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import { Fragment, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import type { BankReconciliation, ReconDoublePayment, ReconIssue, ReconLine, ReconPayment } from '../api/types'
import { PAYMENT_METHOD_LABELS } from '../bills/labels'
import { StatusBadge } from '../ui/Badges'
import { DateText, Id, MoneyText } from '../ui/DataText'
import { PAYMENT_STATUS } from '../ui/statusStyles'
import { useBankReconciliation } from './queries'

/** The two views: every line, or only what needs someone's action. Kept in the URL (?view=issues). */
const VIEWS = [
  { value: 'all', label: 'All lines' },
  { value: 'issues', label: 'Only issues' },
] as const

/** One label and value in the summary grid. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="sm" component="div">{children}</Text>
    </Stack>
  )
}

/** "1 line", "333 lines". */
function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

/** "333 lines, $1,740,825.21". */
function CountAndTotal({ count, noun, total }: { count: number; noun: string; total: string }) {
  return <>{`${plural(count, noun)}, `}<MoneyText value={total} /></>
}

const DOUBLE_COLUMNS = ['Bills', 'Card charges', 'Payments', 'Extra paid', 'Still to go out', 'What happened']
const OFF_STATEMENT_COLUMNS = ['Payment', 'Bill', 'Method', 'Status', 'Date', 'Amount (CAD)', 'Issues']

/** A line's or payment's issues: the ones that need review in ink, notes in the secondary colour. */
function Issues({ issues, skip = [] }: { issues: readonly ReconIssue[]; skip?: readonly string[] }) {
  const shown = issues.filter((i) => !skip.includes(i.code))
  if (shown.length === 0) return null
  return (
    <Stack gap={2}>
      {shown.map((issue, index) => (
        <Text key={`${issue.code}-${index}`} size="sm" c={issue.severity === 'review' ? undefined : 'dimmed'}
          fw={issue.severity === 'review' ? 500 : undefined}>
          {issue.message}
        </Text>
      ))}
    </Stack>
  )
}

/** Links to a list of bills or payments, comma separated. */
function Links({ ids, to }: { ids: readonly string[]; to: (id: string) => string }) {
  if (ids.length === 0) return <Text span c="dimmed" size="sm">None</Text>
  return (
    <>
      {ids.map((id, index) => (
        <Fragment key={id}>
          {index > 0 && ', '}
          <Anchor component={Link} to={to(id)} underline="hover"><Id>{id}</Id></Anchor>
        </Fragment>
      ))}
    </>
  )
}

/** A titled section with a one-line count and total under the title. */
function Section({ title, note, children }: { title: string; note: ReactNode; children: ReactNode }) {
  return (
    <Stack component="section" aria-label={title} gap="sm">
      <Stack gap={2}>
        <Title order={2}>{title}</Title>
        <Text size="sm" c="dimmed" component="div">{note}</Text>
      </Stack>
      {children}
    </Stack>
  )
}

/** A table with its column headers (numeric ones right-aligned) and an empty line. */
function SimpleTable({ label, columns, numeric = [], empty, rows }: {
  label: string; columns: readonly string[]; numeric?: readonly string[]; empty: string; rows: ReactNode[]
}) {
  return (
    <Table.ScrollContainer minWidth={820}>
      <Table aria-label={label} bg="white" withTableBorder>
        <Table.Thead>
          <Table.Tr>
            {columns.map((c) => <Table.Th key={c} data-numeric={numeric.includes(c) || undefined}>{c}</Table.Th>)}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.length === 0 ? (
            <Table.Tr><Table.Td colSpan={columns.length}><Text size="sm" c="dimmed" py="xs">{empty}</Text></Table.Td></Table.Tr>
          ) : rows}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}

/** The statement totals: what matched, the fees, what's unexplained, double payments and how much needs review. */
function Summary({ data }: { data: BankReconciliation }) {
  const s = data.summary
  return (
    <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md" verticalSpacing="sm" aria-label="Summary">
      <Field label="Statement">
        {data.statement_from && data.statement_to
          ? <><DateText value={data.statement_from} />{' to '}<DateText value={data.statement_to} /></>
          : 'No statement lines'}
        <Text size="xs" c="dimmed"><CountAndTotal count={s.lines} noun="line" total={s.debits_cad} />{' out'}</Text>
      </Field>
      <Field label="Matched to a payment"><CountAndTotal count={s.matched} noun="line" total={s.matched_cad} /></Field>
      <Field label="Bank fees"><CountAndTotal count={s.bank_fees} noun="line" total={s.bank_fees_cad} /></Field>
      <Field label="Unexplained"><CountAndTotal count={s.unexplained} noun="line" total={s.unexplained_cad} /></Field>
      <Field label="Double payments">
        {`${plural(s.double_payments, 'bill')}, `}<MoneyText value={s.double_paid_extra_cad} />{' paid out extra'}
        {s.double_at_risk_cad !== '0.00' && (
          <Text size="xs" c="dimmed"><MoneyText value={s.double_at_risk_cad} />{' still scheduled to go out'}</Text>
        )}
      </Field>
      <Field label="Needs review">
        {`${plural(s.needs_review, 'line')} or payment${s.needs_review === 1 ? '' : 's'}`}
      </Field>
    </SimpleGrid>
  )
}

/** One statement line: id, date, description, amount, then what it matched and its issues. */
function LineRow({ line, matched, skip }: { line: ReconLine; matched: boolean; skip?: readonly string[] }) {
  return (
    <Table.Tr>
      <Table.Td><Id>{line.bank_txn_id}</Id></Table.Td>
      <Table.Td><DateText value={line.posted_date} /></Table.Td>
      <Table.Td>{line.description}</Table.Td>
      <Table.Td data-numeric>
        <MoneyText value={line.amount} align="right" />
        {line.difference && (
          <Text size="xs" c="dimmed" ta="right">{'Differs by '}<MoneyText value={line.difference} /></Text>
        )}
      </Table.Td>
      {matched && <Table.Td><Links ids={line.payment_ids} to={(id) => `/payments/${id}`} /></Table.Td>}
      {matched && <Table.Td><Links ids={line.bill_ids} to={(id) => `/bills/${id}`} /></Table.Td>}
      <Table.Td><Issues issues={line.issues} skip={skip} /></Table.Td>
    </Table.Tr>
  )
}

/** One bill paid more than once. */
function DoubleRow({ group }: { group: ReconDoublePayment }) {
  return (
    <Table.Tr>
      <Table.Td><Links ids={group.bill_ids} to={(id) => `/bills/${id}`} /></Table.Td>
      <Table.Td>
        {group.card_txn_ids.length > 0
          ? group.card_txn_ids.map((id) => <Id key={id}>{id}</Id>)
          : <Text span c="dimmed" size="sm">None</Text>}
      </Table.Td>
      <Table.Td><Links ids={group.payment_ids} to={(id) => `/payments/${id}`} /></Table.Td>
      <Table.Td data-numeric><MoneyText value={group.extra_paid_cad} align="right" /></Table.Td>
      <Table.Td data-numeric><MoneyText value={group.at_risk_cad} align="right" /></Table.Td>
      <Table.Td>
        <Text size="sm">{group.message}</Text>
        <Text size="xs" c="dimmed">{group.confirmed ? 'Confirmed: same invoice number' : 'Likely: AP payment and a card charge'}</Text>
      </Table.Td>
    </Table.Tr>
  )
}

/** One payment the statement doesn't show (cards, scheduled, outstanding cheques) or that needs a note. */
function PaymentRow({ payment }: { payment: ReconPayment }) {
  const status = payment.status as keyof typeof PAYMENT_STATUS
  return (
    <Table.Tr>
      <Table.Td>
        <Anchor component={Link} to={`/payments/${payment.payment_id}`} underline="hover"><Id>{payment.payment_id}</Id></Anchor>
      </Table.Td>
      <Table.Td><Anchor component={Link} to={`/bills/${payment.bill_id}`} underline="hover"><Id>{payment.bill_id}</Id></Anchor></Table.Td>
      <Table.Td>{PAYMENT_METHOD_LABELS[payment.method] ?? payment.method}</Table.Td>
      <Table.Td>{PAYMENT_STATUS[status] ? <StatusBadge kind="payment" status={status} /> : payment.status}</Table.Td>
      <Table.Td>{payment.on_date ? <DateText value={payment.on_date} /> : <Text span c="dimmed" size="sm">None</Text>}</Table.Td>
      <Table.Td data-numeric><MoneyText value={payment.amount_cad} align="right" /></Table.Td>
      <Table.Td><Issues issues={payment.issues} /></Table.Td>
    </Table.Tr>
  )
}

/** The statement grouped: unexplained debits, double payments, bank fees, matched lines, then payments off the statement. */
function Groups({ data, onlyIssues }: { data: BankReconciliation; onlyIssues: boolean }) {
  const s = data.summary
  const unexplained = data.lines.filter((l) => l.status === 'unexplained')
  const fees = data.lines.filter((l) => l.status === 'bank_fee')
  const matched = data.lines.filter((l) => l.status === 'matched')
  const lineColumns = ['Line', 'Posted', 'Description', 'Amount', 'Issues']
  /** In the issues view, how many of the group are shown. */
  const shownNote = (shown: number) => (onlyIssues ? ` Showing the ${shown} that need review.` : '')

  return (
    <Stack gap="lg">
      <Section title="Unexplained debits"
        note={<>
          <CountAndTotal count={s.unexplained} noun="line" total={s.unexplained_cad} />
          {'. Money that left with no payment, bill or fee behind it.'}
        </>}>
        <SimpleTable label="Unexplained debits" columns={lineColumns} numeric={['Amount']}
          empty="Every debit is matched or explained."
          rows={unexplained.map((l) => <LineRow key={l.bank_txn_id} line={l} matched={false} />)} />
      </Section>

      <Section title="Double payments"
        note={<>
          {`${plural(s.double_payments, 'bill')}, `}<MoneyText value={s.double_paid_extra_cad} />{' paid out extra, '}
          <MoneyText value={s.double_at_risk_cad} />{' still to go out.'}
        </>}>
        <SimpleTable label="Double payments" columns={DOUBLE_COLUMNS}
          numeric={['Extra paid', 'Still to go out']} empty="No bill was paid twice."
          rows={data.double_payments.map((g) => <DoubleRow key={[...g.bill_ids, ...g.card_txn_ids].join('-')} group={g} />)} />
      </Section>

      <Section title="Bank fees"
        note={<><CountAndTotal count={s.bank_fees} noun="line" total={s.bank_fees_cad} />{'.'}{shownNote(fees.length)}</>}>
        <SimpleTable label="Bank fees" columns={lineColumns} numeric={['Amount']}
          empty={onlyIssues ? 'No bank fee needs review.' : 'No bank fees.'}
          rows={fees.map((l) => <LineRow key={l.bank_txn_id} line={l} matched={false} skip={['BANK_FEE']} />)} />
      </Section>

      <Section title="Matched"
        note={<><CountAndTotal count={s.matched} noun="line" total={s.matched_cad} />{'.'}{shownNote(matched.length)}</>}>
        <SimpleTable label="Matched lines" columns={['Line', 'Posted', 'Description', 'Amount', 'Payment', 'Bill', 'Issues']}
          numeric={['Amount']} empty={onlyIssues ? 'No matched line needs review.' : 'No line matched a payment.'}
          rows={matched.map((l) => <LineRow key={l.bank_txn_id} line={l} matched />)} />
      </Section>

      <Section title="Payments not on the statement"
        note={onlyIssues ? 'The ones that need review.' : 'Card payments, scheduled payments and cheques not cleared yet.'}>
        <SimpleTable label="Payments not on the statement" columns={OFF_STATEMENT_COLUMNS}
          numeric={['Amount (CAD)']} empty={onlyIssues ? 'No payment needs review.' : 'Every payment is on the statement.'}
          rows={data.payments.filter((p) => !p.bank_txn_id).map((p) => <PaymentRow key={p.payment_id} payment={p} />)} />
      </Section>
    </Stack>
  )
}

/**
 * /reconciliation: the bank statement against the payments (GET /reconciliation/bank). Every line is matched to its
 * payment, a bank fee or unexplained; double payments and payments the statement doesn't show are listed with what
 * to do. Controller and auditor only; the server enforces it.
 */
export default function ReconciliationPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const onlyIssues = searchParams.get('view') === 'issues'
  const report = useBankReconciliation(onlyIssues)

  return (
    <Stack gap="lg">
      <Title order={1}>Bank reconciliation</Title>
      <Group>
        <SegmentedControl aria-label="Show" data={VIEWS.map((v) => ({ value: v.value, label: v.label }))}
          value={onlyIssues ? 'issues' : 'all'}
          onChange={(value) => setSearchParams(value === 'issues' ? { view: 'issues' } : {}, { replace: true })} />
      </Group>
      {report.isError && !report.data ? (
        <ErrorAlert error={report.error} title="Can't load the reconciliation" onRetry={() => void report.refetch()} />
      ) : !report.data ? (
        <Stack gap="md" aria-busy="true" aria-label="Loading reconciliation">
          <Skeleton animate={false} height={64} />
          <Skeleton animate={false} height={240} />
        </Stack>
      ) : (
        <>
          <Summary data={report.data} />
          <Groups data={report.data} onlyIssues={onlyIssues} />
        </>
      )}
    </Stack>
  )
}
