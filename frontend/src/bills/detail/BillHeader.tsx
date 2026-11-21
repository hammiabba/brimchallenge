import { Group, SimpleGrid, Stack, Text, Title } from '@mantine/core'
import { Fragment, type ReactNode } from 'react'

import { departmentLabel, useDepartments, useVendor } from '../../api/reference'
import type { BillDetail } from '../../api/types'
import { STATUS_TONES } from '../../theme'
import { StatusBadge } from '../../ui/Badges'
import { DateText, Id, MoneyText } from '../../ui/DataText'
import { DEPARTMENT_SOURCES } from '../labels'

/** One labelled fact in the header. */
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Fragment>
      <Stack gap={0}>
        <Text size="xs" c="dimmed">{label}</Text>
        <Text component="div" size="sm">{children}</Text>
      </Stack>
    </Fragment>
  )
}

/** The department with where it came from; a suggestion from line coding is marked "not confirmed". */
function DepartmentFact({ bill }: { bill: BillDetail }) {
  const departments = useDepartments()
  if (!bill.department_id) return <Text span c="dimmed" size="sm">No department</Text>
  const source = bill.department_source ? DEPARTMENT_SOURCES[bill.department_source] : null
  return (
    <Stack gap={0}>
      <Text size="sm">{departmentLabel(bill.department_id, departments.data)}</Text>
      {source && (
        <Text size="xs" c={source.unconfirmed ? STATUS_TONES.attention.color : 'dimmed'} fw={source.unconfirmed ? 600 : undefined}>
          {source.unconfirmed ? `Not confirmed: ${source.label}` : source.label.charAt(0).toUpperCase() + source.label.slice(1)}
        </Text>
      )}
    </Stack>
  )
}

/** The total in CAD; for another currency, the original amount, the FX rate and its date underneath. */
function TotalFact({ bill }: { bill: BillDetail }) {
  return (
    <Stack gap={0}>
      <Text size="sm" fw={600}><MoneyText value={bill.total_cad} /></Text>
      {bill.currency !== 'CAD' && (
        <Text size="xs" c="dimmed">
          <MoneyText value={bill.total} currency={bill.currency} />
          {` at ${bill.fx_rate_to_cad} ${bill.currency}/CAD`}
          {bill.fx_rate_date && <>{', rate of '}<DateText value={bill.fx_rate_date} /></>}
        </Text>
      )}
    </Stack>
  )
}

/**
 * The bill's header row: id and status, then vendor (with its status), invoice number, dates, total and department.
 */
export function BillHeader({ bill }: { bill: BillDetail }) {
  const vendor = useVendor(bill.vendor_id)
  return (
    <Stack component="section" aria-label="Bill summary" gap="sm">
      <Group gap="sm" align="center">
        <Title order={1}>Bill <Id>{bill.bill_id}</Id></Title>
        <StatusBadge kind="bill" status={bill.status} />
        {bill.is_credit_note && <Text size="sm" fw={600}>Credit note</Text>}
      </Group>
      <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }} spacing="md" verticalSpacing="xs">
        <Fact label="Vendor">
          <Group gap={6} wrap="wrap">
            <span>{bill.vendor_name ?? 'No vendor matched'}</span>
            {bill.vendor_id && <Id>{bill.vendor_id}</Id>}
            {vendor.data && <StatusBadge kind="vendor" status={vendor.data.status} />}
          </Group>
        </Fact>
        <Fact label="Invoice number"><Id>{bill.vendor_invoice_number}</Id></Fact>
        <Fact label="Invoice date"><DateText value={bill.invoice_date} /></Fact>
        <Fact label="Due date">{bill.due_date ? <DateText value={bill.due_date} /> : 'None'}</Fact>
        <Fact label="Total (CAD)"><TotalFact bill={bill} /></Fact>
        <Fact label="Department"><DepartmentFact bill={bill} /></Fact>
      </SimpleGrid>
    </Stack>
  )
}
