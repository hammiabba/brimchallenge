import { Box, Group, Stack, Text, Title } from '@mantine/core'
import { IconAlertTriangle, IconCircleCheck, IconCircleDashed, IconCircleX } from '@tabler/icons-react'
import { Fragment } from 'react'

import { personName, usePeople } from '../../api/reference'
import type { BillDetail, Decision, RouteStep } from '../../api/types'
import { STATUS_TONES, TEXT } from '../../theme'
import { DateText, Id } from '../../ui/DataText'
import { Icon } from '../../ui/Icon'
import { stepRoleLabel } from '../labels'

/** "Approved by Raj Patel (U010) on behalf of Sam Rivera, Mar 9, 2026, 10:52 AM EST", then the comment. */
function DecisionLine({ decision }: { decision: Decision }) {
  const people = usePeople()
  const verb = decision.decision === 'approved' ? 'Approved' : 'Rejected'
  return (
    <Stack gap={0}>
      <Text size="sm">
        {`${verb} by ${personName(decision.actor_user_id, people.data)} `}<Id>{decision.actor_user_id}</Id>
        {decision.on_behalf_of && `, on behalf of ${personName(decision.on_behalf_of, people.data)}`}
        {', '}<DateText value={decision.acted_at} kind="timestamp" />
      </Text>
      {decision.comment && <Text size="sm" c="dimmed">{`Comment: ${decision.comment}`}</Text>}
    </Stack>
  )
}

/** "Wen Zhao (U010)", or the id alone for someone the people list doesn't have. */
function personWithId(userId: string, people: ReturnType<typeof usePeople>['data']): string {
  const name = personName(userId, people)
  return name === userId ? userId : `${name} (${userId})`
}

/**
 * How a decision's signer differs from the step's assigned approver: the bill's requester approving their own bill
 * (policy P07), someone else, or not at all. A decision is the assignee's own when they made it, or when it was made
 * on their behalf (a delegate).
 */
function signerMismatch(step: RouteStep, decision: Decision, requesterId: string | null): 'requester' | 'other' | null {
  const assigned = step.user_id
  if (!assigned || decision.actor_user_id === assigned || decision.on_behalf_of === assigned) return null
  return decision.decision === 'approved' && requesterId !== null && decision.actor_user_id === requesterId
    ? 'requester'
    : 'other'
}

/**
 * Who actually signed, when it wasn't the step's assigned approver: an attention marker for someone else, the danger
 * tone for the requester approving their own bill. The decision line above already names the signer with their id.
 */
function SignerCheck({ step, decision, requesterId }: { step: RouteStep; decision: Decision; requesterId: string | null }) {
  const people = usePeople()
  const mismatch = signerMismatch(step, decision, requesterId)
  if (!mismatch || !step.user_id) return null
  const tone = mismatch === 'requester' ? STATUS_TONES.danger : STATUS_TONES.attention
  const signer = personName(decision.actor_user_id, people.data)
  const assigned = personName(step.user_id, people.data)
  return (
    <Group gap={6} wrap="nowrap" align="flex-start" c={tone.color}>
      <Box pt={2}><Icon icon={IconAlertTriangle} size={14} /></Box>
      <Text size="sm" fw={500} c={tone.color}>
        {mismatch === 'requester'
          ? `${signer} approved their own bill; policy P07 needed their manager, ${assigned}, to sign.`
          : `Signed by ${personWithId(decision.actor_user_id, people.data)}, not the assigned approver ${personWithId(step.user_id, people.data)}.`}
      </Text>
    </Group>
  )
}

/**
 * The bullet for a step: rejected, approved, or no decision yet. An approval signed by someone other than the
 * assigned approver gets the warning triangle in the same tone as its marker, not a green check, so the timeline
 * never shows a broken step as a clean one.
 */
function StepBullet({ step, decisions, requesterId }: {
  step: RouteStep
  decisions: readonly Decision[]
  requesterId: string | null
}) {
  if (decisions.some((d) => d.decision === 'rejected')) {
    return <Text span c={STATUS_TONES.danger.color}><Icon icon={IconCircleX} size={18} /></Text>
  }
  const mismatches = decisions.map((d) => signerMismatch(step, d, requesterId))
  if (mismatches.includes('requester')) {
    return <Text span c={STATUS_TONES.danger.color}><Icon icon={IconAlertTriangle} size={18} /></Text>
  }
  if (mismatches.includes('other')) {
    return <Text span c={STATUS_TONES.attention.color}><Icon icon={IconAlertTriangle} size={18} /></Text>
  }
  if (decisions.some((d) => d.decision === 'approved')) {
    return <Text span c={STATUS_TONES.success.color}><Icon icon={IconCircleCheck} size={18} /></Text>
  }
  return <Text span c={TEXT.secondary}><Icon icon={IconCircleDashed} size={18} /></Text>
}

/**
 * One route step on the timeline, with the decisions recorded for its step number, each followed by a marker when
 * someone other than the assigned approver signed it.
 */
function StepItem({ step, decisions, requesterId }: {
  step: RouteStep
  decisions: readonly Decision[]
  requesterId: string | null
}) {
  const people = usePeople()
  return (
    <Box component="li" className="app-timeline-item">
      <span className="app-timeline-bullet"><StepBullet step={step} decisions={decisions} requesterId={requesterId} /></span>
      <Stack gap={2}>
        <Text size="sm" fw={600}>{`Step ${step.step_no}: ${stepRoleLabel(step.role)}`}</Text>
        <Text size="sm">
          {step.user_id
            ? <>{personName(step.user_id, people.data)} <Id>{step.user_id}</Id></>
            : 'Unassigned: nobody eligible to sign was found'}
        </Text>
        {(step.delegated_from || step.escalated_from) && (
          <Text size="sm">
            {step.delegated_from && `Delegate for ${personName(step.delegated_from, people.data)}`}
            {step.delegated_from && step.escalated_from && '; '}
            {step.escalated_from && `Escalated from ${personName(step.escalated_from, people.data)}`}
          </Text>
        )}
        <Text size="xs" c="dimmed">
          {step.policy_ids.length > 0 && (
            <>
              {step.policy_ids.length === 1 ? 'Policy ' : 'Policies '}
              {step.policy_ids.map((policy, index) => (
                <Fragment key={policy}>{index > 0 && ', '}<Id>{policy}</Id></Fragment>
              ))}
              {step.reason && ': '}
            </>
          )}
          {step.reason}
        </Text>
        {decisions.length > 0
          ? decisions.map((d) => (
            <Fragment key={d.decision_id}>
              <DecisionLine decision={d} />
              <SignerCheck step={step} decision={d} requesterId={requesterId} />
            </Fragment>
          ))
          : <Text size="sm" c="dimmed">No decision recorded for this step.</Text>}
      </Stack>
    </Box>
  )
}

/**
 * The approval route from the latest controls run, as a vertical timeline, with every recorded decision under its
 * step. Decisions whose step number isn't on the route (history can differ from the replayed route) are listed
 * after it.
 */
export function ApprovalRoute({ bill }: { bill: BillDetail }) {
  const run = bill.latest_run
  const steps = run?.route ?? []
  const stepNumbers = new Set(steps.map((s) => s.step_no))
  const other = bill.decisions.filter((d) => !stepNumbers.has(d.step_no))

  return (
    <Stack gap="sm">
      <Title order={2}>Approval route</Title>
      {run ? (
        <Text size="sm" c="dimmed">
          {`Controls run version ${run.version}, evaluated `}<DateText value={run.evaluated_at} kind="timestamp" />.
        </Text>
      ) : (
        <Text size="sm">No controls run yet, so this bill has no approval route.</Text>
      )}
      {run?.recommendation && <Text size="sm">{`Recommendation: ${run.recommendation}`}</Text>}
      {run && steps.length === 0 && <Text size="sm">This controls run produced no approval steps.</Text>}
      {steps.length > 0 && (
        <Box component="ol" className="app-timeline" aria-label="Approval steps">
          {steps.map((step) => (
            <StepItem
              key={step.step_no}
              step={step}
              decisions={bill.decisions.filter((d) => d.step_no === step.step_no)}
              requesterId={bill.requester_user_id ?? null}
            />
          ))}
        </Box>
      )}
      {other.length > 0 && (
        <Stack gap={4}>
          <Title order={3}>{steps.length > 0 ? 'Other decisions' : 'Decisions'}</Title>
          {other.map((d) => (
            <Group key={d.decision_id} gap={6} align="flex-start" wrap="nowrap">
              <Text size="sm" fw={600}>{`Step ${d.step_no}`}</Text>
              <DecisionLine decision={d} />
            </Group>
          ))}
        </Stack>
      )}
    </Stack>
  )
}
