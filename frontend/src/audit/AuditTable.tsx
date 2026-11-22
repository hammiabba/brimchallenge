import { ActionIcon, Anchor, Skeleton, Stack, Table, Text, VisuallyHidden } from '@mantine/core'
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react'
import { Fragment, useState } from 'react'
import { Link } from 'react-router'

import { codeAsWords, personName, usePeople } from '../api/reference'
import type { AuditEvent, Role } from '../api/types'
import { ROLE_LABELS } from '../auth/roles'
import { auditFieldLabel } from '../bills/auditText'
import { DateText, Id } from '../ui/DataText'
import { Icon } from '../ui/Icon'
import { auditLogActionLabel } from './filters'

/**
 * Six columns that fit the 752 px content column at 1024 px: the event's number sits under its time. Times are in
 * UTC, like the date filters and the CSV export.
 */
const COLUMNS = ['', 'When (UTC)', 'Who', 'Action', 'Entity', 'Comment'] as const
const MIN_WIDTH = 720
const SKELETON_ROWS = 10
const SYSTEM = 'system'

/** The pages an audited entity has, by entity type; other types are shown as plain ids. */
const ENTITY_PAGES: Partial<Record<string, (id: string) => string>> = {
  bill: (id) => `/bills/${id}`,
  payment: (id) => `/payments/${id}`,
  vendor: (id) => `/vendors/${id}`,
  email: (id) => `/inbox/${id}`,
}

/** A role code as the app words it ("Finance manager"); the system and unknown codes in words. */
function roleLabel(role: string): string {
  return (ROLE_LABELS as Record<string, string>)[role as Role] ?? codeAsWords(role)
}

/** The entity's id, linked to its page when it has one, with its type in words under it. */
function EntityCell({ event }: { event: AuditEvent }) {
  const page = ENTITY_PAGES[event.entity_type]
  return (
    <Stack gap={0}>
      {page
        ? <Anchor component={Link} to={page(event.entity_id)} underline="hover"><Id>{event.entity_id}</Id></Anchor>
        : <Id>{event.entity_id}</Id>}
      <Text size="xs" c="dimmed">{codeAsWords(event.entity_type)}</Text>
    </Stack>
  )
}

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
                <Table.Td>{auditFieldLabel(field)}</Table.Td>
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
        <Table.Td>
          <Stack gap={0}>
            <Text size="sm"><DateText value={event.at} kind="timestamp" timeZone="UTC" /></Text>
            <Text size="xs" c="dimmed">{`No. ${event.seq}`}</Text>
          </Stack>
        </Table.Td>
        <Table.Td>
          {/* The system acts as itself: one line, not "system / system". A person gets their role in words. */}
          {event.actor_user_id === SYSTEM ? <Text size="sm">System</Text> : (
            <Stack gap={0}>
              <Text size="sm">{personName(event.actor_user_id, people.data)}</Text>
              <Text size="xs" c="dimmed">
                {event.on_behalf_of
                  ? `${roleLabel(event.actor_role)}, for ${personName(event.on_behalf_of, people.data)}`
                  : roleLabel(event.actor_role)}
              </Text>
            </Stack>
          )}
        </Table.Td>
        <Table.Td>{auditLogActionLabel(event.action)}</Table.Td>
        <Table.Td><EntityCell event={event} /></Table.Td>
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
    <Table.ScrollContainer minWidth={MIN_WIDTH}>
      <Table aria-label="Audit log" bg="white" withTableBorder>
        <Table.Thead>
          <Table.Tr>
            {COLUMNS.map((column, index) => (
              <Table.Th key={column || index}>
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
