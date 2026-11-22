import { Anchor, Button, Group, Modal, Select, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'
import { Link } from 'react-router'

import { ErrorAlert } from '../api/ErrorAlert'
import { departmentLabel, personName, useDepartments, usePeople } from '../api/reference'
import type { BillSummary, Role } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { stepRoleLabel } from '../bills/labels'
import { Id, MoneyText } from '../ui/DataText'
import { useAssignStep, useUnassignedSteps } from './queries'

/** Who may assign an approver (the server checks this too: POST /bills/{id}/route/{step}/assign). */
const ASSIGNER_ROLES: readonly Role[] = ['finance_manager', 'controller_admin']

/**
 * Which user roles may sign each kind of step, as the server checks it (controls.approvals.STEP_ROLES). Escalation
 * only goes up, so higher roles may sign lower steps.
 */
const STEP_SIGNERS: Record<string, readonly Role[]> = {
  dept_manager: ['approver', 'finance_manager', 'controller_admin'],
  finance_manager: ['finance_manager', 'controller_admin'],
  controller_admin: ['controller_admin'],
  cfo: ['controller_admin'],
}

const COLUMNS = ['Bill', 'Vendor', 'Department', 'Total (CAD)', 'Step', 'Requester'] as const
const NUMERIC = new Set<string>(['Total (CAD)'])
const SKELETON_ROWS = 4

/** The dialog to pick who signs the step: active people whose role may sign it, never the bill's requester. */
function AssignModal({ bill, opened, onClose }: { bill: BillSummary; opened: boolean; onClose: () => void }) {
  const step = bill.current_step!
  const people = usePeople()
  const [userId, setUserId] = useState<string | null>(null)
  const assign = useAssignStep(bill.bill_id, step.step_no, bill.row_version)
  const signers = STEP_SIGNERS[step.role] ?? STEP_SIGNERS.dept_manager!
  const options = (people.data ?? [])
    .filter((p) => p.status === 'active' && signers.includes(p.role) && p.user_id !== bill.requester_user_id)
    .map((p) => ({ value: p.user_id, label: `${p.full_name}, ${p.title} (${p.user_id})` }))

  function close() {
    assign.reset()
    setUserId(null)
    onClose()
  }

  function confirm() {
    if (!userId) return
    assign.mutate(userId, {
      onSuccess: () => {
        notifications.show({
          title: 'Approver assigned',
          message: `${personName(userId, people.data)} signs step ${step.step_no} of ${bill.bill_id}.`,
        })
        close()
      },
    })
  }

  return (
    <Modal opened={opened} onClose={close} title="Assign approver">
      <Stack gap="sm">
        <Text size="sm">
          {`Step ${step.step_no} (${stepRoleLabel(step.role)}) of ${bill.bill_id} found nobody eligible to sign. ` +
            'The person you pick sees it in their approvals, and their limit is still checked when they sign.'}
        </Text>
        <Select
          label="Approver"
          required
          placeholder="Pick someone who may sign this step"
          data={options}
          value={userId}
          onChange={setUserId}
          searchable
          nothingFoundMessage="No one matches"
        />
        {assign.isError && <ErrorAlert error={assign.error} />}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={close}>Cancel</Button>
          <Button onClick={confirm} disabled={!userId} loading={assign.isPending}>Assign approver</Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/** One bill whose current step has no approver, with an Assign button for the roles that may assign. */
function StepRow({ bill, canAssign }: { bill: BillSummary; canAssign: boolean }) {
  const people = usePeople()
  const departments = useDepartments()
  const [open, setOpen] = useState(false)
  const step = bill.current_step!
  return (
    <Table.Tr>
      <Table.Td>
        <Anchor component={Link} to={`/bills/${bill.bill_id}`} underline="hover" fw={500}>
          <Id>{bill.bill_id}</Id>
        </Anchor>
      </Table.Td>
      <Table.Td>{bill.vendor_name ?? <Text span c="dimmed" size="sm">No vendor matched</Text>}</Table.Td>
      <Table.Td>
        {bill.department_id ? departmentLabel(bill.department_id, departments.data) : <Text span c="dimmed" size="sm">None</Text>}
      </Table.Td>
      <Table.Td data-numeric><MoneyText value={bill.total_cad} align="right" /></Table.Td>
      <Table.Td>{`Step ${step.step_no}, ${stepRoleLabel(step.role)}`}</Table.Td>
      <Table.Td>{bill.requester_user_id ? personName(bill.requester_user_id, people.data) : <Text span c="dimmed" size="sm">None</Text>}</Table.Td>
      {canAssign && (
        <Table.Td>
          <Button size="xs" onClick={() => setOpen(true)}>Assign</Button>
          <AssignModal bill={bill} opened={open} onClose={() => setOpen(false)} />
        </Table.Td>
      )}
    </Table.Tr>
  )
}

/**
 * /unassigned-steps: pending bills whose current approval step found nobody eligible to sign (for example, the only
 * approver is the requester or away with no delegate). The finance manager and the controller assign someone.
 */
export default function UnassignedStepsPage() {
  const user = useCurrentUser()
  const steps = useUnassignedSteps()
  const canAssign = ASSIGNER_ROLES.includes(user.role)
  const columns = [...COLUMNS, ...(canAssign ? ['Actions'] : [])]
  const bills = steps.data

  return (
    <Stack gap="md">
      <Title order={1}>Unassigned steps</Title>
      {steps.isError ? (
        <ErrorAlert error={steps.error} title="Can't load unassigned steps" onRetry={() => void steps.refetch()} />
      ) : (
        <>
          <Table.ScrollContainer minWidth={900}>
            <Table aria-label="Unassigned steps" bg="white" withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  {columns.map((column) => (
                    <Table.Th key={column} data-numeric={NUMERIC.has(column) || undefined}>{column}</Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {steps.isPending && Array.from({ length: SKELETON_ROWS }, (_, row) => (
                  <Table.Tr key={`skeleton-${row}`} aria-hidden>
                    {columns.map((column) => (
                      <Table.Td key={column}><Skeleton animate={false} height={12} radius="sm" /></Table.Td>
                    ))}
                  </Table.Tr>
                ))}
                {bills?.length === 0 && (
                  <Table.Tr>
                    <Table.Td colSpan={columns.length}>
                      <Text size="sm" c="dimmed" py="xs">No approval step is waiting for an approver.</Text>
                    </Table.Td>
                  </Table.Tr>
                )}
                {bills?.map((bill) => <StepRow key={bill.bill_id} bill={bill} canAssign={canAssign} />)}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {bills && bills.length > 0 && (
            <Text size="sm" c="dimmed">{`${bills.length} step${bills.length === 1 ? '' : 's'} need an approver`}</Text>
          )}
        </>
      )}
    </Stack>
  )
}
