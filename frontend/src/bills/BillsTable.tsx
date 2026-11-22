import { Anchor, Group, Skeleton, Stack, Table, Text } from '@mantine/core'
import { Link } from 'react-router'

import { codeAsWords, personName, useFlagHelp, usePeople } from '../api/reference'
import type { BillSummary, CurrentStep } from '../api/types'
import { SeverityCountBadge, StatusBadge } from '../ui/Badges'
import { DateText, Id, MoneyText } from '../ui/DataText'
import { stepRoleLabel } from './labels'

const COLUMNS = ['Bill', 'Vendor', 'Invoice no.', 'Invoice date', 'Total (CAD)', 'Status', 'Open flags', 'Top flag',
  'Current step'] as const
const NUMERIC = new Set<string>(['Total (CAD)'])
const SKELETON_ROWS = 8

/** "Step 1, Department manager: Morgan Lee", plus "delegate for Sam Rivera" when the step is delegated. */
function CurrentStepCell({ step }: { step: CurrentStep | null | undefined }) {
  const people = usePeople()
  if (!step) return null
  return (
    <Stack gap={0}>
      <Text size="sm">{`Step ${step.step_no}, ${stepRoleLabel(step.role)}: ${personName(step.user_id, people.data)}`}</Text>
      {step.delegated_from && (
        <Text size="xs" c="dimmed">{`delegate for ${personName(step.delegated_from, people.data)}`}</Text>
      )}
    </Stack>
  )
}

/** The open-flag counts as small severity badges; nothing when no flag is open. Also used by the approval queues. */
export function OpenFlagsCell({ bill }: { bill: BillSummary }) {
  const counts = bill.open_flags ?? { block: 0, warn: 0, info: 0 }
  return (
    <Group gap={4} wrap="nowrap">
      <SeverityCountBadge severity="block" count={counts.block ?? 0} />
      <SeverityCountBadge severity="warn" count={counts.warn ?? 0} />
      <SeverityCountBadge severity="info" count={counts.info ?? 0} />
    </Group>
  )
}

/** One bill row. */
function BillRow({ bill }: { bill: BillSummary }) {
  const flagHelp = useFlagHelp()
  const topFlag = bill.top_flag_code ? (flagHelp.data?.[bill.top_flag_code]?.title ?? codeAsWords(bill.top_flag_code)) : null
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
      <Table.Td data-numeric>
        <MoneyText value={bill.total_cad} align="right" />
        {bill.currency !== 'CAD' && (
          <Text size="xs" c="dimmed" ta="right">
            <MoneyText value={bill.total} currency={bill.currency} />
          </Text>
        )}
      </Table.Td>
      <Table.Td><StatusBadge kind="bill" status={bill.status} /></Table.Td>
      <Table.Td><OpenFlagsCell bill={bill} /></Table.Td>
      <Table.Td>{topFlag}</Table.Td>
      <Table.Td><CurrentStepCell step={bill.current_step} /></Table.Td>
    </Table.Tr>
  )
}

interface BillsTableProps {
  bills: readonly BillSummary[] | undefined
  /** True on the first load (no rows yet): skeleton rows are shown. */
  loading: boolean
  /** One line shown when the list is empty. */
  emptyMessage: string
  /** The table's accessible name. */
  label: string
}

/**
 * The dense bills table used by the bills list and the review queue. Rows come from GET /bills in the server's
 * order; nothing is sorted or filtered here.
 */
export function BillsTable({ bills, loading, emptyMessage, label }: BillsTableProps) {
  return (
    <Table.ScrollContainer minWidth={1100}>
      <Table aria-label={label} bg="white" withTableBorder>
        <Table.Thead>
          <Table.Tr>
            {COLUMNS.map((column) => (
              <Table.Th key={column} data-numeric={NUMERIC.has(column) || undefined}>{column}</Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {loading && Array.from({ length: SKELETON_ROWS }, (_, row) => (
            <Table.Tr key={`skeleton-${row}`} aria-hidden>
              {COLUMNS.map((column) => (
                <Table.Td key={column}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>
              ))}
            </Table.Tr>
          ))}
          {!loading && bills?.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={COLUMNS.length}>
                <Text size="sm" c="dimmed" py="xs">{emptyMessage}</Text>
              </Table.Td>
            </Table.Tr>
          )}
          {!loading && bills?.map((bill) => <BillRow key={bill.bill_id} bill={bill} />)}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
