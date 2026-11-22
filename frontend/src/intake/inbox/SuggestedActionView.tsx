import { Anchor, Box, Button, CopyButton, Group, Stack, Table, Text, Title } from '@mantine/core'
import { IconCheck, IconCopy } from '@tabler/icons-react'
import { Link } from 'react-router'

import { codeAsWords } from '../../api/reference'
import { isMoney } from '../../lib/money'
import { SURFACE } from '../../theme'
import { DateText, Id, MoneyText } from '../../ui/DataText'
import { Icon } from '../../ui/Icon'
import type { InvoiceStatus, SuggestedAction } from '../common/types'

/** An amount from the API; shown as text if it isn't in the two-decimal money format. */
function Amount({ value, currency }: { value: string | null | undefined; currency?: string | null }) {
  if (!value) return null
  return isMoney(value) ? <MoneyText value={value} currency={currency ?? 'CAD'} /> : <>{value}</>
}

/** The ready reply to the sender, as it would be sent, with a button that copies it. */
function ReplyText({ text, language }: { text: string; language: string }) {
  return (
    <Stack gap="xs">
      <Group justify="space-between" align="flex-end">
        <Title order={3}>{language === 'fr' ? 'Reply to the sender (in French)' : 'Reply to the sender'}</Title>
        <CopyButton value={text}>
          {({ copied, copy }) => (
            <Button size="xs" variant="default" onClick={copy} leftSection={<Icon icon={copied ? IconCheck : IconCopy} />}>
              {copied ? 'Copied' : 'Copy reply'}
            </Button>
          )}
        </CopyButton>
      </Group>
      <Box
        component="pre"
        data-testid="reply-text"
        p="sm"
        m={0}
        bg="white"
        style={{ border: `1px solid ${SURFACE.border}`, borderRadius: 4, whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 14 }}
      >
        {text}
      </Box>
    </Stack>
  )
}

/** The answer to a payment question: the invoice in our books and its payments. */
function InvoiceStatusView({ status }: { status: InvoiceStatus }) {
  return (
    <Stack gap="xs">
      <Title order={3}>Invoice {status.invoice_number}</Title>
      <Text size="sm">{status.summary}</Text>
      <Group gap="xl">
        <Stack gap={0}>
          <Text size="xs" c="dimmed">Bill</Text>
          {status.invoice_id ? (
            <Anchor component={Link} to={`/bills/${status.invoice_id}`} underline="hover"><Id>{status.invoice_id}</Id></Anchor>
          ) : <Text size="sm">Not in our books</Text>}
        </Stack>
        <Stack gap={0}>
          <Text size="xs" c="dimmed">Status</Text>
          <Text size="sm">{codeAsWords(status.status)}</Text>
        </Stack>
        {status.invoice_date && (
          <Stack gap={0}><Text size="xs" c="dimmed">Invoice date</Text><Text size="sm"><DateText value={status.invoice_date} /></Text></Stack>
        )}
        {status.total && (
          <Stack gap={0}><Text size="xs" c="dimmed">Total</Text><Text size="sm"><Amount value={status.total} currency={status.currency} /></Text></Stack>
        )}
      </Group>
      {status.payments.length > 0 && (
        <Table aria-label="Payments" bg="white" withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Payment</Table.Th><Table.Th>Method</Table.Th><Table.Th>Status</Table.Th><Table.Th>Paid</Table.Th>
              <Table.Th>Reference</Table.Th><Table.Th data-numeric>Amount</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {status.payments.map((payment) => (
              <Table.Tr key={payment.payment_id}>
                <Table.Td><Id>{payment.payment_id}</Id></Table.Td>
                <Table.Td>{payment.method}</Table.Td>
                <Table.Td>{codeAsWords(payment.status)}</Table.Td>
                <Table.Td>{payment.paid_date ? <DateText value={payment.paid_date} /> : 'Not yet'}</Table.Td>
                <Table.Td><Id>{payment.reference}</Id></Table.Td>
                <Table.Td data-numeric><Amount value={payment.amount} currency={payment.currency} /></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  )
}

/**
 * The suggested next step for an email, in full: what to do, plus the ready reply (resend request, payment answer)
 * and the payment facts when there are any. Only shown; nothing is sent from here.
 */
export function SuggestedActionView({ action }: { action: SuggestedAction }) {
  return (
    <Stack gap="md">
      <Text>{action.message}</Text>
      {action.invoice_status && <InvoiceStatusView status={action.invoice_status} />}
      {action.reply_text && <ReplyText text={action.reply_text} language={action.language} />}
    </Stack>
  )
}
