import { Group, MultiSelect, Select, TextInput } from '@mantine/core'
import { IconSearch } from '@tabler/icons-react'
import { useEffect, useState } from 'react'

import { useDepartments, useVendorList } from '../api/reference'
import type { BillStatus } from '../api/types'
import { Icon } from '../ui/Icon'
import { BILL_STATUS } from '../ui/statusStyles'
import type { BillListFilters } from './listQuery'

/** How long typing pauses before the search goes into the URL (and the request). */
export const SEARCH_DEBOUNCE_MS = 300

const STATUS_OPTIONS = Object.entries(BILL_STATUS).map(([value, style]) => ({ value, label: style.label }))

interface BillFiltersProps {
  filters: BillListFilters
  /** Called with the new filters; the caller writes them to the URL. */
  onChange: (next: BillListFilters) => void
  /** Hide the status filter (the review queue has fixed statuses). */
  showStatus?: boolean
}

/**
 * The filter bar: search (bill id, invoice number or vendor name), status, vendor and department. These are exactly
 * the filters GET /bills applies server-side. Any change goes back to page 1.
 */
export function BillFilters({ filters, onChange, showStatus = true }: BillFiltersProps) {
  const vendors = useVendorList()
  const departments = useDepartments()
  const [search, setSearch] = useState(filters.q)
  const [syncedQ, setSyncedQ] = useState(filters.q)

  // Keep the box in step when the URL changes from outside (back button, a shared link), without undoing what is
  // being typed (the URL holds the trimmed text, the box may still end in a space). Adjusted during render, as React
  // recommends for state that follows a prop.
  if (filters.q !== syncedQ) {
    setSyncedQ(filters.q)
    if (search.trim() !== filters.q.trim()) setSearch(filters.q)
  }

  // Write the search to the URL once typing pauses.
  useEffect(() => {
    if (search.trim() === filters.q.trim()) return undefined
    const timer = setTimeout(() => onChange({ ...filters, q: search, page: 1 }), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [search, filters, onChange])

  return (
    <Group gap="sm" align="flex-end" wrap="wrap">
      <TextInput
        label="Search"
        placeholder="Bill ID, invoice number or vendor"
        leftSection={<Icon icon={IconSearch} />}
        value={search}
        onChange={(event) => setSearch(event.currentTarget.value)}
        w={280}
      />
      {showStatus && (
        <MultiSelect
          label="Status"
          placeholder={filters.status.length === 0 ? 'Any status' : undefined}
          data={STATUS_OPTIONS}
          value={filters.status}
          onChange={(value) => onChange({ ...filters, status: value as BillStatus[], page: 1 })}
          clearable
          w={300}
        />
      )}
      <Select
        label="Vendor"
        placeholder="Any vendor"
        data={(vendors.data?.items ?? []).map((v) => ({ value: v.vendor_id, label: `${v.legal_name} (${v.vendor_id})` }))}
        value={filters.vendorId}
        onChange={(value) => onChange({ ...filters, vendorId: value, page: 1 })}
        searchable
        clearable
        nothingFoundMessage="No vendor matches"
        w={260}
      />
      <Select
        label="Department"
        placeholder="Any department"
        data={(departments.data ?? []).map((d) => ({ value: d.department_id, label: `${d.name} (${d.department_id})` }))}
        value={filters.departmentId}
        onChange={(value) => onChange({ ...filters, departmentId: value, page: 1 })}
        clearable
        w={220}
      />
    </Group>
  )
}
