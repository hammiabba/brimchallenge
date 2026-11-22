import { Anchor, Group, Skeleton, Table, Text } from '@mantine/core'
import { Link } from 'react-router'

import type { VendorSummary } from '../api/types'
import { LookalikeBadge, StatusBadge } from '../ui/Badges'
import { Id } from '../ui/DataText'
import { PAYMENT_METHOD_LABELS, termsLabel } from './labels'

const COLUMNS = ['Vendor', 'Name', 'Category', 'Location', 'Terms', 'Payment method', 'PO required', 'Status'] as const
const SKELETON_ROWS = 8

interface VendorsTableProps {
  vendors: readonly VendorSummary[] | undefined
  /** True on the first load (no rows yet): skeleton rows are shown. */
  loading: boolean
  /** One line shown when the list is empty. */
  emptyMessage: string
}

/**
 * The vendor master as a dense table, in the server's order. Each vendor id opens the vendor page. A record that looks
 * like an existing vendor is tagged "Possible duplicate of V002" under its name.
 */
export function VendorsTable({ vendors, loading, emptyMessage }: VendorsTableProps) {
  return (
    <Table.ScrollContainer minWidth={900}>
      <Table aria-label="Vendors" bg="white" withTableBorder>
        <Table.Thead>
          <Table.Tr>
            {COLUMNS.map((column) => <Table.Th key={column}>{column}</Table.Th>)}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {loading && Array.from({ length: SKELETON_ROWS }, (_, row) => (
            <Table.Tr key={`skeleton-${row}`} aria-hidden>
              {COLUMNS.map((column) => (
                <Table.Td key={column}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>
              ))}
            </Table.Tr>
          ))}
          {!loading && vendors?.length === 0 && (
            <Table.Tr>
              <Table.Td colSpan={COLUMNS.length}>
                <Text size="sm" c="dimmed" py="xs">{emptyMessage}</Text>
              </Table.Td>
            </Table.Tr>
          )}
          {!loading && vendors?.map((vendor) => (
            <Table.Tr key={vendor.vendor_id}>
              <Table.Td>
                <Anchor component={Link} to={`/vendors/${vendor.vendor_id}`} underline="hover" fw={500}>
                  <Id>{vendor.vendor_id}</Id>
                </Anchor>
              </Table.Td>
              <Table.Td>
                {/* A suspicious copy of an existing vendor gets a tag under its name, one per record it copies. */}
                {vendor.legal_name}
                {vendor.lookalike_of.length > 0 && (
                  <Group gap={4} mt={2}>
                    {vendor.lookalike_of.map((other) => <LookalikeBadge key={other.vendor_id} vendorId={other.vendor_id} />)}
                  </Group>
                )}
              </Table.Td>
              <Table.Td>{vendor.category}</Table.Td>
              <Table.Td>{`${vendor.province_or_state}, ${vendor.country}`}</Table.Td>
              <Table.Td>{termsLabel(vendor.payment_terms_days)}</Table.Td>
              <Table.Td>{PAYMENT_METHOD_LABELS[vendor.preferred_payment_method]}</Table.Td>
              <Table.Td>{vendor.requires_po ? 'Yes' : 'No'}</Table.Td>
              <Table.Td><StatusBadge kind="vendor" status={vendor.status} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
