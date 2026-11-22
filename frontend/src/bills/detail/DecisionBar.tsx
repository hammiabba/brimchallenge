import { Button, Group, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'

import { personName, usePeople } from '../../api/reference'
import type { BillDetail } from '../../api/types'
import { useBillDecision } from '../../approvals/queries'
import { CommentActionModal } from '../../vendors/CommentActionModal'
import { stepRoleLabel } from '../labels'

/**
 * Approve and Reject for the signed-in user, shown only when the server's allowed_actions says they may decide now
 * (controls.can_approve: their step, their limit, not their own bill, P08 delegation). Rejecting needs a comment.
 * The server checks again on submit; a refusal (403, 409 when someone else changed the bill) shows in the dialog.
 */
export function DecisionBar({ bill }: { bill: BillDetail }) {
  const people = usePeople()
  const [open, setOpen] = useState<'approve' | 'reject' | null>(null)
  const approve = useBillDecision(bill.bill_id, bill.row_version, 'approve')
  const reject = useBillDecision(bill.bill_id, bill.row_version, 'reject')
  const canApprove = bill.allowed_actions?.approve?.allowed ?? false
  const canReject = bill.allowed_actions?.reject?.allowed ?? false
  if (!canApprove && !canReject) return null

  const step = bill.current_step
  const lastStep = Math.max(0, ...(bill.latest_run?.route ?? []).map((s) => s.step_no))
  const final = step ? step.step_no >= lastStep : false

  function done(title: string) {
    notifications.show({ title, message: `${bill.bill_id} from ${bill.vendor_name ?? 'an unmatched vendor'}` })
    setOpen(null)
  }

  return (
    <Group component="section" aria-label="Your decision" justify="space-between" align="center" gap="sm">
      <Stack gap={0}>
        <Text size="sm" fw={600}>
          {step ? `Step ${step.step_no}, ${stepRoleLabel(step.role)}, is waiting for you` : 'This bill is waiting for you'}
        </Text>
        {step?.delegated_from && (
          <Text size="sm">{`Acting for ${personName(step.delegated_from, people.data)}: your decision is recorded on their behalf.`}</Text>
        )}
      </Stack>
      <Group gap="sm" wrap="nowrap">
        {canApprove && <Button onClick={() => setOpen('approve')}>Approve</Button>}
        {canReject && <Button variant="default" onClick={() => setOpen('reject')}>Reject</Button>}
      </Group>
      <CommentActionModal
        opened={open === 'approve'}
        onClose={() => setOpen(null)}
        title="Approve bill"
        description={final
          ? 'This is the last step: the bill becomes approved and AP can schedule its payment.'
          : 'The bill moves on to the next step of its approval route.'}
        mutation={approve}
        onDone={() => done('Bill approved')}
      />
      <CommentActionModal
        opened={open === 'reject'}
        onClose={() => setOpen(null)}
        title="Reject bill"
        description="The bill is rejected and won't be paid. Say why: AP and the requester read your comment."
        mutation={reject}
        onDone={() => done('Bill rejected')}
        danger
        commentRequired
      />
    </Group>
  )
}
