import { Button, Group, List, Select, SimpleGrid, Stack, Text, TextInput, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, unwrap } from '../api/client'
import { ErrorAlert } from '../api/ErrorAlert'
import { personName, usePeople } from '../api/reference'
import type { DelegationInput, Role } from '../api/types'
import { ME_QUERY_KEY, useCurrentUser } from '../auth/context'
import { formatDate } from '../lib/dates'
import { DateText } from '../ui/DataText'

/** The roles that may sign for someone else. The server checks this too. */
const SIGNER_ROLES: readonly Role[] = ['approver', 'finance_manager', 'controller_admin']

/** The people you are signing for right now, from /auth/me. */
function ActingFor() {
  const user = useCurrentUser()
  const acting = user.acting_for ?? []
  if (acting.length === 0) return <Text size="sm" c="dimmed">You are not signing for anyone right now.</Text>
  return (
    <List size="sm" spacing={4}>
      {acting.map((a) => (
        <List.Item key={a.user_id}>
          {`${a.full_name}, from `}<DateText value={a.starts_on} />
          {a.ends_on ? <>{' to '}<DateText value={a.ends_on} /></> : ' until further notice'}
        </List.Item>
      ))}
    </List>
  )
}

/**
 * /out-of-office: name who approves for you while you are away (PUT /me/delegation). While it is active, your
 * delegate sees your approvals with a banner, and their decisions are recorded as on your behalf.
 */
export default function DelegationPage() {
  const user = useCurrentUser()
  const people = usePeople()
  const queryClient = useQueryClient()
  const [delegateId, setDelegateId] = useState<string | null>(null)
  const [startsOn, setStartsOn] = useState('')
  const [endsOn, setEndsOn] = useState('')
  const save = useMutation({
    mutationFn: (body: DelegationInput) => unwrap(api.PUT('/me/delegation', { body })),
    onSuccess: (me) => {
      queryClient.setQueryData(ME_QUERY_KEY, me)
      return queryClient.invalidateQueries({ queryKey: ['auth', 'users'] })
    },
  })

  const options = (people.data ?? [])
    .filter((p) => p.user_id !== user.user_id && p.status === 'active' && SIGNER_ROLES.includes(p.role))
    .map((p) => ({ value: p.user_id, label: `${p.full_name}, ${p.title} (${p.user_id})` }))
  const valid = delegateId !== null && startsOn !== '' && (endsOn === '' || endsOn >= startsOn)

  function submit() {
    if (!delegateId) return
    save.mutate({ delegate_user_id: delegateId, starts_on: startsOn, ends_on: endsOn || null }, {
      onSuccess: () => {
        notifications.show({
          title: 'Out of office saved',
          message: `${personName(delegateId, people.data)} approves for you from ${formatDate(startsOn)}${endsOn ? ` to ${formatDate(endsOn)}` : ''}.`,
        })
        setDelegateId(null)
        setStartsOn('')
        setEndsOn('')
      },
    })
  }

  // Only the roles that approve have approvals to hand over (PUT /me/delegation: approver, finance, controller).
  if (!SIGNER_ROLES.includes(user.role)) {
    return (
      <Stack gap="lg" maw={720}>
        <Title order={1}>Out of office</Title>
        <Text size="sm">Out of office is for approvers, finance managers and the controller: your role has no approvals to hand over.</Text>
      </Stack>
    )
  }

  return (
    <Stack gap="lg" maw={720}>
      <Title order={1}>Out of office</Title>
      <form onSubmit={(event) => { event.preventDefault(); submit() }}>
        <Stack gap="sm">
          <Title order={2}>Name a delegate</Title>
          <Text size="sm">
            Your delegate approves bills for you during these dates. Their decisions are recorded as on your behalf.
          </Text>
          <Select label="Delegate" required placeholder="Pick an approver, finance manager or controller" data={options}
            value={delegateId} onChange={setDelegateId} searchable nothingFoundMessage="No one matches" />
          {/* Both date inputs sit on one line: the "To" hint goes under its input, not between label and input. */}
          <SimpleGrid cols={2} spacing="sm">
            <TextInput label="From" type="date" required value={startsOn} onChange={(e) => setStartsOn(e.currentTarget.value)} />
            <TextInput label="To" type="date" description="Leave empty if you don't know yet" value={endsOn}
              inputWrapperOrder={['label', 'input', 'description', 'error']}
              error={endsOn !== '' && startsOn !== '' && endsOn < startsOn ? 'The end date is before the start date' : undefined}
              onChange={(e) => setEndsOn(e.currentTarget.value)} />
          </SimpleGrid>
          {save.isError && <ErrorAlert error={save.error} />}
          <Group>
            <Button type="submit" disabled={!valid} loading={save.isPending}>Save out of office</Button>
          </Group>
        </Stack>
      </form>
      <Stack gap="sm">
        <Title order={2}>Signing for others</Title>
        <ActingFor />
      </Stack>
    </Stack>
  )
}
