import { Box, Button, Group, Stack, Table, Text, Title } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react'
import { useMemo } from 'react'

import { codeAsWords, personFor, useFlagHelp, usePeople } from '../../api/reference'
import type { AuditEvent, BillDetail } from '../../api/types'
import { DateText } from '../../ui/DataText'
import { Icon } from '../../ui/Icon'
import { auditActor, auditChanges, auditSentence, type AuditChange, type AuditContext } from '../auditText'
import { auditActionLabel } from '../labels'

/** The changes as "label: before → after" (or "label: value") rows, one line per value. */
function ChangeRows({ rows }: { rows: AuditChange[] }) {
  return (
    <Stack component="dl" gap={2} m={0}>
      {rows.map((row) => (
        <Group key={row.key} gap={4} wrap="nowrap" align="flex-start">
          <Text component="dt" size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>{`${row.label}:`}</Text>
          <Text component="dd" size="xs" m={0} style={{ overflowWrap: 'anywhere' }}>
            {row.before && <>{row.before.join(', ')}{' → '}</>}
            {(row.after ?? ['none']).join(', ')}
          </Text>
        </Group>
      ))}
    </Stack>
  )
}

/**
 * One event's details: a sentence for the common actions, with "Show changes" for the before/after values; for any
 * other action, the values themselves. The comment, if any, on its own line.
 */
function EventDetails({ event, context }: { event: AuditEvent; context: AuditContext }) {
  const [open, { toggle }] = useDisclosure(false)
  const sentence = auditSentence(event, context)
  const rows = auditChanges(event, context)
  const changesId = `audit-changes-${event.seq}`
  return (
    <Stack gap={2}>
      {sentence ? <Text size="sm">{sentence}</Text> : <ChangeRows rows={rows} />}
      {event.comment && <Text size="sm" c="dimmed" style={{ overflowWrap: 'anywhere' }}>{`Comment: ${event.comment}`}</Text>}
      {sentence && rows.length > 0 && (
        <>
          <Button
            variant="subtle"
            size="compact-xs"
            w="fit-content"
            leftSection={<Icon icon={open ? IconChevronDown : IconChevronRight} size={12} />}
            onClick={toggle}
            aria-expanded={open}
            aria-controls={changesId}
          >
            {open ? 'Hide changes' : 'Show changes'}
          </Button>
          <Box id={changesId} hidden={!open}>
            <ChangeRows rows={rows} />
          </Box>
        </>
      )}
    </Stack>
  )
}

/**
 * The bill's own audit history (BillDetail.audit, returned for every role that can see the bill), collapsed by
 * default; the button shows or hides it at once (no animation). Each event says who, when, what, in a sentence for
 * the common actions, with the before/after values behind "Show changes". The payment screen reuses it for
 * PaymentDetail.audit (the payment's events and its bill's).
 */
export function AuditTrail({ bill, emptyMessage = 'No audit events for this bill yet.' }: {
  bill: Pick<BillDetail, 'audit'>
  emptyMessage?: string
}) {
  const [open, { toggle }] = useDisclosure(false)
  const people = usePeople()
  const flagHelp = useFlagHelp()
  const events = bill.audit
  const count = `${events.length} event${events.length === 1 ? '' : 's'}`

  const context = useMemo<AuditContext>(() => ({
    personLabel: (userId) => {
      const person = personFor(userId, people.data)
      return person ? `${person.full_name} (${userId})` : userId
    },
    flagTitle: (code) => flagHelp.data?.[code]?.title ?? codeAsWords(code),
  }), [people.data, flagHelp.data])

  return (
    <Stack gap="sm">
      <Group gap="sm" align="center">
        <Title order={2}>Audit trail</Title>
        {events.length > 0 && (
          <Button
            variant="subtle"
            size="compact-sm"
            leftSection={<Icon icon={open ? IconChevronDown : IconChevronRight} size={14} />}
            onClick={toggle}
            aria-expanded={open}
            aria-controls="bill-audit-trail"
          >
            {open ? `Hide ${count}` : `Show ${count}`}
          </Button>
        )}
      </Group>
      {events.length === 0 && <Text size="sm">{emptyMessage}</Text>}
      {events.length > 0 && (
        <Box id="bill-audit-trail" hidden={!open}>
          <Table.ScrollContainer minWidth={720}>
            <Table aria-label="Audit trail" withTableBorder bg="white" stickyHeader={false}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>When</Table.Th>
                  <Table.Th>Who</Table.Th>
                  <Table.Th>Action</Table.Th>
                  <Table.Th>Details</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {events.map((event) => {
                  const actor = auditActor(event, context)
                  return (
                    <Table.Tr key={event.seq}>
                      <Table.Td style={{ verticalAlign: 'top' }}><DateText value={event.at} kind="timestamp" /></Table.Td>
                      <Table.Td style={{ verticalAlign: 'top' }}>
                        <Text size="sm">{actor.who}</Text>
                        {actor.onBehalfOf && <Text size="xs" c="dimmed">{`on behalf of ${actor.onBehalfOf}`}</Text>}
                      </Table.Td>
                      <Table.Td style={{ verticalAlign: 'top' }}>{auditActionLabel(event.action)}</Table.Td>
                      <Table.Td style={{ verticalAlign: 'top' }}><EventDetails event={event} context={context} /></Table.Td>
                    </Table.Tr>
                  )
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Box>
      )}
    </Stack>
  )
}
