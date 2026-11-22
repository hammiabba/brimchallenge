import { Box, Button, Group, Stack, Table, Text, Title } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react'

import { personName, usePeople } from '../../api/reference'
import type { BillDetail } from '../../api/types'
import { DateText } from '../../ui/DataText'
import { Icon } from '../../ui/Icon'
import { auditActionLabel, auditDetails } from '../labels'

/**
 * The bill's own audit history (BillDetail.audit, returned for every role that can see the bill), collapsed by
 * default; the button shows or hides it at once (no animation). Events are shown as plain text: who, when, what and
 * what changed. The payment screen reuses it for PaymentDetail.audit (the payment's events and its bill's).
 */
export function AuditTrail({ bill, emptyMessage = 'No audit events for this bill yet.' }: {
  bill: Pick<BillDetail, 'audit'>
  emptyMessage?: string
}) {
  const [open, { toggle }] = useDisclosure(false)
  const people = usePeople()
  const events = bill.audit
  const count = `${events.length} event${events.length === 1 ? '' : 's'}`

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
              {events.map((event) => (
                <Table.Tr key={event.seq}>
                  <Table.Td><DateText value={event.at} kind="timestamp" /></Table.Td>
                  <Table.Td>
                    {personName(event.actor_user_id, people.data)}
                    {event.on_behalf_of && (
                      <Text size="xs" c="dimmed">{`on behalf of ${personName(event.on_behalf_of, people.data)}`}</Text>
                    )}
                  </Table.Td>
                  <Table.Td>{auditActionLabel(event.action)}</Table.Td>
                  <Table.Td><Text size="sm" style={{ wordBreak: 'break-word' }}>{auditDetails(event)}</Text></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Box>
      )}
    </Stack>
  )
}
