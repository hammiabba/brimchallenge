import { Button, Group, List, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'

import { ApiError } from '../../api/errors'
import { ErrorAlert } from '../../api/ErrorAlert'
import { codeAsWords, personName, useFlagHelp, usePeople } from '../../api/reference'
import type { BillDetail } from '../../api/types'
import { useCurrentUser } from '../../auth/context'
import { stepRoleLabel } from '../labels'
import { useSubmitBill } from '../mutations'

/** Bill statuses AP works on before approval. */
const IN_REVIEW = new Set(['needs_review', 'on_hold'])

/** The codes of the open blocking flags on the latest controls run. */
function openBlocking(bill: BillDetail): string[] {
  return (bill.latest_run?.flags ?? []).filter((f) => f.severity === 'block' && f.resolution === 'open').map((f) => f.code)
}

/** The codes a 409 bill.blocked refusal names (details.open_blocking_flags), if it is one. */
function refusedCodes(error: unknown): string[] {
  if (!(error instanceof ApiError) || error.code !== 'bill.blocked') return []
  const codes = (error.details as { open_blocking_flags?: unknown } | null)?.open_blocking_flags
  return Array.isArray(codes) ? codes.filter((c): c is string => typeof c === 'string') : []
}

/**
 * Submit for approval, for AP on a bill in review. allowed_actions.submit says whether the server would accept it;
 * when not, the button is disabled and the reasons are listed: the open blocking flags by name, or the server's
 * reason (no approval route yet, a history bill). A refusal on submit (the controls run again first and may raise a
 * new block) is shown with the flags it names.
 */
export function SubmitBar({ bill }: { bill: BillDetail }) {
  const user = useCurrentUser()
  const flagHelp = useFlagHelp()
  const people = usePeople()
  const submit = useSubmitBill(bill)
  const action = bill.allowed_actions?.submit
  if (!action || user.role !== 'ap_clerk' || !IN_REVIEW.has(bill.status)) return null

  const title = (code: string) => flagHelp.data?.[code]?.title ?? codeAsWords(code)
  const blocking = action.allowed ? [] : openBlocking(bill)
  const refused = refusedCodes(submit.error)

  function send() {
    submit.mutate(undefined, {
      onSuccess: (updated) => {
        const first = updated.current_step
        notifications.show({
          title: 'Submitted for approval',
          message: first
            ? `${bill.bill_id}: step ${first.step_no} (${stepRoleLabel(first.role)}) goes to ${personName(first.user_id, people.data)}.`
            : bill.bill_id,
        })
      },
    })
  }

  return (
    <Stack component="section" aria-label="Ready for approval" gap="xs">
      <Group justify="space-between" align="center" gap="sm">
        <Text size="sm" fw={600}>
          {action.allowed ? 'Ready for approval: the controls found nothing blocking.' : 'Not ready for approval yet.'}
        </Text>
        <Button onClick={send} disabled={!action.allowed} loading={submit.isPending}>Submit for approval</Button>
      </Group>
      {!action.allowed && (blocking.length > 0 ? (
        <Stack gap={2}>
          <Text size="sm">Resolve or override these blocking flags first:</Text>
          <List size="sm">{blocking.map((code) => <List.Item key={code}>{title(code)}</List.Item>)}</List>
        </Stack>
      ) : (
        action.reason && <Text size="sm">{action.reason}</Text>
      ))}
      {submit.isError && (
        <Stack gap={4}>
          <ErrorAlert error={submit.error} title="Not submitted" />
          {refused.length > 0 && (
            <List size="sm" aria-label="Blocking flags">
              {refused.map((code) => <List.Item key={code}>{title(code)}</List.Item>)}
            </List>
          )}
        </Stack>
      )}
    </Stack>
  )
}
