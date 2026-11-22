import { Skeleton, Table, Text } from '@mantine/core'
import type { ReactNode } from 'react'

interface TableShellProps {
  label: string
  columns: readonly string[]
  /** Columns to right-align in tabular figures. */
  numeric?: readonly string[]
  loading: boolean
  /** True when loaded with no rows: the empty line is shown. */
  empty: boolean
  emptyMessage: string
  minWidth?: number
  children: ReactNode
}

/**
 * The admin tables' frame: header, static skeleton rows while loading, and a one-line empty state. Below `minWidth`
 * the table scrolls sideways with the browser's own scrollbar, which is always there to see (Mantine's default one
 * only appears on hover, so cut-off columns looked missing rather than scrollable).
 */
export function TableShell({ label, columns, numeric = [], loading, empty, emptyMessage, minWidth = 900, children }: TableShellProps) {
  return (
    <Table.ScrollContainer minWidth={minWidth} type="native">
      <Table aria-label={label} bg="white" withTableBorder>
        <Table.Thead>
          <Table.Tr>
            {columns.map((column) => (
              <Table.Th key={column} data-numeric={numeric.includes(column) || undefined}>{column}</Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {loading && Array.from({ length: 6 }, (_, row) => (
            <Table.Tr key={`skeleton-${row}`} aria-hidden>
              {columns.map((column) => (
                <Table.Td key={column}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>
              ))}
            </Table.Tr>
          ))}
          {!loading && empty && (
            <Table.Tr>
              <Table.Td colSpan={columns.length}><Text size="sm" c="dimmed" py="xs">{emptyMessage}</Text></Table.Td>
            </Table.Tr>
          )}
          {!loading && children}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
