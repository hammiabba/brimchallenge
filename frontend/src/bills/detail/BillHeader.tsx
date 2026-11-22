import { Anchor, Box, Button, Group, SimpleGrid, Stack, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle } from '@tabler/icons-react'
import { Fragment, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { notifyError } from '../../api/notify'
import { departmentLabel, useDepartments, useVendor } from '../../api/reference'
import type { BillDetail } from '../../api/types'
import { STATUS_TONES } from '../../theme'
import { StatusBadge } from '../../ui/Badges'
import { DateText, Id, MoneyText } from '../../ui/DataText'
import { Icon } from '../../ui/Icon'
import { DEPARTMENT_SOURCES } from '../labels'
import { useEditBill, useVoidBill } from '../mutations'
import { CommentActionModal } from '../../vendors/CommentActionModal'
import { DepartmentModal } from './DepartmentModal'

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

/**
 * AP's department actions, when allowed_actions.edit allows them: confirm a department that was only suggested by
 * the line coding (saves the same value, which marks it as set by a person) or change it.
 */
function DepartmentActions({ bill, unconfirmed }: { bill: BillDetail; unconfirmed: boolean }) {
  const [open, setOpen] = useState(false)
  const confirm = useEditBill(bill)

  function confirmDepartment() {
    confirm.mutate({ department_id: bill.department_id }, {
      onSuccess: () => notifications.show({ title: 'Department confirmed', message: bill.bill_id }),
      onError: (error) => notifyError(error),
    })
  }

  return (
    <Group gap="xs" wrap="nowrap" mt={4}>
      {unconfirmed && bill.department_id && (
        <Button size="xs" onClick={confirmDepartment} loading={confirm.isPending}>Confirm</Button>
      )}
      <Button size="xs" variant="default" onClick={() => setOpen(true)} aria-label="Change department">Change</Button>
      <DepartmentModal bill={bill} opened={open} onClose={() => setOpen(false)} />
    </Group>
  )
}

/** The department with where it came from; a suggestion from line coding is marked "not confirmed". */
function DepartmentFact({ bill }: { bill: BillDetail }) {
  const departments = useDepartments()
  const canEdit = bill.allowed_actions?.edit?.allowed ?? false
  const source = bill.department_source ? DEPARTMENT_SOURCES[bill.department_source] : null
  if (!bill.department_id) {
    return (
      <Stack gap={0}>
        <Text span c="dimmed" size="sm">No department</Text>
        {canEdit && <DepartmentActions bill={bill} unconfirmed={false} />}
      </Stack>
    )
  }
  return (
    <Stack gap={0}>
      <Text size="sm">{departmentLabel(bill.department_id, departments.data)}</Text>
      {source && (
        <Text size="xs" c={source.unconfirmed ? STATUS_TONES.attention.color : 'dimmed'} fw={source.unconfirmed ? 600 : undefined}>
          {source.unconfirmed ? `Not confirmed: ${source.label}` : source.label.charAt(0).toUpperCase() + source.label.slice(1)}
        </Text>
      )}
      {canEdit && <DepartmentActions bill={bill} unconfirmed={source?.unconfirmed ?? false} />}
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
 * Void, when the bill's allowed_actions.void allows it (AP on bills in review; the controller also on bills awaiting or
 * past approval with no payment scheduled). A confirm dialog with a required comment, since it can't be undone. The
 * dialog stays mounted once the bill is void, so its success handling still runs after the bill refreshes.
 */
function VoidAction({ bill }: { bill: BillDetail }) {
  const [open, setOpen] = useState(false)
  const voidBill = useVoidBill(bill)
  const action = bill.allowed_actions?.void
  if (!action) return null
  return (
    <>
      {action.allowed && <Button size="xs" variant="default" onClick={() => setOpen(true)}>Void bill</Button>}
      <CommentActionModal
        opened={open}
        onClose={() => setOpen(false)}
        title="Void bill"
        description={`${bill.bill_id} is cancelled and won't be paid. It stays on record with your reason; this can't be undone.`}
        mutation={voidBill}
        onDone={() => {
          notifications.show({ title: 'Bill voided', message: bill.bill_id })
          setOpen(false)
        }}
        danger
        commentRequired
      />
    </>
  )
}

/**
 * A warning when a bill still has a payment scheduled while blocking flags are open (a history bill scheduled before
 * the controls flagged it, such as a duplicate): the payment would go out unless someone cancels it, so the banner
 * names it and links to it. Nothing otherwise.
 */
function ScheduledWhileBlocked({ bill }: { bill: BillDetail }) {
  const blocking = (bill.latest_run?.flags ?? []).filter((f) => f.severity === 'block' && f.resolution === 'open')
  const scheduled = bill.payments.filter((p) => p.status === 'scheduled')
  if (blocking.length === 0 || scheduled.length === 0) return null
  return (
    <Group gap={6} wrap="nowrap" align="flex-start" role="status">
      <Box pt={2} c={STATUS_TONES.attention.color}><Icon icon={IconAlertTriangle} size={16} /></Box>
      <Text size="sm" fw={500}>
        {`${blocking.length} blocking flag${blocking.length === 1 ? ' is' : 's are'} open, but `}
        {scheduled.map((payment, index) => (
          <Fragment key={payment.payment_id}>
            {index > 0 && ', '}
            <Anchor component={Link} to={`/payments/${payment.payment_id}`} inherit><Id>{payment.payment_id}</Id></Anchor>
            {' is scheduled for '}<DateText value={payment.scheduled_date} />
          </Fragment>
        ))}
        {'. Cancel the payment if the flags hold.'}
      </Text>
    </Group>
  )
}

/**
 * The bill's header row: id and status, then vendor (with its status), invoice number, dates, total and department.
 */
export function BillHeader({ bill }: { bill: BillDetail }) {
  const vendor = useVendor(bill.vendor_id)
  return (
    <Stack component="section" aria-label="Bill summary" gap="sm">
      <Group justify="space-between" align="center" gap="sm">
        <Group gap="sm" align="center">
          <Title order={1}>Bill <Id>{bill.bill_id}</Id></Title>
          <StatusBadge kind="bill" status={bill.status} />
          {bill.is_credit_note && <Text size="sm" fw={600}>Credit note</Text>}
        </Group>
        <VoidAction bill={bill} />
      </Group>
      <ScheduledWhileBlocked bill={bill} />
      <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }} spacing="md" verticalSpacing="xs">
        <Fact label="Vendor">
          <Group gap={6} wrap="wrap">
            {/* The vendor's page, like vendor names elsewhere in the app. */}
            {bill.vendor_id && bill.vendor_name
              ? <Anchor component={Link} to={`/vendors/${bill.vendor_id}`} underline="hover" inherit>{bill.vendor_name}</Anchor>
              : <span>{bill.vendor_name ?? 'No vendor matched'}</span>}
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
