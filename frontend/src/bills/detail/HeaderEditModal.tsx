import { Button, Group, Modal, Select, SimpleGrid, Stack, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'

import { ErrorAlert } from '../../api/ErrorAlert'
import { usePeople, useVendorList } from '../../api/reference'
import type { BillDetail } from '../../api/types'
import { useEditBill, type HeaderChanges } from '../mutations'

/** Canadian province and territory codes, as the server accepts them (models.PROVINCES). */
const PROVINCES = ['AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT']

/** The form's values: what the bill holds now, '' for none. */
interface HeaderForm {
  vendor_id: string
  vendor_invoice_number: string
  invoice_date: string
  due_date: string
  po_id: string
  contract_id: string
  requester_user_id: string
  ship_to_province: string
}

function formFor(bill: BillDetail): HeaderForm {
  return {
    vendor_id: bill.vendor_id ?? '',
    vendor_invoice_number: bill.vendor_invoice_number,
    invoice_date: bill.invoice_date,
    due_date: bill.due_date ?? '',
    po_id: bill.po_id ?? '',
    contract_id: bill.contract_id ?? '',
    requester_user_id: bill.requester_user_id ?? '',
    ship_to_province: bill.ship_to_province ?? '',
  }
}

/** Only the fields that changed, trimmed; an emptied optional field is sent as null (cleared). */
function changesFrom(start: HeaderForm, form: HeaderForm): HeaderChanges {
  const out: Record<string, string | null> = {}
  for (const key of Object.keys(form) as (keyof HeaderForm)[]) {
    const value = form[key].trim()
    if (value !== start[key]) out[key] = value === '' ? null : value
  }
  return out as HeaderChanges
}

/**
 * Edit the bill's header: vendor, invoice number, dates, PO, contract, requester and ship-to province. Only changed
 * fields are sent; saving re-runs the controls on the server, so the flags and the route follow. Amounts and lines
 * come from the invoice and can't be edited (the API has no field for them).
 */
export function HeaderEditModal({ bill, opened, onClose }: { bill: BillDetail; opened: boolean; onClose: () => void }) {
  const vendors = useVendorList()
  const people = usePeople()
  const edit = useEditBill(bill)
  const start = formFor(bill)
  const [form, setForm] = useState<HeaderForm>(start)
  const [shownOpen, setShownOpen] = useState(opened)
  // The dialog stays mounted while the bill changes (so a save's confirmation and close still run once the new bill
  // arrives); its form starts again from the bill as it is now each time it opens. Adjusted during render, as React
  // recommends for state that follows a prop.
  if (opened !== shownOpen) {
    setShownOpen(opened)
    if (opened) setForm(start)
  }
  const changes = changesFrom(start, form)
  const changed = Object.keys(changes).length > 0
  const set = (key: keyof HeaderForm) => (value: string | null) => setForm((f) => ({ ...f, [key]: value ?? '' }))

  function close() {
    edit.reset()
    setForm(formFor(bill))
    onClose()
  }

  function save() {
    edit.mutate(changes, {
      onSuccess: (updated) => {
        const open = updated.latest_run?.flags.filter((f) => f.resolution === 'open').length ?? 0
        notifications.show({
          title: 'Bill updated',
          message: `${bill.bill_id}: controls ran again, ${open} open flag${open === 1 ? '' : 's'}.`,
        })
        close()
      },
    })
  }

  return (
    <Modal opened={opened} onClose={close} title="Edit bill details" size="lg">
      <Stack gap="sm">
        <Text size="sm">
          Correct what intake read. Saving runs the controls again. Amounts and lines come from the invoice and can't be
          edited here: if they were read wrong, the bill has to be voided and the invoice sent again.
        </Text>
        <Select
          label="Vendor"
          required
          searchable
          nothingFoundMessage="No vendor matches"
          data={(vendors.data?.items ?? []).map((v) => ({ value: v.vendor_id, label: `${v.legal_name} (${v.vendor_id})` }))}
          value={form.vendor_id || null}
          onChange={set('vendor_id')}
        />
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
          <TextInput label="Invoice number" required value={form.vendor_invoice_number}
            onChange={(e) => set('vendor_invoice_number')(e.currentTarget.value)} />
          <Select label="Ship-to province" data={PROVINCES} value={form.ship_to_province || null}
            onChange={set('ship_to_province')} clearable />
          <TextInput label="Invoice date" type="date" required value={form.invoice_date}
            onChange={(e) => set('invoice_date')(e.currentTarget.value)} />
          <TextInput label="Due date" type="date" value={form.due_date}
            onChange={(e) => set('due_date')(e.currentTarget.value)} />
          <TextInput label="PO" placeholder="PO-2026-0044" value={form.po_id}
            onChange={(e) => set('po_id')(e.currentTarget.value)} />
          <TextInput label="Contract" placeholder="C018" value={form.contract_id}
            onChange={(e) => set('contract_id')(e.currentTarget.value)} />
        </SimpleGrid>
        <Select
          label="Requester"
          searchable
          clearable
          nothingFoundMessage="No one matches"
          data={(people.data ?? []).map((p) => ({ value: p.user_id, label: `${p.full_name}, ${p.title} (${p.user_id})` }))}
          value={form.requester_user_id || null}
          onChange={set('requester_user_id')}
        />
        {edit.isError && <ErrorAlert error={edit.error} />}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={close}>Cancel</Button>
          <Button onClick={save} disabled={!changed || form.vendor_invoice_number.trim() === '' || form.invoice_date === ''}
            loading={edit.isPending}>
            Save and re-run controls
          </Button>
        </Group>
      </Stack>
    </Modal>
  )
}
