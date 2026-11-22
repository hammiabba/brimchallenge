import { Button, Checkbox, Group, Modal, NumberInput, Select, SimpleGrid, Stack, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import { useGlAccounts } from '../api/reference'
import type { PaymentMethod, VendorInput } from '../api/types'
import { PAYMENT_METHOD_LABELS } from './labels'
import { useOnboardVendor } from './queries'

const METHOD_OPTIONS = Object.entries(PAYMENT_METHOD_LABELS).map(([value, label]) => ({ value, label }))

interface Draft {
  legal_name: string
  category: string
  address: string
  province_or_state: string
  country: string
  ap_contact_email: string
  payment_terms_days: number
  preferred_payment_method: PaymentMethod
  requires_po: boolean
  accepts_card_payment: boolean
  gst_hst_number: string
  qst_number: string
  default_gl_account: string | null
}

const EMPTY: Draft = {
  legal_name: '', category: '', address: '', province_or_state: '', country: 'CA', ap_contact_email: '',
  payment_terms_days: 30, preferred_payment_method: 'EFT', requires_po: false, accepts_card_payment: false,
  gst_hst_number: '', qst_number: '', default_gl_account: null,
}

/** The request body: trimmed text, empty optional fields left out, codes upper-cased as the API expects. */
function toInput(draft: Draft): VendorInput {
  return {
    legal_name: draft.legal_name.trim(),
    category: draft.category.trim(),
    address: draft.address.trim(),
    province_or_state: draft.province_or_state.trim().toUpperCase(),
    country: draft.country.trim().toUpperCase(),
    ap_contact_email: draft.ap_contact_email.trim(),
    payment_terms_days: draft.payment_terms_days,
    preferred_payment_method: draft.preferred_payment_method,
    requires_po: draft.requires_po,
    accepts_card_payment: draft.accepts_card_payment,
    gst_hst_number: draft.gst_hst_number.trim() || null,
    qst_number: draft.qst_number.trim() || null,
    default_gl_account: draft.default_gl_account,
  }
}

/**
 * The onboarding form. A new vendor starts as pending review and can't be paid until finance or the controller
 * approves it. Field rules (lengths, two-letter codes, email shape) are checked by the server; its message shows here.
 */
export function OnboardVendorModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const onboard = useOnboardVendor()
  const accounts = useGlAccounts()
  const navigate = useNavigate()

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => ({ ...current, [key]: value }))
  const complete = [draft.legal_name, draft.category, draft.address, draft.province_or_state, draft.country,
    draft.ap_contact_email].every((value) => value.trim() !== '')

  function close() {
    onboard.reset()
    setDraft(EMPTY)
    onClose()
  }

  function submit() {
    onboard.mutate(toInput(draft), {
      onSuccess: (vendor) => {
        notifications.show({ title: 'Vendor onboarded', message: `${vendor.legal_name} (${vendor.vendor_id}) is pending review.` })
        close()
        void navigate(`/vendors/${vendor.vendor_id}`)
      },
    })
  }

  return (
    <Modal opened={opened} onClose={close} title="Onboard vendor" size="lg">
      <form onSubmit={(event) => { event.preventDefault(); submit() }}>
        <Stack gap="sm">
          <TextInput label="Legal name" required value={draft.legal_name}
            onChange={(e) => set('legal_name', e.currentTarget.value)} maxLength={200} />
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <TextInput label="Category" required placeholder="Freight & Carriers" value={draft.category}
              onChange={(e) => set('category', e.currentTarget.value)} maxLength={100} />
            <TextInput label="AP contact email" required type="email" value={draft.ap_contact_email}
              onChange={(e) => set('ap_contact_email', e.currentTarget.value)} />
          </SimpleGrid>
          <TextInput label="Address" required value={draft.address}
            onChange={(e) => set('address', e.currentTarget.value)} maxLength={300} />
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <TextInput label="Province or state" required description="Two-letter code, e.g. ON" maxLength={2}
              value={draft.province_or_state} onChange={(e) => set('province_or_state', e.currentTarget.value)} />
            <TextInput label="Country" required description="Two-letter code, e.g. CA" maxLength={2}
              value={draft.country} onChange={(e) => set('country', e.currentTarget.value)} />
            <TextInput label="GST/HST number" value={draft.gst_hst_number}
              onChange={(e) => set('gst_hst_number', e.currentTarget.value)} />
            <TextInput label="QST number" value={draft.qst_number}
              onChange={(e) => set('qst_number', e.currentTarget.value)} />
            <NumberInput label="Payment terms (days)" min={0} max={180} allowDecimal={false} allowNegative={false}
              value={draft.payment_terms_days}
              onChange={(value) => set('payment_terms_days', typeof value === 'number' ? value : 0)} />
            <Select label="Payment method" data={METHOD_OPTIONS} value={draft.preferred_payment_method} allowDeselect={false}
              onChange={(value) => value && set('preferred_payment_method', value as PaymentMethod)} />
          </SimpleGrid>
          <Select
            label="Default GL account"
            placeholder="None"
            data={(accounts.data ?? []).map((a) => ({ value: a.account_number, label: `${a.account_number} ${a.name}` }))}
            value={draft.default_gl_account}
            onChange={(value) => set('default_gl_account', value)}
            searchable
            clearable
          />
          <Group gap="lg">
            <Checkbox label="Requires a PO" checked={draft.requires_po}
              onChange={(e) => set('requires_po', e.currentTarget.checked)} />
            <Checkbox label="Accepts card payment" checked={draft.accepts_card_payment}
              onChange={(e) => set('accepts_card_payment', e.currentTarget.checked)} />
          </Group>
          {onboard.isError && <ErrorAlert error={onboard.error} />}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={close}>Cancel</Button>
            <Button type="submit" disabled={!complete} loading={onboard.isPending}>Onboard vendor</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}
