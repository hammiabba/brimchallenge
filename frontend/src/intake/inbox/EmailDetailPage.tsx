import { Anchor, Box, Divider, Group, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import { Link, useParams } from 'react-router'

import { API_PREFIX } from '../../api/client'
import { ApiError } from '../../api/errors'
import { ErrorAlert } from '../../api/ErrorAlert'
import { useBill } from '../../bills/queries'
import { SURFACE } from '../../theme'
import { StatusBadge } from '../../ui/Badges'
import { DateText, Id } from '../../ui/DataText'
import { EmailClassBadge, IntakeStatusBadge } from '../common/IntakeBadges'
import { asIntakeStatus } from '../common/labels'
import type { EmailDetail } from '../common/types'
import { useEmail } from './queries'
import { SuggestedActionView } from './SuggestedActionView'

/** A bill made from the email, with its current status. */
function LinkedBill({ billId }: { billId: string }) {
  const bill = useBill(billId)
  return (
    <Group gap="sm">
      <Anchor component={Link} to={`/bills/${billId}`} underline="hover" fw={500}><Id>{billId}</Id></Anchor>
      {bill.data && <StatusBadge kind="bill" status={bill.data.status} />}
      {bill.data?.vendor_name && <Text size="sm">{bill.data.vendor_name}</Text>}
    </Group>
  )
}

/** An attachment's intake status; "Not read" before intake has seen it. */
function AttachmentStatus({ status }: { status: string | undefined }) {
  const known = status ? asIntakeStatus(status) : null
  if (known) return <IntakeStatusBadge status={known} />
  return <Text size="sm" c="dimmed">{status ?? 'Not read'}</Text>
}

/** Each attachment: a link to the original file once intake has read it, its status, and why it failed if it did. */
function Attachments({ email }: { email: EmailDetail }) {
  if (email.attachments.length === 0) return <Text size="sm" c="dimmed">No attachments.</Text>
  return (
    <Table aria-label="Attachments" bg="white" withTableBorder>
      <Table.Thead><Table.Tr><Table.Th>File</Table.Th><Table.Th>Status</Table.Th><Table.Th>Bill</Table.Th></Table.Tr></Table.Thead>
      <Table.Tbody>
        {email.attachments.map((name) => {
          const item = email.items.find((i) => i.file_name === name)
          return (
            <Table.Tr key={name}>
              <Table.Td>
                {item?.file_hash ? (
                  <Anchor href={`${API_PREFIX}/intake/files/${item.file_hash}`} target="_blank" rel="noopener" size="sm">{name}</Anchor>
                ) : <Text size="sm">{name}</Text>}
                {item?.error && <Text size="xs" c="dimmed">{item.error}</Text>}
              </Table.Td>
              <Table.Td><AttachmentStatus status={item?.status} /></Table.Td>
              <Table.Td>
                {item?.bill_id && (
                  <Anchor component={Link} to={`/bills/${item.bill_id}`} underline="hover"><Id>{item.bill_id}</Id></Anchor>
                )}
              </Table.Td>
            </Table.Tr>
          )
        })}
      </Table.Tbody>
    </Table>
  )
}

/** Placeholder blocks while the email loads (static). */
function DetailSkeleton() {
  return (
    <Stack gap="md" aria-busy="true" aria-label="Loading email">
      <Skeleton animate={false} height={28} width={320} />
      <Skeleton animate={false} height={60} />
      <Skeleton animate={false} height={160} />
    </Stack>
  )
}

/**
 * /inbox/:emailId: one inbox email in full (GET /intake/emails/{email_id}): who sent it, how it was sorted and why,
 * the suggested next step with any ready reply, its attachments and the bills made from it, then the email itself.
 */
export default function EmailDetailPage() {
  const { emailId = '' } = useParams()
  const email = useEmail(emailId)
  const back = <Anchor component={Link} to="/inbox" size="sm" w="fit-content">Back to inbox</Anchor>

  if (email.isPending) return <DetailSkeleton />
  if (email.error instanceof ApiError && email.error.status === 404) {
    return (
      <Stack gap="sm" maw={720}>
        <Title order={1}>Email not found</Title>
        <Text>There is no email <Id>{emailId}</Id> in the inbox.</Text>
        {back}
      </Stack>
    )
  }
  if (email.isError) {
    return <ErrorAlert error={email.error} title="Can't load this email" onRetry={() => void email.refetch()} />
  }

  const data = email.data
  return (
    <Stack gap="lg" maw={1000}>
      {back}
      <Stack gap="xs">
        <Group gap="sm">
          <Id>{data.email_id}</Id>
          <EmailClassBadge emailClass={data.email_class} />
        </Group>
        <Title order={1}>{data.subject}</Title>
        <Text size="sm">
          From {data.from_name ? `${data.from_name} <${data.from_address}>` : data.from_address}, received{' '}
          <DateText value={data.received_at} kind="timestamp" />
        </Text>
      </Stack>

      {/* Only a sorted email explains its sorting. An unsorted one says where it gets sorted: the Inbox page's run. */}
      {data.triage_reason ? (
        <Stack gap="xs">
          <Title order={2}>Why it was sorted this way</Title>
          <Text>{data.triage_reason}</Text>
        </Stack>
      ) : (
        <Text size="sm" c="dimmed">
          {'Not sorted yet. '}
          <Anchor component={Link} to="/inbox" inherit>Run the inbox</Anchor>
          {' to sort it.'}
        </Text>
      )}

      {data.suggested_action && (
        <Stack gap="xs">
          <Title order={2}>Suggested action</Title>
          <SuggestedActionView action={data.suggested_action} />
        </Stack>
      )}

      <Stack gap="xs">
        <Title order={2}>Attachments</Title>
        <Attachments email={data} />
      </Stack>

      {data.bill_ids.length > 0 && (
        <Stack gap="xs">
          <Title order={2}>Bills</Title>
          {data.bill_ids.map((billId) => <LinkedBill key={billId} billId={billId} />)}
        </Stack>
      )}

      <Divider />
      <Stack gap="xs">
        <Title order={2}>Email</Title>
        <Box component="pre" m={0} p="sm" bg="white"
          style={{ border: `1px solid ${SURFACE.border}`, borderRadius: 4, whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 14 }}>
          {data.body}
        </Box>
      </Stack>
    </Stack>
  )
}
