import { Button, Group, Modal, Select, SimpleGrid, Stack, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'

import { ErrorAlert } from '../api/ErrorAlert'
import type { BankChangeChannel } from '../api/types'
import { CHANNEL_LABELS } from './labels'
import { useRequestBankChange } from './queries'

const CHANNEL_OPTIONS = Object.entries(CHANNEL_LABELS).map(([value, label]) => ({ value, label }))

/** Keeps only digits, so pasted numbers with spaces or dashes still fit the API's digit-only patterns. */
function digits(value: string): string {
  return value.replace(/\D/g, '')
}

interface BankChangeModalProps {
  vendorId: string
  vendorName: string
  opened: boolean
  onClose: () => void
}

/**
 * Request new bank details for a vendor. The change waits as pending verification: someone else confirms it with the
 * vendor on a number already on file before payments go to the new account.
 */
export function BankChangeModal({ vendorId, vendorName, opened, onClose }: BankChangeModalProps) {
  const [institution, setInstitution] = useState('')
  const [transit, setTransit] = useState('')
  const [account, setAccount] = useState('')
  const [channel, setChannel] = useState<BankChangeChannel | null>(null)
  const request = useRequestBankChange(vendorId)

  const valid = /^\d{3}$/.test(institution) && /^\d{5}$/.test(transit) && /^\d{5,12}$/.test(account) && channel !== null

  function close() {
    request.reset()
    setInstitution('')
    setTransit('')
    setAccount('')
    setChannel(null)
    onClose()
  }

  function submit() {
    if (!channel) return
    request.mutate({ institution, transit, account, request_channel: channel }, {
      onSuccess: (change) => {
        notifications.show({ title: 'Bank change requested', message: `${change.change_id} is waiting for verification.` })
        close()
      },
    })
  }

  return (
    <Modal opened={opened} onClose={close} title="Request bank change">
      <form onSubmit={(event) => { event.preventDefault(); submit() }}>
        <Stack gap="sm">
          <Text size="sm">{`New bank details for ${vendorName}. Payments keep going to the current account until someone else verifies the change.`}</Text>
          <SimpleGrid cols={2} spacing="sm">
            <TextInput label="Institution" description="3 digits" required inputMode="numeric" maxLength={3}
              value={institution} onChange={(e) => setInstitution(digits(e.currentTarget.value))} />
            <TextInput label="Transit" description="5 digits" required inputMode="numeric" maxLength={5}
              value={transit} onChange={(e) => setTransit(digits(e.currentTarget.value))} />
          </SimpleGrid>
          <TextInput label="Account number" description="5 to 12 digits" required inputMode="numeric" maxLength={12}
            value={account} onChange={(e) => setAccount(digits(e.currentTarget.value))} />
          <Select label="How the request came in" required data={CHANNEL_OPTIONS} value={channel}
            onChange={(value) => setChannel(value as BankChangeChannel | null)} />
          {request.isError && <ErrorAlert error={request.error} />}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={close}>Cancel</Button>
            <Button type="submit" disabled={!valid} loading={request.isPending}>Request change</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}
