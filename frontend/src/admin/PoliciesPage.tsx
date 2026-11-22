import { Button, Group, Modal, Stack, Table, Text, TextInput, Textarea, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'

import { ErrorAlert } from '../api/ErrorAlert'
import { personName, usePeople } from '../api/reference'
import type { Policy, PolicyPatch } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { stepRoleLabel } from '../bills/labels'
import { DateText, Id } from '../ui/DataText'
import { ADMIN_WRITE_ROLES, usePolicies, useUpdatePolicy } from './queries'
import { TableShell } from './TableShell'

/** The rules' columns; Edit comes last, as on Users, and only for roles that may edit. */
const COLUMNS = ['Rule', 'Type', 'Condition', 'Required', 'Notes', 'Last changed'] as const
/** The Edit column has no heading: its buttons say what they do ("Edit rule P02"). */
const EDIT_COLUMN = ''
const TYPE_LABELS: Record<Policy['rule_type'], string> = {
  approval: 'Approval',
  payment_release: 'Payment release',
  match: 'Match',
}

/**
 * Edit a rule's condition, requirement and notes. A rule with an amount in its condition must keep one, because
 * routing reads the threshold from that text; the server says so if it is removed.
 */
function EditPolicyModal({ policy, onClose }: { policy: Policy; onClose: () => void }) {
  const update = useUpdatePolicy(policy.rule_id)
  const [condition, setCondition] = useState(policy.condition)
  const [required, setRequired] = useState(policy.required)
  const [notes, setNotes] = useState(policy.notes ?? '')

  const patch: PolicyPatch = {}
  if (condition.trim() !== policy.condition) patch.condition = condition.trim()
  if (required.trim() !== policy.required) patch.required = required.trim()
  if (notes.trim() !== (policy.notes ?? '')) patch.notes = notes.trim() || null

  function save() {
    update.mutate(patch, {
      onSuccess: () => {
        notifications.show({ title: 'Policy updated', message: `Rule ${policy.rule_id}` })
        onClose()
      },
    })
  }

  return (
    <Modal opened onClose={onClose} title={`Edit rule ${policy.rule_id}`} size="lg">
      <form onSubmit={(event) => { event.preventDefault(); save() }}>
        <Stack gap="sm">
          <TextInput label="Condition" value={condition} onChange={(e) => setCondition(e.currentTarget.value)}
            description='Keep the amount in approval thresholds, e.g. "Invoice total over $10,000 CAD".' />
          <TextInput label="Required" value={required} onChange={(e) => setRequired(e.currentTarget.value)}
            description="Approver roles in order, e.g. dept_manager > finance_manager" />
          <Textarea label="Notes" value={notes} onChange={(e) => setNotes(e.currentTarget.value)} rows={2} />
          {update.isError && <ErrorAlert error={update.error} />}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={Object.keys(patch).length === 0} loading={update.isPending}>Save changes</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}

/** Policy steps that aren't approval roles, in words. */
const REQUIRED_WORDS: Record<string, string> = {
  delegate_user_id: "The absent approver's delegate",
}

/**
 * One step of a rule's "Required" text in words: a role code as the approval route names it ("dept_manager" ->
 * "Department manager"), a known field ("delegate_user_id"), or the rule's own prose ("approver's manager") with a
 * capital letter.
 */
function requiredStep(step: string): string {
  if (REQUIRED_WORDS[step]) return REQUIRED_WORDS[step]
  if (/^[a-z]+(_[a-z]+)*$/.test(step) && step.includes('_') || step === 'cfo') return stepRoleLabel(step)
  return step.charAt(0).toUpperCase() + step.slice(1)
}

/**
 * The approver chain ("dept_manager > finance_manager > controller_admin") in words, one step per line:
 * "Department manager", "then Finance manager", "then Controller". The stored text is unchanged (routing reads it).
 */
function RequiredCell({ required }: { required: string }) {
  const steps = required.split('>').map((step) => step.trim()).filter(Boolean)
  return (
    <Stack gap={0}>
      {steps.map((step, index) => (
        <Text key={`${step}-${index}`} size="sm">{`${index > 0 ? 'then ' : ''}${requiredStep(step)}`}</Text>
      ))}
    </Stack>
  )
}

/**
 * When a rule last changed. A rule nobody has edited still has the date the dataset was loaded (stored as midnight
 * UTC, which would read as the evening before in Toronto), so it shows that date alone; an edit shows its time and
 * who made it.
 */
function LastChanged({ policy, people }: { policy: Policy; people: ReturnType<typeof usePeople>['data'] }) {
  if (!policy.updated_by) {
    return (
      <Stack gap={0}>
        <Text size="sm"><DateText value={policy.updated_at.slice(0, 10)} /></Text>
        <Text size="xs" c="dimmed">From the dataset</Text>
      </Stack>
    )
  }
  return (
    <Stack gap={0}>
      <Text size="sm"><DateText value={policy.updated_at} kind="timestamp" /></Text>
      <Text size="xs" c="dimmed">{personName(policy.updated_by, people)}</Text>
    </Stack>
  )
}

/** /admin/policies: the approval, payment-release and match rules, as routing and the controls read them. */
export default function PoliciesPage() {
  const policies = usePolicies()
  const people = usePeople()
  const [editing, setEditing] = useState<Policy | null>(null)
  const rows = policies.data ?? []
  // Auditors read this page; only the roles the server lets edit policies get the Edit column (display only).
  const mayEdit = ADMIN_WRITE_ROLES.includes(useCurrentUser().role)
  const columns = mayEdit ? [...COLUMNS, EDIT_COLUMN] : COLUMNS

  return (
    <Stack gap="md">
      <Title order={1}>Policies</Title>
      {policies.isError ? (
        <ErrorAlert error={policies.error} title="Can't load policies" onRetry={() => void policies.refetch()} />
      ) : (
        <TableShell label="Policies" columns={columns} loading={policies.isPending} empty={rows.length === 0}
          emptyMessage="No policies yet." minWidth={900}>
          {rows.map((policy) => (
            <Table.Tr key={policy.rule_id}>
              <Table.Td><Id>{policy.rule_id}</Id></Table.Td>
              <Table.Td>{TYPE_LABELS[policy.rule_type]}</Table.Td>
              {/* Shown with spaces for underscores ("pending_review" -> "pending review"); the stored text is kept. */}
              <Table.Td>{policy.condition.replace(/_/g, ' ')}</Table.Td>
              <Table.Td><RequiredCell required={policy.required} /></Table.Td>
              <Table.Td><Text size="sm">{policy.notes ?? ''}</Text></Table.Td>
              <Table.Td><LastChanged policy={policy} people={people.data} /></Table.Td>
              {mayEdit && (
                <Table.Td>
                  <Button size="xs" variant="default" onClick={() => setEditing(policy)}
                    aria-label={`Edit rule ${policy.rule_id}`}>Edit</Button>
                </Table.Td>
              )}
            </Table.Tr>
          ))}
        </TableShell>
      )}
      {editing && <EditPolicyModal policy={editing} onClose={() => setEditing(null)} />}
    </Stack>
  )
}
