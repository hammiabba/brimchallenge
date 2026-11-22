import { Anchor, Skeleton, Stack, Table, Text } from '@mantine/core'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { personName, usePeople } from '../api/reference'
import type { BankChange } from '../api/types'
import { StatusBadge } from '../ui/Badges'
import { DateText, Id } from '../ui/DataText'
import { CHANNEL_LABELS } from './labels'

const SKELETON_ROWS = 5

/** "Account ending 4821", or the full number with its institution and transit when the server sent it unmasked. */
function NewAccountCell({ change }: { change: BankChange }) {
  if (change.new_account) {
    return (
      <Stack gap={0}>
        <Id>{change.new_account}</Id>
        <Text size="xs" c="dimmed">{`Institution ${change.new_institution ?? '?'}, transit ${change.new_transit ?? '?'}`}</Text>
      </Stack>
    )
  }
  return <Text size="sm">{`Ending ${change.new_account_last4}`}</Text>
}

interface BankChangesTableProps {
  changes: readonly BankChange[] | undefined
  loading: boolean
  emptyMessage: string
  label: string
  /** Show a vendor column (the queue lists every vendor; the vendor page doesn't need it). */
  showVendor?: boolean
  /** Extra cell at the end of each row, for actions. */
  actions?: (change: BankChange) => ReactNode
}

/**
 * Bank change requests: who asked, when and through which channel, the old and new account, and who verified or
 * rejected it. Account numbers are masked to the last 4 by the server for roles that may not see more.
 */
export function BankChangesTable({ changes, loading, emptyMessage, label, showVendor, actions }: BankChangesTableProps) {
  const people = usePeople()
  const columns = ['Change', ...(showVendor ? ['Vendor'] : []), 'Requested', 'Requested by', 'Channel', 'Old account',
    'New account', 'Status', 'Decided by', ...(actions ? ['Actions'] : [])]

  return (
    <Table.ScrollContainer minWidth={900}>
      <Table aria-label={label} bg="white" withTableBorder>
        <Table.Thead>
          <Table.Tr>{columns.map((column) => <Table.Th key={column}>{column}</Table.Th>)}</Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {loading && Array.from({ length: SKELETON_ROWS }, (_, row) => (
            <Table.Tr key={`skeleton-${row}`} aria-hidden>
              {columns.map((column) => (
                <Table.Td key={column}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>
              ))}
            </Table.Tr>
          ))}
          {!loading && changes?.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={columns.length}><Text size="sm" c="dimmed" py="xs">{emptyMessage}</Text></Table.Td>
            </Table.Tr>
          )}
          {!loading && changes?.map((change) => (
            <Table.Tr key={change.change_id}>
              <Table.Td><Id>{change.change_id}</Id></Table.Td>
              {showVendor && (
                <Table.Td>
                  <Anchor component={Link} to={`/vendors/${change.vendor_id}`} underline="hover">
                    <Id>{change.vendor_id}</Id>
                  </Anchor>
                </Table.Td>
              )}
              <Table.Td><DateText value={change.requested_at} kind="timestamp" /></Table.Td>
              <Table.Td>{change.requested_by ? personName(change.requested_by, people.data) : 'Not recorded'}</Table.Td>
              <Table.Td>{CHANNEL_LABELS[change.request_channel]}</Table.Td>
              <Table.Td>{change.old_account_last4 ? `Ending ${change.old_account_last4}` : 'None on file'}</Table.Td>
              <Table.Td><NewAccountCell change={change} /></Table.Td>
              <Table.Td><StatusBadge kind="bankChange" status={change.status} /></Table.Td>
              <Table.Td>
                {change.verified_by ? (
                  <Stack gap={0}>
                    <Text size="sm">{personName(change.verified_by, people.data)}</Text>
                    {change.verified_at && <Text size="xs" c="dimmed"><DateText value={change.verified_at} kind="timestamp" /></Text>}
                  </Stack>
                ) : null}
              </Table.Td>
              {actions && <Table.Td>{actions(change)}</Table.Td>}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
