import { Anchor, List, Text } from '@mantine/core'
import { Link } from 'react-router'

import type { IntakeItem } from '../api/types'
import { Id } from '../ui/DataText'

/** The error of a failed item, or the warnings of a read one (for example a department suggested from coding). */
export function ItemNotes({ item }: { item: Pick<IntakeItem, 'error' | 'warnings'> }) {
  if (item.error) return <Text size="sm">{item.error}</Text>
  if (item.warnings.length === 0) return null
  return (
    <List size="xs" spacing={2}>
      {item.warnings.map((warning) => <List.Item key={warning}>{warning}</List.Item>)}
    </List>
  )
}

/** A link to the bill an item became, or a word saying why there is none. */
export function BillLink({ billId, pending }: { billId: string | null; pending: boolean }) {
  if (billId) {
    return <Anchor component={Link} to={`/bills/${billId}`} underline="hover" fw={500}><Id>{billId}</Id></Anchor>
  }
  return <Text size="sm" c="dimmed">{pending ? 'Not yet' : 'No bill'}</Text>
}
