import { Button, Group, Modal, Select, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'

import { ErrorAlert } from '../../api/ErrorAlert'
import { useDepartments, useGlAccounts } from '../../api/reference'
import type { BillDetail, BillLine } from '../../api/types'
import { useCodeLine } from '../mutations'

interface CodingModalProps {
  bill: BillDetail
  line: BillLine
  opened: boolean
  onClose: () => void
}

/**
 * Change a line's coding: GL account and department, starting from the current coding (or the suggestion). Saving
 * the suggestion unchanged counts as accepting it; anything else as overriding it. Controls run again on save.
 */
export function CodingModal({ bill, line, opened, onClose }: CodingModalProps) {
  const accounts = useGlAccounts()
  const departments = useDepartments()
  const save = useCodeLine(bill, line.line_no)
  const startGl = line.gl_account ?? line.suggested_gl_account ?? null
  const startDepartment = line.department_id ?? line.suggested_department_id ?? bill.department_id ?? null
  const [gl, setGl] = useState<string | null>(startGl)
  const [department, setDepartment] = useState<string | null>(startDepartment)
  const [shownOpen, setShownOpen] = useState(opened)
  // The dialog stays mounted while the bill changes (so a save's confirmation and close still run once the new bill
  // arrives); its form starts again from the bill as it is now each time it opens. Adjusted during render, as React
  // recommends for state that follows a prop.
  if (opened !== shownOpen) {
    setShownOpen(opened)
    if (opened) {
      setGl(startGl)
      setDepartment(startDepartment)
    }
  }

  function close() {
    save.reset()
    setGl(startGl)
    setDepartment(startDepartment)
    onClose()
  }

  function confirm() {
    if (!gl || !department) return
    save.mutate({ gl_account: gl, department_id: department }, {
      onSuccess: () => {
        notifications.show({ title: 'Coding saved', message: `Line ${line.line_no} of ${bill.bill_id}` })
        close()
      },
    })
  }

  return (
    <Modal opened={opened} onClose={close} title={`Code line ${line.line_no}`}>
      <Stack gap="sm">
        <Text size="sm">{line.description}</Text>
        {line.suggestion_reason && <Text size="sm" c="dimmed">{`Suggested: ${line.suggestion_reason}`}</Text>}
        <Select
          label="GL account"
          required
          searchable
          nothingFoundMessage="No account matches"
          data={(accounts.data ?? []).map((a) => ({ value: a.account_number, label: `${a.account_number} ${a.name}` }))}
          value={gl}
          onChange={setGl}
          // Picking the selected option again keeps it; clearing a required field by accident left Save disabled.
          allowDeselect={false}
        />
        <Select
          label="Department"
          required
          data={(departments.data ?? []).map((d) => ({ value: d.department_id, label: `${d.name} (${d.department_id})` }))}
          value={department}
          onChange={setDepartment}
          allowDeselect={false}
        />
        {save.isError && <ErrorAlert error={save.error} />}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={close}>Cancel</Button>
          <Button onClick={confirm} disabled={!gl || !department} loading={save.isPending}>Save coding</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
