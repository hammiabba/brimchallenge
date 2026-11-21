import { Group, Pagination, Stack, Text, Title } from '@mantine/core'
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import type { BillStatus } from '../api/types'
import { BillFilters } from './BillFilters'
import { BillsTable } from './BillsTable'
import { PAGE_SIZE, apiQuery, filtersFromSearch, searchFromFilters, type BillListFilters } from './listQuery'
import { useBillsPage } from './queries'

interface BillListViewProps {
  title: string
  /** Statuses the view always shows (the review queue); hides the status filter. */
  fixedStatus?: readonly BillStatus[]
  /** One line for an empty list with no filters. */
  emptyMessage: string
}

/** "Showing 51 to 100 of 426 bills": the range on this page of the server's total. */
function rangeLine(page: number, shown: number, total: number): string {
  if (total === 0) return ''
  const first = (page - 1) * PAGE_SIZE + 1
  return `Showing ${first} to ${first + shown - 1} of ${total} bill${total === 1 ? '' : 's'}`
}

/**
 * A titled, filtered, paged bills table. Filters and the page number are kept in the URL query string, so the
 * view can be shared or bookmarked. Rows, order and totals come from GET /bills.
 */
export function BillListView({ title, fixedStatus, emptyMessage }: BillListViewProps) {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(() => filtersFromSearch(searchParams), [searchParams])
  const query = useMemo(() => apiQuery(filters, fixedStatus), [filters, fixedStatus])
  const bills = useBillsPage(query)

  /** Writes new filters to the URL (replacing the entry, so typing doesn't fill the history). */
  const setFilters = useCallback(
    (next: BillListFilters) => setSearchParams(searchFromFilters(next), { replace: true }),
    [setSearchParams],
  )

  const filtered = filters.q.trim() !== '' || filters.vendorId !== null || filters.departmentId !== null
    || (!fixedStatus && filters.status.length > 0)
  const total = bills.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <Stack gap="md">
      <Title order={1}>{title}</Title>
      <BillFilters filters={filters} onChange={setFilters} showStatus={!fixedStatus} />
      {bills.isError && !bills.data ? (
        <ErrorAlert error={bills.error} title="Can't load bills" onRetry={() => void bills.refetch()} />
      ) : (
        <>
          <BillsTable
            bills={bills.data?.items}
            loading={bills.isPending}
            emptyMessage={filtered ? 'No bills match these filters.' : emptyMessage}
            label={title}
          />
          <Group justify="space-between">
            <Text size="sm" c="dimmed">{rangeLine(filters.page, bills.data?.items.length ?? 0, total)}</Text>
            {pages > 1 && (
              <Pagination
                total={pages}
                value={Math.min(filters.page, pages)}
                onChange={(page) => setSearchParams(searchFromFilters({ ...filters, page }))}
                size="sm"
                getControlProps={(control) => ({ 'aria-label': `${control} page` })}
              />
            )}
          </Group>
        </>
      )}
    </Stack>
  )
}
