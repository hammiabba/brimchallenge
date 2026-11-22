import { Anchor, Box, Button, Divider, Group, SimpleGrid, Skeleton, Stack, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle } from '@tabler/icons-react'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '../api/errors'
import { ErrorAlert } from '../api/ErrorAlert'
import { glAccountName, useGlAccounts, useVendor } from '../api/reference'
import type { VendorDetail } from '../api/types'
import { STATUS_TONES } from '../theme'
import { StatusBadge } from '../ui/Badges'
import { DateText, Id } from '../ui/DataText'
import { Icon } from '../ui/Icon'
import { BankChangeModal } from './BankChangeModal'
import { BankChangesTable } from './BankChangesTable'
import { CommentActionModal } from './CommentActionModal'
import { PAYMENT_METHOD_LABELS, termsLabel } from './labels'
import { useVendorDecision } from './queries'
import { useMayDo } from './roles'

/** One label and value in the details grid. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="sm" component="div">{children}</Text>
    </Stack>
  )
}

/**
 * Approve (pending review or on hold: finance and the controller) and Hold (anything not on hold: AP, finance and the
 * controller), each shown only to the roles the API allows. The server checks every request.
 */
function VendorActions({ vendor }: { vendor: VendorDetail }) {
  const [open, setOpen] = useState<'approve' | 'hold' | null>(null)
  const approve = useVendorDecision(vendor.vendor_id, 'approve')
  const hold = useVendorDecision(vendor.vendor_id, 'hold')
  const mayApprove = useMayDo('approve') && vendor.status !== 'active'
  const mayHold = useMayDo('hold') && vendor.status !== 'on_hold'
  if (!mayApprove && !mayHold) return null

  function done(title: string) {
    notifications.show({ title, message: `${vendor.legal_name} (${vendor.vendor_id})` })
    setOpen(null)
  }

  return (
    <Group gap="sm">
      {mayApprove && <Button onClick={() => setOpen('approve')}>Approve vendor</Button>}
      {mayHold && <Button variant="default" onClick={() => setOpen('hold')}>Put on hold</Button>}
      <CommentActionModal
        opened={open === 'approve'}
        onClose={() => setOpen(null)}
        title="Approve vendor"
        description="The vendor becomes active and its bills can be paid."
        mutation={approve}
        onDone={() => done('Vendor approved')}
      />
      <CommentActionModal
        opened={open === 'hold'}
        onClose={() => setOpen(null)}
        title="Put on hold"
        description="No payment to this vendor can be released while it is on hold."
        mutation={hold}
        onDone={() => done('Vendor on hold')}
        danger
      />
    </Group>
  )
}

/**
 * The bank account on file: full numbers for AP, finance and the controller; the last 4 for everyone else. Only AP
 * may request a change (someone else verifies it).
 */
function BankAccountSection({ vendor }: { vendor: VendorDetail }) {
  const [requesting, setRequesting] = useState(false)
  const mayRequest = useMayDo('requestBankChange')
  const account = vendor.bank_account
  // The account on file can be one a change put there before anyone verified it (the dataset's BC-009 was applied
  // straight from an email). Then it is the pending change's new account, and the page says so instead of showing it
  // as a settled account.
  const unverified = account
    ? vendor.bank_changes.find((c) => c.status === 'pending_verification' && c.new_account_last4 === account.account_last4)
    : undefined
  return (
    <Stack gap="sm">
      <Group justify="space-between">
        <Title order={2}>Bank account</Title>
        {mayRequest && <Button variant="default" size="xs" onClick={() => setRequesting(true)}>Request bank change</Button>}
      </Group>
      {account ? (
        <SimpleGrid cols={{ base: 2, md: 4 }} spacing="md">
          <Field label="Institution"><Id>{account.institution}</Id></Field>
          <Field label="Transit"><Id>{account.transit}</Id></Field>
          <Field label="Account">{account.masked ? `Ending ${account.account_last4}` : <Id>{account.account}</Id>}</Field>
          <Field label="On file since"><DateText value={account.valid_from} /></Field>
        </SimpleGrid>
      ) : (
        <Text size="sm" c="dimmed">{mayRequest ? 'No bank account on file. Request a change to add one.' : 'No bank account on file.'}</Text>
      )}
      {unverified && (
        <Group gap={6} wrap="nowrap" align="flex-start" role="status">
          <Box pt={2} c={STATUS_TONES.attention.color}><Icon icon={IconAlertTriangle} size={16} /></Box>
          <Text size="sm" fw={500}>
            {'Not verified: this account came in through '}<Id>{unverified.change_id}</Id>
            {', which nobody has confirmed by phone yet. New payments to this vendor are held until it is verified.'}
          </Text>
        </Group>
      )}
      <Title order={3} mt="xs">Change requests</Title>
      <BankChangesTable
        changes={vendor.bank_changes}
        loading={false}
        emptyMessage="No bank change has been requested for this vendor."
        label="Bank change requests"
      />
      {mayRequest && (
        <BankChangeModal vendorId={vendor.vendor_id} vendorName={vendor.legal_name} opened={requesting}
          onClose={() => setRequesting(false)} />
      )}
    </Stack>
  )
}

/** The vendor's terms, tax numbers and contact. */
function VendorDetails({ vendor }: { vendor: VendorDetail }) {
  const accounts = useGlAccounts()
  const gl = vendor.default_gl_account
  return (
    <Stack gap="sm">
      <Title order={2}>Details</Title>
      <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} spacing="md">
        <Field label="Category">{vendor.category}</Field>
        <Field label="Address">{vendor.address}</Field>
        <Field label="Province or state">{`${vendor.province_or_state}, ${vendor.country}`}</Field>
        <Field label="AP contact">{vendor.ap_contact_email}</Field>
        <Field label="Payment terms">{termsLabel(vendor.payment_terms_days)}</Field>
        <Field label="Early payment discount">{vendor.early_pay_discount ?? 'None'}</Field>
        <Field label="Payment method">{PAYMENT_METHOD_LABELS[vendor.preferred_payment_method]}</Field>
        <Field label="Accepts card">{vendor.accepts_card_payment ? 'Yes' : 'No'}</Field>
        <Field label="PO required">{vendor.requires_po ? 'Yes' : 'No'}</Field>
        <Field label="GST/HST number">{vendor.gst_hst_number ? <Id>{vendor.gst_hst_number}</Id> : 'None'}</Field>
        <Field label="QST number">{vendor.qst_number ? <Id>{vendor.qst_number}</Id> : 'None'}</Field>
        <Field label="Default GL account">
          {gl ? <><Id>{gl}</Id>{glAccountName(gl, accounts.data) ? ` ${glAccountName(gl, accounts.data)}` : ''}</> : 'None'}
        </Field>
        <Field label="Onboarded"><DateText value={vendor.onboarded_at} /></Field>
      </SimpleGrid>
    </Stack>
  )
}

/** /vendors/:vendorId: one vendor with its actions, details, bank account and bank change history. */
export default function VendorDetailPage() {
  const { vendorId = '' } = useParams()
  const vendor = useVendor(vendorId)

  if (vendor.isPending) {
    return (
      <Stack gap="md" aria-busy="true" aria-label="Loading vendor">
        <Skeleton animate={false} height={28} width={260} />
        <Skeleton animate={false} height={160} />
      </Stack>
    )
  }
  if (vendor.error instanceof ApiError && vendor.error.status === 404) {
    return (
      <Stack gap="sm" maw={720}>
        <Title order={1}>Vendor not found</Title>
        <Text>There is no vendor <Id>{vendorId}</Id>.</Text>
        <Anchor component={Link} to="/vendors" size="sm" w="fit-content">Back to vendors</Anchor>
      </Stack>
    )
  }
  if (vendor.isError) {
    return <ErrorAlert error={vendor.error} title="Can't load this vendor" onRetry={() => void vendor.refetch()} />
  }

  const data = vendor.data
  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Anchor component={Link} to="/vendors" size="sm" w="fit-content">Vendors</Anchor>
          <Group gap="sm" align="center">
            <Title order={1}>{data.legal_name}</Title>
            <StatusBadge kind="vendor" status={data.status} />
          </Group>
          <Text size="sm" c="dimmed"><Id>{data.vendor_id}</Id></Text>
        </Stack>
        <VendorActions vendor={data} />
      </Group>
      <Divider />
      <VendorDetails vendor={data} />
      <Divider />
      <BankAccountSection vendor={data} />
    </Stack>
  )
}
