import { Button, Group, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import { IconUpload } from '@tabler/icons-react'
import { Link } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import { DateText } from '../ui/DataText'
import { Icon } from '../ui/Icon'
import { IntakeStatusBadge } from './IntakeStatusBadge'
import { BillLink, ItemNotes } from './ItemCells'
import { useMySubmissions } from './queries'
import { isPending } from './status'

const COLUMNS = ['File', 'Submitted', 'Status', 'Bill', 'Notes'] as const

/**
 * /submissions: every file the signed-in user submitted, with its status and the bill it became. While any file is
 * queued or processing the list refreshes every two seconds.
 */
export default function SubmissionsPage() {
  const submissions = useMySubmissions()
  const items = submissions.data ?? []
  const working = items.filter((item) => isPending(item.status)).length

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <Title order={1}>My submissions</Title>
        <Button component={Link} to="/submit" leftSection={<Icon icon={IconUpload} />}>Submit invoice</Button>
      </Group>
      {working > 0 && <Text size="sm">{`${working} file${working === 1 ? ' is' : 's are'} still being read. This list updates by itself.`}</Text>}
      {submissions.isError ? (
        <ErrorAlert error={submissions.error} title="Can't load your submissions" onRetry={() => void submissions.refetch()} />
      ) : (
        <Table.ScrollContainer minWidth={800}>
          <Table aria-label="My submissions" bg="white" withTableBorder>
            <Table.Thead>
              <Table.Tr>{COLUMNS.map((column) => <Table.Th key={column}>{column}</Table.Th>)}</Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {submissions.isPending && Array.from({ length: 5 }, (_, row) => (
                <Table.Tr key={`skeleton-${row}`} aria-hidden>
                  {COLUMNS.map((column) => <Table.Td key={column}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>)}
                </Table.Tr>
              ))}
              {!submissions.isPending && items.length === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={COLUMNS.length}>
                    <Text size="sm" c="dimmed" py="xs">You haven't submitted any invoices yet.</Text>
                  </Table.Td>
                </Table.Tr>
              )}
              {items.map((item) => (
                <Table.Tr key={item.item_id}>
                  <Table.Td>{item.file_name}</Table.Td>
                  <Table.Td><DateText value={item.created_at} kind="timestamp" /></Table.Td>
                  <Table.Td><IntakeStatusBadge status={item.status} /></Table.Td>
                  <Table.Td><BillLink billId={item.bill_id} pending={isPending(item.status)} /></Table.Td>
                  <Table.Td><ItemNotes item={item} /></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  )
}
