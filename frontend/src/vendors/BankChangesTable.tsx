import { Anchor, Skeleton, Stack, Table, Text, VisuallyHidden } from '@mantine/core'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { personName, usePeople } from '../api/reference'
import type { BankChange } from '../api/types'
import { accountEnding } from '../lib/accounts'
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
 * reader hears "Ending 7504 changed to Ending 9679". Accounts are always shown by their last four digits (lib/accounts),
 * even when the server sent the full number; the new account's institution and transit follow when it sent them.
 * Each account is its own text element.
 */
function AccountCell({ change }: { change: BankChange }) {
  // Each account line stays on one line ("→ Ending 9679", never "→ Ending" / "9679"); the column grows to fit it.
  const oneLine = { whiteSpace: 'nowrap' } as const
  return (
    <Stack gap={0}>
      <Text size="sm" style={oneLine}>{accountEnding(change.old_account_last4)}</Text>
      <Text size="sm" style={oneLine}>
        <span aria-hidden="true">{'→ '}</span>
        <VisuallyHidden component="span">changed to </VisuallyHidden>
        <Text span inherit>{accountEnding(change.new_account_last4)}</Text>
      </Text>
      {(change.new_institution || change.new_transit) && (
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
                  {/* The vendor by name, with its id linked under it, on the queue (the vendor page is the vendor). */}
                  {showVendor && (
                    <>
                      <Text size="sm">{change.vendor_name ?? change.vendor_id}</Text>
                      <Text size="xs">
                        <VisuallyHidden component="span">Vendor </VisuallyHidden>
                        <Anchor component={Link} to={`/vendors/${change.vendor_id}`} underline="hover" inherit>
                          <Id>{change.vendor_id}</Id>
                        </Anchor>
                      </Text>
                    </>
                  )}
                </Stack>
              </Table.Td>
              <Table.Td>
                <Stack gap={0}>
                  {/* A request from the dataset history has a date, not a time (stored as midnight UTC, which reads
                      as the evening before in Toronto): it shows the date alone. App requests show their time. */}
                  <Text size="sm">
                    {change.origin === 'history'
                      ? <DateText value={change.requested_at.slice(0, 10)} />
                      : <DateText value={change.requested_at} kind="timestamp" />}
                  </Text>
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
