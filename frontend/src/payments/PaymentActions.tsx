import { Button, Group, Modal, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'

import { ErrorAlert } from '../api/ErrorAlert'
import type { PaymentDetail, Role } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { PAYMENT_METHOD_LABELS } from '../bills/labels'
import { MoneyText } from '../ui/DataText'
import { newIdempotencyKey, usePayment, useReleasePayment } from './queries'

/** The roles that release payments; they are told why when they can't release this one. */
const RELEASER_ROLES: readonly Role[] = ['finance_manager', 'controller_admin']

/**
 * Confirms a release. The Idempotency-Key is made when the dialog opens and kept for every retry of this attempt, so a
 * release that reached the server but lost its answer is never paid twice. Refusals (P11, over the release limit, an
 * open block flag, a bank account changed since scheduling) show here with the server's message and request id.
 */
function ReleaseModal({ payment, opened, onClose }: { payment: PaymentDetail; opened: boolean; onClose: () => void }) {
  const release = useReleasePayment(payment.payment_id)
  const [key, setKey] = useState(newIdempotencyKey)
  const account = payment.bank_account

  function close() {
    release.reset()
    setKey(newIdempotencyKey())
    onClose()
  }

  function confirm() {
    release.mutate(key, {
      onSuccess: (released) => {
        notifications.show({
          title: 'Payment released',
          message: `${released.payment_id} to ${released.vendor_name ?? released.vendor_id}`,
        })
        close()
      },
    })
  }

  return (
    <Modal opened={opened} onClose={close} title="Release payment">
      <Stack gap="sm">
        <Text size="sm">
          {'Send '}<MoneyText value={payment.amount} currency={payment.currency} />
          {` to ${payment.vendor_name ?? payment.vendor_id} by ${PAYMENT_METHOD_LABELS[payment.method] ?? payment.method}`}
          {payment.method === 'EFT' && account ? `, to the account ending ${account.account_last4}` : ''}
          {'. The payment is simulated, and it can\'t be undone here.'}
        </Text>
        {release.isError && <ErrorAlert error={release.error} />}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={close}>Cancel</Button>
          <Button onClick={confirm} loading={release.isPending}>Release payment</Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/**
 * The actions on one payment, from its allowed_actions (GET /payments/{id}): only what the server says the signed-in
 * user may do now. A releaser who can't release it sees why (for example P11: they approved the bill).
 */
export function PaymentActions({ paymentId }: { paymentId: string }) {
  const user = useCurrentUser()
  const payment = usePayment(paymentId)
  const [open, setOpen] = useState<'release' | null>(null)
  const data = payment.data
  if (!data) return null
  const release = data.allowed_actions?.release
  const releaser = RELEASER_ROLES.includes(user.role)

  return (
    <Group gap="xs" wrap="nowrap">
      {release?.allowed && <Button size="xs" onClick={() => setOpen('release')}>Release</Button>}
      {release && !release.allowed && releaser && data.status === 'scheduled' && release.reason && (
        <Text size="sm" c="dimmed">{release.reason}</Text>
      )}
      {release?.allowed && <ReleaseModal payment={data} opened={open === 'release'} onClose={() => setOpen(null)} />}
    </Group>
  )
}
