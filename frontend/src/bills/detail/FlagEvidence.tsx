import { Anchor, Group, List, SimpleGrid, Stack, Table, Text } from '@mantine/core'
import { Fragment } from 'react'
import { Link } from 'react-router'

import type { DuplicateMatch } from '../../api/types'
import { accountEnding } from '../../lib/accounts'
import { DateText, Id, MoneyText } from '../../ui/DataText'
import { classifyEvidence, type EvidenceBlock, type EvidenceValue } from '../evidence'
import { bankChannelLabel, duplicateKindLabel, similarityText } from '../labels'

/** One evidence value: money, a date, a mono id, plain text (never HTML), or a comma-separated list. */
export function EvidenceValueView({ value }: { value: EvidenceValue }) {
  switch (value.kind) {
    case 'money':
      return <MoneyText value={value.value} currency={value.currency} />
    case 'date':
      return <DateText value={value.value} />
    case 'id':
      // A bank-change id opens the bank changes list, where it can be verified or rejected.
      return value.value.startsWith('BC-')
        ? <Anchor component={Link} to="/bank-changes?status=all" underline="hover"><Id>{value.value}</Id></Anchor>
        : <Id>{value.value}</Id>
    case 'text':
      return <>{value.value}</>
    case 'list':
      return (
        <>
          {value.items.map((item, index) => (
            <Fragment key={index}>
              {index > 0 && ', '}
              <EvidenceValueView value={item} />
            </Fragment>
          ))}
        </>
      )
    case 'empty':
      return <Text span c="dimmed" inherit>none</Text>
  }
}

/** A link to another bill, with its id in mono. */
function BillLink({ billId }: { billId: string }) {
  return (
    <Anchor component={Link} to={`/bills/${billId}`} underline="always" size="sm">
      <Id>{billId}</Id>
    </Anchor>
  )
}


/** One evidence block. */
function Block({ block }: { block: EvidenceBlock }) {
  switch (block.type) {
    case 'pairs':
      return (
        <Table withTableBorder fz="sm" verticalSpacing={4} bg="white" highlightOnHover={false}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Item</Table.Th>
              <Table.Th>{block.expectedLabel}</Table.Th>
              <Table.Th>{block.foundLabel}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {block.rows.map((row) => (
              <Table.Tr key={row.label}>
                <Table.Td>{row.label}</Table.Td>
                <Table.Td><EvidenceValueView value={row.expected} /></Table.Td>
                <Table.Td><EvidenceValueView value={row.found} /></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )
    case 'matches':
      return (
        <List size="sm" spacing={4} aria-label="Matches">
          {block.rows.map((match) => (
            <List.Item key={match.id}>
              <Group gap={6} wrap="wrap">
                {match.isBill ? <BillLink billId={match.id} /> : <Id>{match.id}</Id>}
                {match.kind && <Text span size="sm">{duplicateKindLabel(match.kind)}</Text>}
                {match.score !== null && <Text span size="sm" c="dimmed">{similarityText(match.score)}</Text>}
              </Group>
              {match.reasons.length > 0 && (
                <Text size="xs" c="dimmed">{match.reasons.join('; ')}</Text>
              )}
            </List.Item>
          ))}
        </List>
      )
    case 'related':
      return (
        <Stack gap={2}>
          <Group gap={6} wrap="wrap">
            <Text span size="sm">Related bills:</Text>
            {block.bills.map((id, index) => (
              <Fragment key={id}>
                {index > 0 && <Text span size="sm">,</Text>}
                <BillLink billId={id} />
              </Fragment>
            ))}
          </Group>
          {block.combinedCad && (
            <Text size="sm">Combined total: <EvidenceValueView value={block.combinedCad} /></Text>
          )}
        </Stack>
      )
    case 'bankChange':
      return (
        <Stack gap={2}>
          <Text size="sm">
            {`Account ${accountEnding(block.oldLast4, true)} changed to ${accountEnding(block.newLast4, true)}`}
          </Text>
          <Text size="sm" c="dimmed">
            {block.changedOn.kind !== 'empty' && <>On <EvidenceValueView value={block.changedOn} /></>}
            {block.channel && `${block.changedOn.kind !== 'empty' ? ', by ' : 'By '}${bankChannelLabel(block.channel).toLowerCase()}`}
            {block.verified !== null && (block.verified ? '. Verified by callback.' : '. Not verified by callback.')}
          </Text>
        </Stack>
      )
    case 'facts':
      return (
        <SimpleGrid cols={2} spacing={4} verticalSpacing={2} component="dl" style={{ gridTemplateColumns: 'max-content 1fr', margin: 0 }}>
          {block.rows.map((row) => (
            <Fragment key={row.key}>
              <Text component="dt" size="sm" c="dimmed">{row.label}</Text>
              <Text component="dd" size="sm" m={0}><EvidenceValueView value={row.value} /></Text>
            </Fragment>
          ))}
        </SimpleGrid>
      )
  }
}

interface FlagEvidenceProps {
  evidence: Record<string, unknown>
  currency: string
  duplicates?: readonly DuplicateMatch[]
}

/** A flag's evidence, as the blocks classifyEvidence finds in it; nothing for empty evidence. */
export function FlagEvidence({ evidence, currency, duplicates }: FlagEvidenceProps) {
  const blocks = classifyEvidence(evidence, { currency, duplicates })
  if (blocks.length === 0) return null
  return (
    <Stack gap="xs">
      {blocks.map((block, index) => <Block key={`${block.type}-${index}`} block={block} />)}
    </Stack>
  )
}
