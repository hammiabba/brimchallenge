import { Button, Group, Modal, Select, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'

import { ErrorAlert } from '../../api/ErrorAlert'
import { useDepartments } from '../../api/reference'
import type { BillDetail } from '../../api/types'
import { useEditBill } from '../mutations'

/**
 * Change the bill's department (it decides the department manager who approves). Saving records it as set by a
 * person and re-runs the controls, so the approval route follows.
 */
export function DepartmentModal({ bill, opened, onClose }: { bill: BillDetail; opened: boolean; onClose: () => void }) {
  const departments = useDepartments()
  const edit = useEditBill(bill)
  const [department, setDepartment] = useState<string | null>(bill.department_id ?? null)
  const [shownOpen, setShownOpen] = useState(opened)
  // The dialog stays mounted while the bill changes (so a save's confirmation and close still run once the new bill
  // arrives); its form starts again from the bill as it is now each time it opens. Adjusted during render, as React
  // recommends for state that follows a prop.
  if (opened !== shownOpen) {
    setShownOpen(opened)
    if (opened) setDepartment(bill.department_id ?? null)
  }

  function close() {
    edit.reset()
    setDepartment(bill.department_id ?? null)
    onClose()
  }

  function confirm() {
    if (!department) return
    edit.mutate({ department_id: department }, {
      onSuccess: () => {
        notifications.show({ title: 'Department saved', message: `${bill.bill_id}: controls ran again` })
        close()
      },
    })
  }

  return (
    <Modal opened={opened} onClose={close} title="Change department">
      <Stack gap="sm">
        <Text size="sm">The department's manager approves the bill. Saving runs the controls again.</Text>
        <Select
          label="Department"
          required
          data={(departments.data ?? []).map((d) => ({ value: d.department_id, label: `${d.name} (${d.department_id})` }))}
          value={department}
          onChange={setDepartment}
        />
        {edit.isError && <ErrorAlert error={edit.error} />}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={close}>Cancel</Button>
          <Button onClick={confirm} disabled={!department} loading={edit.isPending}>Save department</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
