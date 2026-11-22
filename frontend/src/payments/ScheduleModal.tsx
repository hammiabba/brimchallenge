import { Button, Group, Modal, Select, SimpleGrid, Stack, Text, TextInput } from '@mantine/core'
import { useState } from 'react'

import { ErrorAlert } from '../api/ErrorAlert'
import { useVendor } from '../api/reference'
import type { BillSummary, PaymentMethod } from '../api/types'
import { PAYMENT_METHOD_LABELS } from '../bills/labels'
import { MoneyText } from '../ui/DataText'
import { useSchedulePayment } from './queries'

const METHODS: PaymentMethod[] = ['EFT', 'CHEQUE', 'CARD']

interface ScheduleModalProps {
  bill: BillSummary
  /** The business date (GET /payments/summary as_of): a payment can't be scheduled before it. */
  asOf: string
  opened: boolean
  onClose: () => void
}

/**
 * Schedule the payment of an approved bill: method (the vendor's preferred one first) and date (the bill's due date,
 * or today when that has passed). The server checks the rest: the vendor is active, no bank change is pending, there
 * is an account for EFT and no other open payment. A refusal shows here with its request id.
 */
export function ScheduleModal({ bill, asOf, opened, onClose }: ScheduleModalProps) {
  const vendor = useVendor(bill.vendor_id)
  const schedule = useSchedulePayment(bill.bill_id)
  const due = bill.due_date && bill.due_date > asOf ? bill.due_date : asOf
  const [method, setMethod] = useState<PaymentMethod | null>(null)
  const [date, setDate] = useState(due)
  const chosen = method ?? vendor.data?.preferred_payment_method ?? 'EFT'
  const tooEarly = date !== '' && asOf !== '' && date < asOf

  function close() {
    schedule.reset()
    setMethod(null)
    setDate(due)
    onClose()
  }

  function confirm() {
    // useSchedulePayment shows the "Payment scheduled" confirmation, even once this bill has left the list.
    schedule.mutate({ scheduled_date: date, method: chosen }, { onSuccess: () => close() })
  }

  return (
    <Modal opened={opened} onClose={close} title="Schedule payment">
      <Stack gap="sm">
        <Text size="sm">
          {`Prepare the payment of ${bill.bill_id} (${bill.vendor_name ?? 'no vendor matched'}) for `}
          <MoneyText value={bill.total_cad} />
          {'. Someone in finance releases it; you can\'t release a payment you prepared.'}
        </Text>
        <SimpleGrid cols={2} spacing="sm">
          <Select
            label="Method"
            required
            data={METHODS.map((m) => ({ value: m, label: PAYMENT_METHOD_LABELS[m] ?? m }))}
            value={chosen}
            onChange={(value) => setMethod(value as PaymentMethod | null)}
            allowDeselect={false}
          />
          <TextInput
            label="Payment date"
            type="date"
            required
            value={date}
            min={asOf}
            error={tooEarly ? 'Pick today or a later date' : undefined}
            onChange={(event) => setDate(event.currentTarget.value)}
          />
        </SimpleGrid>
        {schedule.isError && <ErrorAlert error={schedule.error} />}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={close}>Cancel</Button>
          <Button onClick={confirm} disabled={date === '' || tooEarly} loading={schedule.isPending}>Schedule payment</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
