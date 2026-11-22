import { ActionIcon, Anchor, Box, Button, Group, Stack, Table, Text, Title } from '@mantine/core'
import { IconUpload, IconX } from '@tabler/icons-react'
import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type DragEvent } from 'react'
import { Link } from 'react-router'

import { ApiError } from '../../api/errors'
import { BRAND, SURFACE } from '../../theme'
import { Id } from '../../ui/DataText'
import { Icon } from '../../ui/Icon'
import { IntakeStatusBadge } from '../common/IntakeBadges'
import { SUBMISSIONS_KEY, alreadyReceivedBill, submitFile, useMySubmissions } from '../common/queries'
import type { IntakeItem } from '../common/types'
import { ACCEPT, fileProblem } from './fileChecks'

/** One chosen file and what happened to it. */
type Row =
  | { key: number; file: File; phase: 'ready' }
  | { key: number; file: File; phase: 'rejected'; reason: string }
  | { key: number; file: File; phase: 'sending' }
  | { key: number; file: File; phase: 'sent'; item: IntakeItem }
  | { key: number; file: File; phase: 'refused'; error: ApiError | null }

/** A link to a bill, in mono. */
function BillLink({ billId }: { billId: string }) {
  return (
    <Anchor component={Link} to={`/bills/${billId}`} underline="hover">
      <Id>{billId}</Id>
    </Anchor>
  )
}

/** What became of a submitted file, in one line: the bill, the bill it was already received as, or why it failed. */
function SentResult({ item }: { item: IntakeItem }) {
  const existing = alreadyReceivedBill(item)
  if (existing) {
    return <Text size="sm">Already received as <BillLink billId={existing} />. No new bill was made.</Text>
  }
  if (item.status === 'failed' || item.status === 'llm_skipped') {
    return <Text size="sm">{item.error ?? 'The file could not be read.'}</Text>
  }
  if (item.bill_id) return <Text size="sm">Bill <BillLink billId={item.bill_id} /> is waiting for AP review.</Text>
  if (item.status === 'ok') return <Text size="sm">Read, but no bill was made.</Text>
  return <Text size="sm" c="dimmed">Reading the invoice.</Text>
}

/** The status and result cells of one row. */
function RowCells({ row, live }: { row: Row; live: IntakeItem | undefined }) {
  switch (row.phase) {
    case 'ready':
      return <><Table.Td><Text size="sm">Ready to send</Text></Table.Td><Table.Td /></>
    case 'rejected':
      return <><Table.Td><Text size="sm">Not sent</Text></Table.Td><Table.Td><Text size="sm">{row.reason}</Text></Table.Td></>
    case 'sending':
      return <><Table.Td><Text size="sm">Uploading</Text></Table.Td><Table.Td /></>
    case 'refused':
      return (
        <>
          <Table.Td><Text size="sm">Not accepted</Text></Table.Td>
          <Table.Td>
            <Text size="sm">{row.error?.message ?? 'The upload failed.'}</Text>
            {row.error?.request_id && <Text size="xs" c="dimmed" ff="monospace">Request id: {row.error.request_id}</Text>}
          </Table.Td>
        </>
      )
    case 'sent': {
      const item = live ?? row.item
      return <><Table.Td><IntakeStatusBadge status={item.status} /></Table.Td><Table.Td><SentResult item={item} /></Table.Td></>
    }
  }
}

/**
 * /submit: send one or more invoice files (PDF or image) to AP. Each file is one POST /submissions; the result of
 * each is followed by polling GET /submissions until it is final. File type and size are checked here only for
 * quick feedback: the server checks them again and its answer is shown.
 */
export default function SubmitPage() {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const nextKey = useRef(0)
  const [rows, setRows] = useState<Row[]>([])
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)

  const anySent = rows.some((row) => row.phase === 'sent')
  const submissions = useMySubmissions(anySent)
  const live = new Map((submissions.data ?? []).map((item) => [item.item_id, item]))
  const ready = rows.filter((row) => row.phase === 'ready')

  function addFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    const added: Row[] = Array.from(files, (file) => {
      const key = nextKey.current++
      const reason = fileProblem(file)
      return reason ? { key, file, phase: 'rejected', reason } : { key, file, phase: 'ready' }
    })
    setRows((current) => [...current.filter((row) => row.phase !== 'rejected'), ...added])
  }

  function update(key: number, next: Row) {
    setRows((current) => current.map((row) => (row.key === key ? next : row)))
  }

  async function submit() {
    setUploading(true)
    for (const row of ready) {
      update(row.key, { key: row.key, file: row.file, phase: 'sending' })
      try {
        const item = await submitFile(row.file)
        update(row.key, { key: row.key, file: row.file, phase: 'sent', item })
      } catch (error) {
        update(row.key, { key: row.key, file: row.file, phase: 'refused', error: error instanceof ApiError ? error : null })
      }
    }
    setUploading(false)
    await queryClient.invalidateQueries({ queryKey: SUBMISSIONS_KEY })
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    if (!uploading) addFiles(event.dataTransfer.files)
  }

  return (
    <Stack gap="md" maw={960}>
      <Title order={1}>Submit invoice</Title>
      <Box
        data-testid="drop-zone"
        onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        p="xl"
        bg={dragging ? SURFACE.primaryTint : 'white'}
        style={{ border: `1px dashed ${dragging ? BRAND.blumine : SURFACE.controlBorder}`, borderRadius: 4 }}
      >
        <Stack gap="sm" align="center">
          <Text size="sm">Drop PDF or image files here, up to 10 MB each, or choose them.</Text>
          <input
            ref={input}
            type="file"
            multiple
            accept={ACCEPT}
            aria-label="Invoice files"
            hidden
            onChange={(event) => { addFiles(event.currentTarget.files); event.currentTarget.value = '' }}
          />
          <Button variant="default" leftSection={<Icon icon={IconUpload} />} onClick={() => input.current?.click()}
            disabled={uploading}>
            Choose files
          </Button>
        </Stack>
      </Box>

      {rows.length > 0 && (
        <Table aria-label="Files" bg="white" withTableBorder>
          <Table.Thead>
            <Table.Tr><Table.Th>File</Table.Th><Table.Th>Status</Table.Th><Table.Th>Result</Table.Th><Table.Th /></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.key}>
                <Table.Td><Text size="sm" style={{ overflowWrap: 'anywhere' }}>{row.file.name}</Text></Table.Td>
                <RowCells row={row} live={row.phase === 'sent' ? live.get(row.item.item_id) : undefined} />
                <Table.Td w={40}>
                  {(row.phase === 'ready' || row.phase === 'rejected') && !uploading && (
                    <ActionIcon variant="subtle" color="gray" aria-label={`Remove ${row.file.name}`}
                      onClick={() => setRows((current) => current.filter((r) => r.key !== row.key))}>
                      <Icon icon={IconX} />
                    </ActionIcon>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Group justify="space-between">
        <Button onClick={() => void submit()} disabled={uploading || ready.length === 0}>
          {uploading ? 'Uploading' : ready.length > 1 ? `Submit ${ready.length} files` : 'Submit'}
        </Button>
        {anySent && <Anchor component={Link} to="/submissions" size="sm">See all in My submissions</Anchor>}
      </Group>
    </Stack>
  )
}
