import { Stack, Table, Text, Title } from '@mantine/core'

import { personName, usePeople } from '../../api/reference'
import type { BillDetail } from '../../api/types'
import { StatusBadge } from '../../ui/Badges'
import { DateText, Id, MoneyText } from '../../ui/DataText'
import { PAYMENT_METHOD_LABELS } from '../labels'

/** The bill's payments: id, method, scheduled and paid dates, amount, status and who released it. */
export function PaymentsTable({ bill }: { bill: BillDetail }) {
  const people = usePeople()
  return (
    <Stack gap="sm">
      <Title order={2}>Payments</Title>
      {bill.payments.length === 0 ? (
        <Text size="sm">No payments for this bill yet.</Text>
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table aria-label="Payments" withTableBorder bg="white" stickyHeader={false}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Payment</Table.Th>
                <Table.Th>Method</Table.Th>
                <Table.Th>Scheduled</Table.Th>
                <Table.Th>Paid</Table.Th>
                <Table.Th data-numeric>Amount</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Released by</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {bill.payments.map((p) => (
                <Table.Tr key={p.payment_id}>
                  <Table.Td><Id>{p.payment_id}</Id></Table.Td>
                  <Table.Td>{PAYMENT_METHOD_LABELS[p.method] ?? p.method}</Table.Td>
                  <Table.Td><DateText value={p.scheduled_date} /></Table.Td>
                  <Table.Td>{p.paid_date ? <DateText value={p.paid_date} /> : <Text span c="dimmed" size="sm">Not yet</Text>}</Table.Td>
                  <Table.Td data-numeric><MoneyText value={p.amount} currency={p.currency} /></Table.Td>
                  <Table.Td><StatusBadge kind="payment" status={p.status} /></Table.Td>
                  <Table.Td>{p.released_by ? personName(p.released_by, people.data) : <Text span c="dimmed" size="sm">Not released</Text>}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  )
}
