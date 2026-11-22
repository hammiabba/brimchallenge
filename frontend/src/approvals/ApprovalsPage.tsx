import { Anchor, Box, Button, Group, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import { Link } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import { personName, usePeople } from '../api/reference'
import type { BillSummary } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { OpenFlagsCell } from '../bills/BillsTable'
import { stepRoleLabel } from '../bills/labels'
import { DateText, Id, MoneyText } from '../ui/DataText'
import { useApprovalQueue } from './queries'

const COLUMNS = ['Bill', 'Vendor', 'Invoice no.', 'Invoice date', 'Due date', 'Total (CAD)', 'Open flags',
  'Your step'] as const
const NUMERIC = new Set<string>(['Total (CAD)'])
const SKELETON_ROWS = 5
/** Below the theme's `sm` breakpoint (48em) the eight-column table doesn't fit: the queue shows as cards instead. */
const PHONE_QUERY = '(max-width: 47.99em)'

/** "Step 1, Department manager", and "Acting for Liam O'Connor" when the step is someone else's (delegation, P08). */
function YourStepCell({ bill }: { bill: BillSummary }) {
  const people = usePeople()
  const step = bill.current_step
  if (!step) return null
  return (
    <Stack gap={0}>
      <Text size="sm">{`Step ${step.step_no}, ${stepRoleLabel(step.role)}`}</Text>
      {step.delegated_from && (
        <Text size="xs" fw={600}>{`Acting for ${personName(step.delegated_from, people.data)}`}</Text>
      )}
    </Stack>
  )
}

/** One bill waiting for the signed-in user. */
function QueueRow({ bill }: { bill: BillSummary }) {
  return (
    <Table.Tr>
      <Table.Td>
        <Anchor component={Link} to={`/bills/${bill.bill_id}`} underline="hover" fw={500}>
          <Id>{bill.bill_id}</Id>
        </Anchor>
      </Table.Td>
      <Table.Td>{bill.vendor_name ?? <Text span c="dimmed" size="sm">No vendor matched</Text>}</Table.Td>
      <Table.Td><Id>{bill.vendor_invoice_number}</Id></Table.Td>
      <Table.Td><DateText value={bill.invoice_date} /></Table.Td>
      <Table.Td>{bill.due_date ? <DateText value={bill.due_date} /> : <Text span c="dimmed" size="sm">None</Text>}</Table.Td>
      <Table.Td data-numeric>
        <MoneyText value={bill.total_cad} align="right" />
        {bill.currency !== 'CAD' && (
          <Text size="xs" c="dimmed" ta="right">
            <MoneyText value={bill.total} currency={bill.currency} />
          </Text>
        )}
      </Table.Td>
      <Table.Td><OpenFlagsCell bill={bill} /></Table.Td>
      <Table.Td><YourStepCell bill={bill} /></Table.Td>
    </Table.Tr>
  )
}

/**
 * One bill as a card, for phones: the bill id, vendor, amount, why it is waiting for this user (their step, or whom
 * they act for) and any open flags, with Open to go to the bill, where Approve and Reject are.
 */
function QueueCard({ bill }: { bill: BillSummary }) {
  return (
    <Box component="li" p="sm" bg="white" style={{ border: '1px solid var(--app-border)', borderRadius: 4 }}>
      <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
        <Stack gap={4} style={{ minWidth: 0 }}>
          <Text size="sm" fw={500}><Id>{bill.bill_id}</Id></Text>
          <Text size="sm">{bill.vendor_name ?? <Text span c="dimmed" inherit>No vendor matched</Text>}</Text>
          <YourStepCell bill={bill} />
          <OpenFlagsCell bill={bill} />
        </Stack>
        <Stack gap="xs" align="flex-end">
          <Text size="sm" fw={500}><MoneyText value={bill.total_cad} /></Text>
          <Button component={Link} to={`/bills/${bill.bill_id}`} size="xs" variant="default"
            aria-label={`Open ${bill.bill_id}`}>
            Open
          </Button>
        </Stack>
      </Group>
    </Box>
  )
}

/** The queue as a list of cards (phones). */
function QueueCards({ bills, loading }: { bills: readonly BillSummary[] | undefined; loading: boolean }) {
  if (loading) return <Skeleton animate={false} height={96} />
  if (bills?.length === 0) return <Text size="sm" c="dimmed">No bills are waiting for your decision.</Text>
  return (
    <Stack component="ul" aria-label="My approvals" gap="xs" m={0} p={0} style={{ listStyle: 'none' }}>
      {bills?.map((bill) => <QueueCard key={bill.bill_id} bill={bill} />)}
    </Stack>
  )
}

/**
 * /approvals: the bills whose current approval step is the signed-in user's (GET /approvals/queue), in the server's
 * order (due date first), including steps they sign as someone's delegate. Each opens the bill screen, where the
 * Approve and Reject buttons are.
 */
export default function ApprovalsPage() {
  const user = useCurrentUser()
  const queue = useApprovalQueue()
  const bills = queue.data
  const phone = useMediaQuery(PHONE_QUERY)

  return (
    <Stack gap="md">
      <Title order={1}>My approvals</Title>
      {user.approval_limit_cad && (
        <Text size="sm" c="dimmed">
          {'Your approval limit is '}<MoneyText value={user.approval_limit_cad} />{'.'}
        </Text>
      )}
      {queue.isError ? (
        <ErrorAlert error={queue.error} title="Can't load your approvals" onRetry={() => void queue.refetch()} />
      ) : phone ? (
        <>
          {bills && bills.length > 0 && (
            <Text size="sm" c="dimmed">{`${bills.length} bill${bills.length === 1 ? '' : 's'} waiting`}</Text>
          )}
          <QueueCards bills={bills} loading={queue.isPending} />
        </>
      ) : (
        <>
          <Table.ScrollContainer minWidth={960} type="native">
            <Table aria-label="My approvals" bg="white" withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  {COLUMNS.map((column) => (
                    <Table.Th key={column} data-numeric={NUMERIC.has(column) || undefined}>{column}</Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {queue.isPending && Array.from({ length: SKELETON_ROWS }, (_, row) => (
                  <Table.Tr key={`skeleton-${row}`} aria-hidden>
                    {COLUMNS.map((column) => (
                      <Table.Td key={column}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>
                    ))}
                  </Table.Tr>
                ))}
                {bills?.length === 0 && (
                  <Table.Tr>
                    <Table.Td colSpan={COLUMNS.length}>
                      <Text size="sm" c="dimmed" py="xs">No bills are waiting for your decision.</Text>
                    </Table.Td>
                  </Table.Tr>
                )}
                {bills?.map((bill) => <QueueRow key={bill.bill_id} bill={bill} />)}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {bills && bills.length > 0 && (
            <Text size="sm" c="dimmed">{`${bills.length} bill${bills.length === 1 ? '' : 's'} waiting`}</Text>
          )}
        </>
      )}
    </Stack>
  )
}
