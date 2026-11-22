import { Anchor, Skeleton, Stack, Table, Text, VisuallyHidden } from '@mantine/core'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { personName, usePeople } from '../api/reference'
import type { BankChange } from '../api/types'
import { StatusBadge } from '../ui/Badges'
import { DateText, Id } from '../ui/DataText'
import { CHANNEL_LABELS } from './labels'

const SKELETON_ROWS = 5
/**
 * Five or six columns, fitting the 1008 px content column at 1280 px. Like the Payments list, secondary details sit
 * under the main value in the same cell: the vendor under the change id, who asked and how under the request time,
 * the new account under the old one. Below this width the table scrolls sideways.
 */
const MIN_WIDTH = 720

/**
 * The old account, then the new one under it: "Ending 7504" / "→ Ending 9679". The arrow is decoration; a screen
 * reader hears "Ending 7504 changed to Ending 9679". The new account is the full number, with its institution and
 * transit, when the server sent it unmasked. Each account is its own text element.
 */
function AccountCell({ change }: { change: BankChange }) {
  // Each account line stays on one line ("→ Ending 9679", never "→ Ending" / "9679"); the column grows to fit it.
  const oneLine = { whiteSpace: 'nowrap' } as const
  return (
    <Stack gap={0}>
      <Text size="sm" style={oneLine}>{change.old_account_last4 ? `Ending ${change.old_account_last4}` : 'None on file'}</Text>
      <Text size="sm" style={oneLine}>
        <span aria-hidden="true">{'→ '}</span>
        <VisuallyHidden component="span">changed to </VisuallyHidden>
        {change.new_account ? <Id>{change.new_account}</Id> : <Text span inherit>{`Ending ${change.new_account_last4}`}</Text>}
      </Text>
      {change.new_account && (
        <Text size="xs" c="dimmed">{`Institution ${change.new_institution ?? '?'}, transit ${change.new_transit ?? '?'}`}</Text>
      )}
    </Stack>
  )
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
 * Bank change requests: the change (and its vendor, on the queue), when it was asked for, by whom and through which
 * channel, the old and new account, its status, and who verified or rejected it. Account numbers are masked to the
 * last 4 by the server for roles that may not see more.
 */
export function BankChangesTable({ changes, loading, emptyMessage, label, showVendor, actions }: BankChangesTableProps) {
  const people = usePeople()
  const columns = ['Change', 'Requested', 'Account', 'Status', 'Decided by', ...(actions ? ['Actions'] : [])]

  return (
    <Table.ScrollContainer minWidth={MIN_WIDTH}>
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
              <Table.Td>
                <Stack gap={0}>
                  <Id>{change.change_id}</Id>
                  {showVendor && (
                    <Text size="xs">
                      <VisuallyHidden component="span">Vendor </VisuallyHidden>
                      <Anchor component={Link} to={`/vendors/${change.vendor_id}`} underline="hover" inherit>
                        <Id>{change.vendor_id}</Id>
                      </Anchor>
                    </Text>
                  )}
                </Stack>
              </Table.Td>
              <Table.Td>
                <Stack gap={0}>
                  <Text size="sm"><DateText value={change.requested_at} kind="timestamp" /></Text>
                  <Text size="xs" c="dimmed">
                    <span>{change.requested_by ? personName(change.requested_by, people.data) : 'Not recorded'}</span>
                    {' · '}
                    <span>{CHANNEL_LABELS[change.request_channel]}</span>
                  </Text>
                </Stack>
              </Table.Td>
              <Table.Td><AccountCell change={change} /></Table.Td>
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
