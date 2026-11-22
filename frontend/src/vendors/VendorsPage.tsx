import { Button, Group, MultiSelect, Pagination, Stack, Text, TextInput, Title } from '@mantine/core'
import { IconPlus, IconSearch } from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import type { VendorStatus } from '../api/types'
import { Icon } from '../ui/Icon'
import { VENDOR_STATUS } from '../ui/statusStyles'
import { PAGE_SIZE, apiQuery, filtersFromSearch, searchFromFilters, type VendorListFilters } from './listQuery'
import { OnboardVendorModal } from './OnboardVendorModal'
import { useMayDo } from './roles'
import { useVendorsPage } from './queries'
import { VendorsTable } from './VendorsTable'

/** How long typing pauses before the search goes into the URL (and the request). */
const SEARCH_DEBOUNCE_MS = 300
const STATUS_OPTIONS = Object.entries(VENDOR_STATUS).map(([value, style]) => ({ value, label: style.label }))

/** Search and status filters; the search is written to the URL once typing pauses. Any change goes back to page 1. */
function VendorFilters({ filters, onChange }: { filters: VendorListFilters; onChange: (next: VendorListFilters) => void }) {
  const [search, setSearch] = useState(filters.q)
  const [syncedQ, setSyncedQ] = useState(filters.q)

  // Follow the URL when it changes from outside (back button, a shared link) without undoing what is being typed.
  if (filters.q !== syncedQ) {
    setSyncedQ(filters.q)
    if (search.trim() !== filters.q.trim()) setSearch(filters.q)
  }

  useEffect(() => {
    if (search.trim() === filters.q.trim()) return undefined
    const timer = setTimeout(() => onChange({ ...filters, q: search, page: 1 }), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [search, filters, onChange])

  return (
    <Group gap="sm" align="flex-end" wrap="wrap">
      <TextInput
        label="Search"
        placeholder="Vendor name or ID"
        leftSection={<Icon icon={IconSearch} />}
        value={search}
        onChange={(event) => setSearch(event.currentTarget.value)}
        w={280}
      />
      <MultiSelect
        label="Status"
        placeholder={filters.status.length === 0 ? 'Any status' : undefined}
        data={STATUS_OPTIONS}
        value={filters.status}
        onChange={(value) => onChange({ ...filters, status: value as VendorStatus[], page: 1 })}
        clearable
        w={300}
      />
    </Group>
  )
}

/**
 * /vendors: the vendor master, filtered and paged in the URL. AP onboards new vendors here; the server refuses the
 * form for roles that can't, with its own message.
 */
export default function VendorsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(() => filtersFromSearch(searchParams), [searchParams])
  const query = useMemo(() => apiQuery(filters), [filters])
  const vendors = useVendorsPage(query)
  const [onboarding, setOnboarding] = useState(false)
  const mayOnboard = useMayDo('onboard')

  const setFilters = useCallback(
    (next: VendorListFilters) => setSearchParams(searchFromFilters(next), { replace: true }),
    [setSearchParams],
  )

  const filtered = filters.q.trim() !== '' || filters.status.length > 0
  const total = vendors.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const shown = vendors.data?.items.length ?? 0
  const first = (filters.page - 1) * PAGE_SIZE + 1

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <Title order={1}>Vendors</Title>
        {mayOnboard && <Button leftSection={<Icon icon={IconPlus} />} onClick={() => setOnboarding(true)}>Onboard vendor</Button>}
      </Group>
      <VendorFilters filters={filters} onChange={setFilters} />
      {vendors.isError && !vendors.data ? (
        <ErrorAlert error={vendors.error} title="Can't load vendors" onRetry={() => void vendors.refetch()} />
      ) : (
        <>
          <VendorsTable
            vendors={vendors.data?.items}
            loading={vendors.isPending}
            emptyMessage={filtered ? 'No vendors match these filters.' : 'No vendors yet.'}
          />
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              {total > 0 ? `Showing ${first} to ${first + shown - 1} of ${total} vendor${total === 1 ? '' : 's'}` : ''}
            </Text>
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
      {mayOnboard && <OnboardVendorModal opened={onboarding} onClose={() => setOnboarding(false)} />}
    </Stack>
  )
}
