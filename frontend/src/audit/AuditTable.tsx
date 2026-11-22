import { ActionIcon, Skeleton, Stack, Table, Text, VisuallyHidden } from '@mantine/core'
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react'
import { Fragment, useState } from 'react'

import { personName, usePeople } from '../api/reference'
import type { AuditEvent } from '../api/types'
import { DateText, Id } from '../ui/DataText'
import { Icon } from '../ui/Icon'

const COLUMNS = ['', 'Seq', 'When', 'Who', 'Action', 'Entity', 'Comment'] as const
const SKELETON_ROWS = 10

/** A recorded value as text: strings as they are, everything else as compact JSON. */
function show(value: unknown): string {
  if (value === undefined) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

/** What changed: every field in before or after, with both values. Plain text only. */
function ChangeTable({ event }: { event: AuditEvent }) {
  const before = event.before ?? {}
  const after = event.after ?? {}
  const fields = [...new Set([...Object.keys(before), ...Object.keys(after)])]
  return (
    <Stack gap="xs" py="xs">
      {fields.length === 0 ? (
        <Text size="sm" c="dimmed">No field values were recorded for this event.</Text>
      ) : (
        <Table aria-label={`Changes in event ${event.seq}`} withTableBorder>
          <Table.Thead>
            <Table.Tr><Table.Th>Field</Table.Th><Table.Th>Before</Table.Th><Table.Th>After</Table.Th></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {fields.map((field) => (
              <Table.Tr key={field}>
                <Table.Td><Id>{field}</Id></Table.Td>
                <Table.Td><Text size="sm" style={{ wordBreak: 'break-word' }}>{show(before[field])}</Text></Table.Td>
                <Table.Td><Text size="sm" style={{ wordBreak: 'break-word' }}>{show(after[field])}</Text></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      <Text size="xs" c="dimmed" ff="monospace">
        {`Event ${event.event_id}${event.request_id ? `, request ${event.request_id}` : ''}`}
      </Text>
    </Stack>
  )
}

/** One event, with a toggle that shows what changed. */
function EventRow({ event }: { event: AuditEvent }) {
  const people = usePeople()
  const [open, setOpen] = useState(false)
  return (
    <Fragment>
      <Table.Tr data-selected={open || undefined}>
        <Table.Td w={36}>
          <ActionIcon
            variant="subtle"
            size="sm"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-label={`${open ? 'Hide' : 'Show'} changes in event ${event.seq}`}
          >
            <Icon icon={open ? IconChevronDown : IconChevronRight} size={16} />
          </ActionIcon>
        </Table.Td>
        <Table.Td data-numeric>{event.seq}</Table.Td>
        <Table.Td><DateText value={event.at} kind="timestamp" /></Table.Td>
        <Table.Td>
          <Stack gap={0}>
            <Text size="sm">{personName(event.actor_user_id, people.data)}</Text>
            <Text size="xs" c="dimmed">
              {event.on_behalf_of ? `${event.actor_role}, for ${personName(event.on_behalf_of, people.data)}` : event.actor_role}
            </Text>
          </Stack>
        </Table.Td>
        <Table.Td><Id>{event.action}</Id></Table.Td>
        <Table.Td>
          <Stack gap={0}>
            <Id>{event.entity_id}</Id>
            <Text size="xs" c="dimmed">{event.entity_type}</Text>
          </Stack>
        </Table.Td>
        <Table.Td><Text size="sm">{event.comment ?? ''}</Text></Table.Td>
      </Table.Tr>
      {open && (
        <Table.Tr>
          <Table.Td />
          <Table.Td colSpan={COLUMNS.length - 1}><ChangeTable event={event} /></Table.Td>
        </Table.Tr>
      )}
    </Fragment>
  )
}

interface AuditTableProps {
  events: readonly AuditEvent[] | undefined
  loading: boolean
  emptyMessage: string
}

/** Audit events in the server's order (oldest first), each expandable to show its before and after values. */
export function AuditTable({ events, loading, emptyMessage }: AuditTableProps) {
  return (
    <Table.ScrollContainer minWidth={1000}>
      <Table aria-label="Audit log" bg="white" withTableBorder>
        <Table.Thead>
          <Table.Tr>
            {COLUMNS.map((column, index) => (
              <Table.Th key={column || index} data-numeric={column === 'Seq' || undefined}>
                {column || <VisuallyHidden>Details</VisuallyHidden>}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {loading && Array.from({ length: SKELETON_ROWS }, (_, row) => (
            <Table.Tr key={`skeleton-${row}`} aria-hidden>
              {COLUMNS.map((column, index) => (
                <Table.Td key={column || index}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>
              ))}
            </Table.Tr>
          ))}
          {!loading && events?.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={COLUMNS.length}><Text size="sm" c="dimmed" py="xs">{emptyMessage}</Text></Table.Td>
            </Table.Tr>
          )}
          {!loading && events?.map((event) => <EventRow key={event.seq} event={event} />)}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
