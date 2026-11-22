import { Anchor, Divider, Group, SimpleGrid, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../api/errors'
import { ErrorAlert } from '../api/ErrorAlert'
import { departmentLabel, glAccountName, personName, useDepartments, useGlAccounts, usePeople } from '../api/reference'
import type { PaymentDetail } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { AuditTrail } from '../bills/detail/AuditTrail'
import { PAYMENT_METHOD_LABELS, stepRoleLabel } from '../bills/labels'
import { isInNavigation } from '../shell/navigation'
import { StatusBadge } from '../ui/Badges'
import { DateText, Id, MoneyText } from '../ui/DataText'
import { PaymentActions } from './PaymentActions'
import { usePayment } from './queries'

/** One label and value in the details grid. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="sm" component="div">{children}</Text>
    </Stack>
  )
}

/** The payment's facts: its bill, vendor, amount, dates, who prepared and released it, and the account it went to. */
function PaymentFacts({ payment }: { payment: PaymentDetail }) {
  const people = usePeople()
  const account = payment.bank_account
  return (
    <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} spacing="md" verticalSpacing="sm">
      <Field label="Bill">
        <Group gap={6} wrap="wrap">
          <Anchor component={Link} to={`/bills/${payment.bill_id}`} underline="hover"><Id>{payment.bill_id}</Id></Anchor>
          <StatusBadge kind="bill" status={payment.bill.status} />
        </Group>
      </Field>
      <Field label="Vendor">
        <Group gap={6} wrap="wrap">
          <span>{payment.vendor_name ?? payment.vendor_id}</span>
          <Anchor component={Link} to={`/vendors/${payment.vendor_id}`} underline="hover"><Id>{payment.vendor_id}</Id></Anchor>
        </Group>
      </Field>
      <Field label="Invoice number"><Id>{payment.bill.vendor_invoice_number}</Id></Field>
      <Field label="Amount">
        <Text size="sm" fw={600} span><MoneyText value={payment.amount} currency={payment.currency} /></Text>
        {payment.currency !== 'CAD' && (
          <Text size="xs" c="dimmed">
            <MoneyText value={payment.amount_cad} />{` at ${payment.fx_rate_to_cad} ${payment.currency}/CAD`}
          </Text>
        )}
        {payment.discount_taken !== '0.00' && (
          <Text size="xs" c="dimmed">{'Discount taken: '}<MoneyText value={payment.discount_taken} currency={payment.currency} /></Text>
        )}
      </Field>
      <Field label="Method">{PAYMENT_METHOD_LABELS[payment.method] ?? payment.method}</Field>
      <Field label="Scheduled"><DateText value={payment.scheduled_date} /></Field>
      <Field label="Paid">{payment.paid_date ? <DateText value={payment.paid_date} /> : 'Not yet'}</Field>
      <Field label="Reference">{payment.reference ? <Id>{payment.reference}</Id> : 'None'}</Field>
      <Field label="Prepared by">{payment.prepared_by ? personName(payment.prepared_by, people.data) : 'None'}</Field>
      <Field label="Released by">
        {payment.released_by ? (
          <>
            {personName(payment.released_by, people.data)}
            {payment.released_at && <Text size="xs" c="dimmed"><DateText value={payment.released_at} kind="timestamp" /></Text>}
          </>
        ) : 'Not released'}
      </Field>
      <Field label="Bank account">
        {account ? (
          <>
            {account.masked ? `Ending ${account.account_last4}` : <Id>{account.account}</Id>}
            <Text size="xs" c="dimmed">{`Institution ${account.institution}, transit ${account.transit}`}</Text>
          </>
        ) : 'None (not an EFT payment, or no account on file)'}
      </Field>
    </SimpleGrid>
  )
}

/** The bill's approval chain: every decision, who made it (and for whom) and when. */
function ApprovalChain({ payment }: { payment: PaymentDetail }) {
  const people = usePeople()
  return (
    <Stack gap="sm">
      <Title order={2}>Approval chain</Title>
      {payment.decisions.length === 0 ? (
        <Text size="sm">No approval decisions are recorded for this bill.</Text>
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table aria-label="Approval chain" withTableBorder bg="white">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Step</Table.Th>
                <Table.Th>Decision</Table.Th>
                <Table.Th>By</Table.Th>
                <Table.Th>When</Table.Th>
                <Table.Th>Comment</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {payment.decisions.map((d) => (
                <Table.Tr key={d.decision_id}>
                  <Table.Td>{`Step ${d.step_no}${d.step_role ? `, ${stepRoleLabel(d.step_role)}` : ''}`}</Table.Td>
                  <Table.Td>{d.decision === 'approved' ? 'Approved' : 'Rejected'}</Table.Td>
                  <Table.Td>
                    {personName(d.actor_user_id, people.data)} <Id>{d.actor_user_id}</Id>
                    {d.on_behalf_of && (
                      <Text size="xs" c="dimmed">{`on behalf of ${personName(d.on_behalf_of, people.data)}`}</Text>
                    )}
                  </Table.Td>
                  <Table.Td><DateText value={d.acted_at} kind="timestamp" /></Table.Td>
                  <Table.Td>{d.comment ?? <Text span c="dimmed" size="sm">None</Text>}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  )
}

/** The bill's lines with their accounting codes (GL account and department). */
function Coding({ payment }: { payment: PaymentDetail }) {
  const accounts = useGlAccounts()
  const departments = useDepartments()
  return (
    <Stack gap="sm">
      <Title order={2}>Accounting codes</Title>
      {payment.lines.length === 0 ? (
        <Text size="sm">This bill has no lines.</Text>
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table aria-label="Accounting codes" withTableBorder bg="white">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Line</Table.Th>
                <Table.Th>Description</Table.Th>
                <Table.Th>GL account</Table.Th>
                <Table.Th>Department</Table.Th>
                <Table.Th data-numeric>Amount</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {payment.lines.map((line) => {
                const gl = line.gl_account ?? line.suggested_gl_account
                const department = line.department_id ?? line.suggested_department_id
                return (
                  <Table.Tr key={line.line_no}>
                    <Table.Td>{line.line_no}</Table.Td>
                    <Table.Td>{line.description}</Table.Td>
                    <Table.Td>
                      {gl ? <><Id>{gl}</Id>{glAccountName(gl, accounts.data) ? ` ${glAccountName(gl, accounts.data)}` : ''}</> : 'Not coded'}
                      {!line.gl_account && line.suggested_gl_account && <Text size="xs" c="dimmed">Suggested, not confirmed</Text>}
                    </Table.Td>
                    <Table.Td>{department ? departmentLabel(department, departments.data) : 'None'}</Table.Td>
                    <Table.Td data-numeric><MoneyText value={line.amount} currency={payment.bill.currency} align="right" /></Table.Td>
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  )
}

/** The audit trail: the payment's events and its bill's, plus a link to the full audit log for those who can read it. */
function PaymentAudit({ payment }: { payment: PaymentDetail }) {
  const user = useCurrentUser()
  return (
    <Stack gap="xs">
      <AuditTrail bill={payment} emptyMessage="No audit events for this payment or its bill yet." />
      {isInNavigation(user.role, 'audit') && (
        <Anchor component={Link} to={`/audit?entity_type=payment&entity_id=${payment.payment_id}`} size="sm" w="fit-content">
          Open this payment in the audit log
        </Anchor>
      )}
    </Stack>
  )
}

/** Shown for a 404: the payment doesn't exist, or the signed-in role can't see payments. */
function PaymentNotFound({ paymentId }: { paymentId: string }) {
  return (
    <Stack gap="sm" maw={720}>
      <Title order={1}>Payment not found</Title>
      <Text>There is no payment <Id>{paymentId}</Id> that you can see.</Text>
      <Anchor component={Link} to="/payments" size="sm" w="fit-content">Back to payments</Anchor>
    </Stack>
  )
}

/**
 * /payments/:paymentId, the audit-ready view of one payment: its facts and actions, the bill it pays (linked), the
 * bill's approval chain and accounting codes, and the audit trail. All from GET /payments/{id}.
 */
export function PaymentDetailView({ paymentId }: { paymentId: string }) {
  const payment = usePayment(paymentId)

  if (payment.isPending) {
    return (
      <Stack gap="md" aria-busy="true" aria-label="Loading payment">
        <Skeleton animate={false} height={28} width={260} />
        <Skeleton animate={false} height={160} />
      </Stack>
    )
  }
  if (payment.error instanceof ApiError && payment.error.status === 404) return <PaymentNotFound paymentId={paymentId} />
  if (payment.isError) {
    return <ErrorAlert error={payment.error} title="Can't load this payment" onRetry={() => void payment.refetch()} />
  }

  const data = payment.data
  return (
    <Stack gap="lg">
      <Stack component="section" aria-label="Payment summary" gap="sm">
        <Group justify="space-between" align="center">
          <Group gap="sm" align="center">
            <Title order={1}>Payment <Id>{data.payment_id}</Id></Title>
            <StatusBadge kind="payment" status={data.status} />
          </Group>
          <PaymentActions paymentId={data.payment_id} />
        </Group>
        <PaymentFacts payment={data} />
      </Stack>
      <Divider />
      <ApprovalChain payment={data} />
      <Divider />
      <Coding payment={data} />
      <Divider />
      <PaymentAudit payment={data} />
    </Stack>
  )
}

/** The routed screen: reads the payment id from the URL. */
export default function PaymentDetailPage() {
  const { paymentId = '' } = useParams()
  return <PaymentDetailView paymentId={paymentId} />
}
