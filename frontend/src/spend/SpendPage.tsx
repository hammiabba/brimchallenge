import { Anchor, Group, SegmentedControl, Select, Skeleton, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'

import { api, unwrap } from '../api/client'
import { ErrorAlert } from '../api/ErrorAlert'
import { departmentLabel, useDepartments } from '../api/reference'
import type { Role, SpendGroupBy, SpendReport, SpendRow } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { DateText, Id, MoneyText } from '../ui/DataText'
import { shareOf } from './share'

const GROUPS: Array<{ value: SpendGroupBy; label: string; column: string }> = [
  { value: 'department', label: 'Department', column: 'Department' },
  { value: 'vendor', label: 'Vendor', column: 'Vendor' },
  { value: 'gl_account', label: 'GL account', column: 'GL account' },
]
const DATE = /^\d{4}-\d{2}-\d{2}$/
/** Roles the server limits to their own department, whatever they ask for (backend services/spend.py). */
const SCOPED_ROLES: readonly Role[] = ['approver']

interface SpendFilters {
  groupBy: SpendGroupBy
  from: string
  to: string
  departmentId: string | null
}

/** The filters in the URL: ?group_by=vendor&from=2026-01-01&to=2026-10-31&department=D01. */
function filtersFromSearch(search: URLSearchParams): SpendFilters {
  const group = GROUPS.find((g) => g.value === search.get('group_by'))?.value ?? 'department'
  const date = (key: string) => (DATE.test(search.get(key) ?? '') ? (search.get(key) ?? '') : '')
  return { groupBy: group, from: date('from'), to: date('to'), departmentId: search.get('department') || null }
}

function searchFromFilters(filters: SpendFilters): URLSearchParams {
  const search = new URLSearchParams()
  if (filters.groupBy !== 'department') search.set('group_by', filters.groupBy)
  if (filters.from) search.set('from', filters.from)
  if (filters.to) search.set('to', filters.to)
  if (filters.departmentId) search.set('department', filters.departmentId)
  return search
}

/** The row: its name, with its code under it (a link to the vendor's page for vendors). One column, not two. */
function KeyCell({ row, groupBy }: { row: SpendRow; groupBy: SpendGroupBy }) {
  const code = groupBy === 'vendor' && row.key !== 'unknown'
    ? <Anchor component={Link} to={`/vendors/${row.key}`} underline="hover"><Id>{row.key}</Id></Anchor>
    : <Id>{row.key}</Id>
  return (
    <Stack gap={0}>
      <Text size="sm">{row.label}</Text>
      <Text size="xs" c="dimmed">{code}</Text>
    </Stack>
  )
}

/** The report table, with a total row that adds up the bills and the whole share. */
function SpendTable({ report, loading, column }: { report: SpendReport | undefined; loading: boolean; column: string }) {
  const columns = [column, 'Bills', 'Total (CAD)', 'Share']
  // Bill counts are whole numbers, so a plain sum is exact.
  const bills = report?.rows.reduce((sum, row) => sum + row.bill_count, 0) ?? 0
  const numeric = new Set(['Bills', 'Total (CAD)', 'Share'])
  return (
    <Table.ScrollContainer minWidth={560}>
      <Table aria-label="Spend" bg="white" withTableBorder>
        <Table.Thead>
          <Table.Tr>{columns.map((c) => <Table.Th key={c} data-numeric={numeric.has(c) || undefined}>{c}</Table.Th>)}</Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {loading && Array.from({ length: 6 }, (_, row) => (
            <Table.Tr key={`skeleton-${row}`} aria-hidden>
              {columns.map((c) => <Table.Td key={c}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>)}
            </Table.Tr>
          ))}
          {!loading && report?.rows.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={columns.length}><Text size="sm" c="dimmed" py="xs">No committed spend in this range.</Text></Table.Td>
            </Table.Tr>
          )}
          {!loading && report?.rows.map((row) => (
            <Table.Tr key={row.key}>
              <Table.Td><KeyCell row={row} groupBy={report.group_by} /></Table.Td>
              <Table.Td data-numeric>{row.bill_count}</Table.Td>
              <Table.Td data-numeric><MoneyText value={row.total_cad} align="right" /></Table.Td>
              <Table.Td data-numeric>{shareOf(row.total_cad, report.total_cad)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
        {!loading && report && report.rows.length > 0 && (
          <Table.Tfoot>
            <Table.Tr>
              <Table.Th scope="row">Total</Table.Th>
              <Table.Td data-numeric>{bills}</Table.Td>
              <Table.Td data-numeric><MoneyText value={report.total_cad} align="right" fw={600} /></Table.Td>
              <Table.Td data-numeric>100.0%</Table.Td>
            </Table.Tr>
          </Table.Tfoot>
        )}
      </Table>
    </Table.ScrollContainer>
  )
}

/**
 * /spend: committed spend (approved, scheduled, paid and credit-open bills) by department, vendor or GL account over an
 * invoice-date range. The server scopes approvers to their own department and says so in the report.
 */
export default function SpendPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(() => filtersFromSearch(searchParams), [searchParams])
  const departments = useDepartments()
  const query = useMemo(() => ({
    group_by: filters.groupBy,
    ...(filters.from ? { from_date: filters.from } : {}),
    ...(filters.to ? { to_date: filters.to } : {}),
    ...(filters.departmentId ? { department_id: filters.departmentId } : {}),
  }), [filters])
  const report = useQuery({
    queryKey: ['spend', query],
    queryFn: () => unwrap(api.GET('/spend', { params: { query } })),
    placeholderData: keepPreviousData,
  })
  const set = (next: Partial<SpendFilters>) => setSearchParams(searchFromFilters({ ...filters, ...next }), { replace: true })
  const group = GROUPS.find((g) => g.value === filters.groupBy) ?? GROUPS[0]!
  const user = useCurrentUser()
  // An approver's report is always their own department: the select shows it, locked, instead of "All departments".
  const scoped = SCOPED_ROLES.includes(user.role) ? user.department_id : null

  return (
    <Stack gap="md">
      <Title order={1}>Spend</Title>
      <Group gap="sm" align="flex-end" wrap="wrap">
        <Stack gap={4}>
          <Text size="sm" fw={500} id="spend-group-label">Group by</Text>
          <SegmentedControl aria-labelledby="spend-group-label" data={GROUPS.map(({ value, label }) => ({ value, label }))}
            value={filters.groupBy} onChange={(value) => set({ groupBy: value as SpendGroupBy })} />
        </Stack>
        <TextInput label="Invoice date from" type="date" value={filters.from} onChange={(e) => set({ from: e.currentTarget.value })} w={170} />
        <TextInput label="Invoice date to" type="date" value={filters.to} onChange={(e) => set({ to: e.currentTarget.value })} w={170} />
        <Select
          label="Department"
          placeholder="All departments"
          description={scoped ? 'Approvers see their own department.' : undefined}
          data={(departments.data ?? []).map((d) => ({ value: d.department_id, label: departmentLabel(d.department_id, departments.data) }))}
          value={scoped ?? filters.departmentId}
          onChange={(value) => set({ departmentId: value })}
          clearable={!scoped}
          disabled={Boolean(scoped)}
          w={220}
        />
      </Group>
      {report.isError && !report.data ? (
        <ErrorAlert error={report.error} title="Can't load spend" onRetry={() => void report.refetch()} />
      ) : (
        <SpendTable report={report.data} loading={report.isPending} column={group.column} />
      )}
      {/* The period the report covers, also when no dates are set. */}
      {report.data && (
        <Text size="sm" c="dimmed">
          {!report.data.from_date && !report.data.to_date ? 'All invoice dates' : <>
            {'Invoices dated '}
            {report.data.from_date ? <>from <DateText value={report.data.from_date} /> </> : ''}
            {report.data.to_date ? <>to <DateText value={report.data.to_date} /></> : 'onwards'}
          </>}
        </Text>
      )}
    </Stack>
  )
}
