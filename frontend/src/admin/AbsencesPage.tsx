import { Button, Group, Modal, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { IconPlus } from '@tabler/icons-react'
import { notifications } from '@mantine/notifications'
import { useState } from 'react'

import { ErrorAlert } from '../api/ErrorAlert'
import { personName, usePeople } from '../api/reference'
import type { Absence, PickerUser, Role } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { DateText } from '../ui/DataText'
import { Icon } from '../ui/Icon'
import { ADMIN_WRITE_ROLES, useAbsences, useAddAbsence, useBusinessDate, useEndAbsence } from './queries'
import { TableShell } from './TableShell'

const COLUMNS = ['Who', 'Delegate', 'From', 'To'] as const
/** The actions column has no heading: its buttons say what they do ("End absence of Liam O'Connor"). */
const ACTIONS_COLUMN = ''

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

/** True when the absence covers the business date: started, and not over yet (ISO dates compare as text). */
function underWay(absence: Absence, today: string | undefined): boolean {
  return today !== undefined && absence.starts_on <= today && (absence.ends_on === null || absence.ends_on >= today)
}

/** Confirm ending an absence: the person is back and approves their own steps again. */
function EndAbsenceModal({ absence, onClose }: { absence: Absence; onClose: () => void }) {
  const people = usePeople()
  const end = useEndAbsence()
  const who = personName(absence.user_id, people.data)
  const delegate = personName(absence.delegate_user_id, people.data)

  function confirm() {
    end.mutate(absence.id, {
      onSuccess: () => {
        notifications.show({ title: 'Absence ended', message: `${who} approves their own steps again.` })
        onClose()
      },
    })
  }

  return (
    <Modal opened onClose={onClose} title="End absence">
      <Stack gap="sm">
        <Text size="sm">{`${who} is back: their approval steps go to them again, not to ${delegate}.`}</Text>
        {end.isError && <ErrorAlert error={end.error} />}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button onClick={confirm} loading={end.isPending}>End absence</Button>
        </Group>
      </Stack>
    </Modal>
  )
}

/**
 * /admin/absences: who is or will be away, and who signs in their place. The controller adds absences and ends the
 * ones under way; auditors read the list without those buttons (the server refuses them anyway).
 */
export default function AbsencesPage() {
  const absences = useAbsences()
  const people = usePeople()
  const today = useBusinessDate()
  const mayEdit = ADMIN_WRITE_ROLES.includes(useCurrentUser().role)
  const [adding, setAdding] = useState(false)
  const [ending, setEnding] = useState<Absence | null>(null)
  const rows = absences.data ?? []
  const columns = mayEdit ? [...COLUMNS, ACTIONS_COLUMN] : COLUMNS

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end">
        <Title order={1}>Absences</Title>
        {mayEdit && <Button leftSection={<Icon icon={IconPlus} />} onClick={() => setAdding(true)}>Add absence</Button>}
      </Group>
      {absences.isError ? (
        <ErrorAlert error={absences.error} title="Can't load absences" onRetry={() => void absences.refetch()} />
      ) : (
        <TableShell label="Absences" columns={columns} loading={absences.isPending} empty={rows.length === 0}
          emptyMessage="No absences recorded." minWidth={700}>
          {rows.map((absence) => (
            <Table.Tr key={absence.id}>
              <Table.Td>{personName(absence.user_id, people.data)}</Table.Td>
              <Table.Td>{personName(absence.delegate_user_id, people.data)}</Table.Td>
              <Table.Td><DateText value={absence.starts_on} /></Table.Td>
              <Table.Td>{absence.ends_on ? <DateText value={absence.ends_on} /> : <Text size="sm" c="dimmed">Open-ended</Text>}</Table.Td>
              {mayEdit && (
                <Table.Td>
                  {underWay(absence, today) && (
                    <Button size="xs" variant="default" onClick={() => setEnding(absence)}
                      aria-label={`End absence of ${personName(absence.user_id, people.data)}`}>
                      End absence
                    </Button>
                  )}
                </Table.Td>
              )}
            </Table.Tr>
          ))}
        </TableShell>
      )}
      {adding && <AddAbsenceModal onClose={() => setAdding(false)} />}
      {ending && <EndAbsenceModal absence={ending} onClose={() => setEnding(null)} />}
    </Stack>
  )
}
