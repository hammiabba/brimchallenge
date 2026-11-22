import { Button, Group, Select, Stack, Text, TextInput, Title } from '@mantine/core'
import { IconDownload } from '@tabler/icons-react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'

import { API_PREFIX, api, unwrap } from '../api/client'
import { ErrorAlert } from '../api/ErrorAlert'
import { codeAsWords, usePeople } from '../api/reference'
import { Icon } from '../ui/Icon'
import { AuditTable } from './AuditTable'
import {
  ACTIONS,
  ENTITY_TYPES,
  apiFilters,
  auditLogActionLabel,
  filtersFromSearch,
  hasFilters,
  searchFromFilters,
  type AuditFilters,
} from './filters'

export const PAGE_SIZE = 100
/** How long typing in the entity id pauses before it goes into the URL. */
const TYPING_DEBOUNCE_MS = 300

/** The filter bar. Every change is written to the URL, which resets paging. */
function FilterBar({ filters, onChange }: { filters: AuditFilters; onChange: (next: AuditFilters) => void }) {
  const people = usePeople()
  const [entityId, setEntityId] = useState(filters.entityId)
  const [synced, setSynced] = useState(filters.entityId)

  if (filters.entityId !== synced) {
    setSynced(filters.entityId)
    if (entityId.trim() !== filters.entityId.trim()) setEntityId(filters.entityId)
  }

  useEffect(() => {
    if (entityId.trim() === filters.entityId.trim()) return undefined
    const timer = setTimeout(() => onChange({ ...filters, entityId }), TYPING_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [entityId, filters, onChange])

  return (
    <Group gap="sm" align="flex-end" wrap="wrap">
      {/* The options read as words; the URL and the request keep the codes. */}
      <Select label="Entity type" placeholder="Any" value={filters.entityType}
        data={ENTITY_TYPES.map((type) => ({ value: type, label: codeAsWords(type) }))}
        onChange={(value) => onChange({ ...filters, entityType: value })} clearable w={160} />
      <TextInput label="Entity ID" placeholder="AP-00407, V011, U005" value={entityId}
        onChange={(event) => setEntityId(event.currentTarget.value)} w={180} />
      <Select
        label="Person"
        placeholder="Anyone"
        data={(people.data ?? []).map((p) => ({ value: p.user_id, label: `${p.full_name} (${p.user_id})` }))}
        value={filters.actor}
        onChange={(value) => onChange({ ...filters, actor: value })}
        searchable
        clearable
        w={240}
      />
      <Select label="Action" placeholder="Any action" value={filters.action}
        data={ACTIONS.map((action) => ({ value: action, label: auditLogActionLabel(action) }))}
        onChange={(value) => onChange({ ...filters, action: value })} searchable clearable w={240} />
      <TextInput label="From (UTC)" type="date" value={filters.from}
        onChange={(event) => onChange({ ...filters, from: event.currentTarget.value })} w={160} />
      <TextInput label="To (UTC)" type="date" value={filters.to}
        onChange={(event) => onChange({ ...filters, to: event.currentTarget.value })} w={160} />
    </Group>
  )
}

/**
 * One filter's results, paged with the server's keyset cursor (after_seq): Next asks for the events after the last
 * one shown, Previous goes back through the cursors already used. Mounted with a key per filter, so paging restarts
 * when a filter changes.
 */
function AuditResults({ filters }: { filters: AuditFilters }) {
  const [cursors, setCursors] = useState<Array<number | null>>([null])
  const after = cursors[cursors.length - 1] ?? null
  const query = useMemo(() => ({ ...apiFilters(filters), limit: PAGE_SIZE, ...(after !== null ? { after_seq: after } : {}) }),
    [filters, after])
  const page = useQuery({
    queryKey: ['audit', 'list', query],
    queryFn: () => unwrap(api.GET('/audit', { params: { query } })),
    placeholderData: keepPreviousData,
  })

  if (page.isError && !page.data) {
    return <ErrorAlert error={page.error} title="Can't load the audit log" onRetry={() => void page.refetch()} />
  }
  const next = page.data?.next_after_seq ?? null
  const items = page.data?.items ?? []
  const first = items[0]?.seq
  const last = items[items.length - 1]?.seq

  return (
    <Stack gap="sm">
      <AuditTable
        events={page.data?.items}
        loading={page.isPending}
        emptyMessage={hasFilters(filters) ? 'No events match these filters.' : 'No events recorded yet.'}
      />
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          {/* How many events are on this page, then the range of their numbers (a range, not a count). */}
          {first !== undefined && last !== undefined
            ? `Page ${cursors.length}: ${items.length} event${items.length === 1 ? '' : 's'}, numbers ${first} to ${last}`
            : ''}
        </Text>
        <Group gap="xs">
          <Button size="xs" variant="default" disabled={cursors.length === 1}
            onClick={() => setCursors((list) => list.slice(0, -1))}>Previous page</Button>
          <Button size="xs" variant="default" disabled={next === null || page.isFetching}
            onClick={() => setCursors((list) => [...list, next])}>Next page</Button>
        </Group>
      </Group>
    </Stack>
  )
}

/**
 * /audit: the full audit trail, filtered in the URL, oldest first, each event expandable to what changed. Export
 * downloads the current filter as CSV (the export itself is recorded). Controller and auditor only; the server's 403
 * explains it to anyone else.
 */
export default function AuditPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(() => filtersFromSearch(searchParams), [searchParams])
  const setFilters = useCallback(
    (next: AuditFilters) => setSearchParams(searchFromFilters(next), { replace: true }),
    [setSearchParams],
  )
  const filterKey = searchFromFilters(filters).toString()
  const exportQuery = new URLSearchParams(apiFilters(filters)).toString()
  const exportHref = `${API_PREFIX}/audit/export${exportQuery ? `?${exportQuery}` : ''}`

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <Title order={1}>Audit log</Title>
        <Button component="a" href={exportHref} download variant="default" leftSection={<Icon icon={IconDownload} />}>
          Export CSV
        </Button>
      </Group>
      <FilterBar filters={filters} onChange={setFilters} />
      <AuditResults key={filterKey} filters={filters} />
    </Stack>
  )
}
