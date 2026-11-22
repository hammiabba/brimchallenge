import { Button, Group, SegmentedControl, Stack, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'
import { useSearchParams } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import type { BankChange, BankChangeStatus } from '../api/types'
import { BANK_CHANGE_STATUS } from '../ui/statusStyles'
import { BankChangesTable } from '../vendors/BankChangesTable'
import { CommentActionModal } from '../vendors/CommentActionModal'
import { useBankChangeDecision, useBankChanges } from '../vendors/queries'
import { useMayDo } from '../vendors/roles'

/** The status tabs; "all" is no filter. The queue opens on what still needs a decision. */
const TABS = [
  { value: 'pending_verification', label: BANK_CHANGE_STATUS.pending_verification.label },
  { value: 'verified', label: BANK_CHANGE_STATUS.verified.label },
  { value: 'rejected', label: BANK_CHANGE_STATUS.rejected.label },
  { value: 'all', label: 'All' },
] as const
type Tab = (typeof TABS)[number]['value']

/** The tab in the URL (?status=verified); anything unknown falls back to pending verification. */
function tabFromSearch(search: URLSearchParams): Tab {
  const value = search.get('status')
  return TABS.find((tab) => tab.value === value)?.value ?? 'pending_verification'
}

/** Verify and Reject for one pending request. The server refuses a person verifying their own request. */
function DecisionButtons({ change }: { change: BankChange }) {
  const [open, setOpen] = useState<'verify' | 'reject' | null>(null)
  const verify = useBankChangeDecision(change.change_id, 'verify')
  const reject = useBankChangeDecision(change.change_id, 'reject')
  if (change.status !== 'pending_verification') return null

  function done(title: string) {
    notifications.show({ title, message: `${change.change_id} for ${change.vendor_name ?? change.vendor_id}` })
    setOpen(null)
  }

  // Verify above Reject, as the payments list stacks its actions, so the Actions column stays narrow.
  return (
    <Stack gap={6} align="flex-start">
      <Button size="xs" onClick={() => setOpen('verify')}>Verify</Button>
      <Button size="xs" variant="default" onClick={() => setOpen('reject')}>Reject</Button>
      <CommentActionModal
        opened={open === 'verify'}
        onClose={() => setOpen(null)}
        title="Verify bank change"
        description={`Confirm you called ${change.vendor_name ?? change.vendor_id} on a number already on file and they confirmed the account ending ${change.new_account_last4}. Say whom you spoke to and on which number. Payments then go to the new account.`}
        mutation={verify}
        onDone={() => done('Bank change verified')}
        // The callback is the control itself, so its record (who was called, on which number) is required.
        commentRequired
      />
      <CommentActionModal
        opened={open === 'reject'}
        onClose={() => setOpen(null)}
        title="Reject bank change"
        description="The current account stays on file and the request is closed."
        mutation={reject}
        onDone={() => done('Bank change rejected')}
        danger
      />
    </Stack>
  )
}

/**
 * /bank-changes: requests to change a vendor's bank details by status, in the server's order. Finance and the controller
 * verify or reject the pending ones (the only roles that see the buttons); AP and auditors read. The server enforces
 * who may decide, and that nobody decides their own request.
 */
export default function BankChangesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = tabFromSearch(searchParams)
  const changes = useBankChanges(tab === 'all' ? null : (tab as BankChangeStatus))
  // Only finance and the controller verify or reject; AP and auditors read, with no Actions column.
  const mayDecide = useMayDo('decideBankChange')

  const empty = tab === 'pending_verification'
    ? 'No bank change is waiting for verification.'
    : tab === 'all' ? 'No bank change has been requested.' : `No ${BANK_CHANGE_STATUS[tab].label.toLowerCase()} bank changes.`

  return (
    <Stack gap="md">
      <Title order={1}>Bank changes</Title>
      <Group>
        <SegmentedControl
          aria-label="Status"
          data={TABS.map((t) => ({ value: t.value, label: t.label }))}
          value={tab}
          onChange={(value) => setSearchParams(value === 'pending_verification' ? {} : { status: value }, { replace: true })}
        />
      </Group>
      {changes.isError ? (
        <ErrorAlert error={changes.error} title="Can't load bank changes" onRetry={() => void changes.refetch()} />
      ) : (
        <>
          <BankChangesTable
            changes={changes.data}
            loading={changes.isPending}
            emptyMessage={empty}
            label="Bank changes"
            showVendor
            actions={mayDecide ? (change) => <DecisionButtons change={change} /> : undefined}
          />
          {changes.data && changes.data.length > 0 && (
            <Text size="sm" c="dimmed">{`${changes.data.length} request${changes.data.length === 1 ? '' : 's'}`}</Text>
          )}
        </>
      )}
    </Stack>
  )
}
