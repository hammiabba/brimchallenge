import { Button, Group, Modal, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { IconPlus } from '@tabler/icons-react'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'

import { ErrorAlert } from '../api/ErrorAlert'
import { personName, usePeople } from '../api/reference'
import type { PickerUser, Role } from '../api/types'
import { DateText } from '../ui/DataText'
import { Icon } from '../ui/Icon'
import { useAbsences, useAddAbsence } from './queries'
import { TableShell } from './TableShell'

const COLUMNS = ['Who', 'Delegate', 'From', 'To'] as const

/** The roles that approve bills, so need (and can be) a delegate. The server checks this too. */
const SIGNER_ROLES: readonly Role[] = ['approver', 'finance_manager', 'controller_admin']

/** Picker options for people in signer roles, optionally only active ones. */
function signerOptions(people: readonly PickerUser[] | undefined, activeOnly: boolean) {
  return (people ?? [])
    .filter((p) => SIGNER_ROLES.includes(p.role) && (!activeOnly || p.status === 'active'))
    .map((p) => ({ value: p.user_id, label: `${p.full_name} (${p.user_id})` }))
}

/** Record an absence for someone who approves bills, with who signs in their place. Controller only. */
function AddAbsenceModal({ onClose }: { onClose: () => void }) {
  const people = usePeople()
  const add = useAddAbsence()
  const [userId, setUserId] = useState<string | null>(null)
  const [delegateId, setDelegateId] = useState<string | null>(null)
  const [startsOn, setStartsOn] = useState('')
  const [endsOn, setEndsOn] = useState('')
  const valid = userId !== null && delegateId !== null && startsOn !== ''

  function save() {
    if (!userId || !delegateId) return
    add.mutate({ user_id: userId, delegate_user_id: delegateId, starts_on: startsOn, ends_on: endsOn || null }, {
      onSuccess: () => {
        notifications.show({ title: 'Absence recorded', message: `${personName(delegateId, people.data)} signs for ${personName(userId, people.data)}.` })
        onClose()
      },
    })
  }

  return (
    <Modal opened onClose={onClose} title="Add absence">
      <form onSubmit={(event) => { event.preventDefault(); save() }}>
        <Stack gap="sm">
          <Select label="Who is away" required data={signerOptions(people.data, false)} value={userId}
            onChange={setUserId} searchable />
          <Select label="Delegate" required description="An active approver, finance manager or controller"
            data={signerOptions(people.data, true).filter((o) => o.value !== userId)} value={delegateId}
            onChange={setDelegateId} searchable />
          <SimpleGrid cols={2} spacing="sm">
            <TextInput label="From" type="date" required value={startsOn} onChange={(e) => setStartsOn(e.currentTarget.value)} />
            <TextInput label="To" type="date" description="Leave empty if open-ended" value={endsOn}
              onChange={(e) => setEndsOn(e.currentTarget.value)} />
          </SimpleGrid>
          {add.isError && <ErrorAlert error={add.error} />}
          <Group justify="flex-end" gap="sm">
            <Button variant="default" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={!valid} loading={add.isPending}>Add absence</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  )
}

/** /admin/absences: who is or will be away, and who signs in their place. */
export default function AbsencesPage() {
  const absences = useAbsences()
  const people = usePeople()
  const [adding, setAdding] = useState(false)
  const rows = absences.data ?? []

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <Title order={1}>Absences</Title>
        <Button leftSection={<Icon icon={IconPlus} />} onClick={() => setAdding(true)}>Add absence</Button>
      </Group>
      {absences.isError ? (
        <ErrorAlert error={absences.error} title="Can't load absences" onRetry={() => void absences.refetch()} />
      ) : (
        <TableShell label="Absences" columns={COLUMNS} loading={absences.isPending} empty={rows.length === 0}
          emptyMessage="No absences recorded." minWidth={700}>
          {rows.map((absence) => (
            <Table.Tr key={absence.id}>
              <Table.Td>{personName(absence.user_id, people.data)}</Table.Td>
              <Table.Td>{personName(absence.delegate_user_id, people.data)}</Table.Td>
              <Table.Td><DateText value={absence.starts_on} /></Table.Td>
              <Table.Td>{absence.ends_on ? <DateText value={absence.ends_on} /> : <Text size="sm" c="dimmed">Open-ended</Text>}</Table.Td>
            </Table.Tr>
          ))}
        </TableShell>
      )}
      {adding && <AddAbsenceModal onClose={() => setAdding(false)} />}
    </Stack>
  )
}
