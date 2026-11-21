import { Button, Center, Group, Loader, Paper, Select, Stack, Text, Title } from '@mantine/core'
import { useMutation, useQuery } from '@tanstack/react-query'
import { IconLogin2, IconSearch } from '@tabler/icons-react'
import { useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router'

import { api, unwrap } from '../api/client'
import { ErrorAlert } from '../api/ErrorAlert'
import type { PickerUser } from '../api/types'
import { APP_NAME } from '../config'
import { StatusBadge } from '../ui/Badges'
import { Icon } from '../ui/Icon'
import { useAuth } from './context'
import { groupUsersByRole, makeUserFilter } from './pickerOptions'
import type { LoginRedirectState } from './RequireAuth'
import { ROLE_LABELS } from './roles'

/** GET /auth/users: the people who may sign in (the server leaves out terminated users). */
function usePickerUsers() {
  return useQuery({
    queryKey: ['auth', 'users'],
    queryFn: () => unwrap(api.GET('/auth/users')),
    staleTime: 5 * 60_000,
  })
}

/** One option in the picker: name (with an "On leave" badge when it applies), then title, department and id. */
function UserOption({ user }: { user: PickerUser }) {
  return (
    <Stack gap={0}>
      <Group gap={6}>
        <Text size="sm" fw={500}>
          {user.full_name}
        </Text>
        {user.status === 'on_leave' && <StatusBadge kind="user" status="on_leave" />}
      </Group>
      <Text size="xs" c="dimmed">
        {user.title}, {user.department_id} ({user.user_id})
      </Text>
    </Stack>
  )
}

/**
 * The demo sign-in: pick a person from GET /auth/users (searchable, grouped by role) and sign in as them with
 * POST /auth/login. There is no password; the server sets the session cookie. After signing in the user goes back
 * to the page they first asked for, or to their role's home page.
 */
export function LoginPage() {
  const { user, login } = useAuth()
  const location = useLocation()
  const users = usePickerUsers()
  const [selected, setSelected] = useState<string | null>(null)

  const from = (location.state as LoginRedirectState | null)?.from ?? '/'
  const byId = useMemo(() => new Map((users.data ?? []).map((u) => [u.user_id, u])), [users.data])
  const options = useMemo(() => groupUsersByRole(users.data ?? []), [users.data])
  const filter = useMemo(() => makeUserFilter(byId), [byId])

  const signIn = useMutation({ mutationFn: (userId: string) => login(userId) })

  // Leave the login page only once the auth context has the user (login() writes it into the cache). Navigating
  // from the mutation's onSuccess instead would run before AuthProvider re-renders: RequireAuth would still see
  // nobody signed in, bounce back to /login, and the shell would mount twice.
  if (user !== null) {
    return <Navigate to={from} replace />
  }

  const selectedUser = selected ? byId.get(selected) : undefined

  return (
    <Center mih="100vh" bg="var(--app-page)" p="md">
      <Paper withBorder p="xl" w={420} maw="100%">
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (selected) signIn.mutate(selected)
          }}
        >
          <Stack gap="md">
            <Stack gap={4}>
              <Title order={1}>{APP_NAME}</Title>
              <Text size="sm" c="dimmed">
                Demo sign-in: choose the person to act as. The server decides what their role can see and do.
              </Text>
            </Stack>

            {users.isPending && (
              <Group gap="xs">
                <Loader size="xs" />
                <Text size="sm">Loading people</Text>
              </Group>
            )}
            {users.isError && (
              <ErrorAlert error={users.error} title="Can't load the people list" onRetry={() => void users.refetch()} />
            )}

            {users.isSuccess && (
              <Select
                label="Sign in as"
                placeholder="Search by name, title, department or role"
                leftSection={<Icon icon={IconSearch} />}
                data={options}
                value={selected}
                onChange={setSelected}
                searchable
                clearable
                filter={filter}
                nothingFoundMessage="Nobody matches"
                maxDropdownHeight={360}
                renderOption={({ option }) => {
                  const person = byId.get(option.value)
                  return person ? <UserOption user={person} /> : option.label
                }}
              />
            )}

            {selectedUser && (
              <Text size="sm" c="dimmed">
                {ROLE_LABELS[selectedUser.role]}: {selectedUser.title}, {selectedUser.department_id}
              </Text>
            )}

            {signIn.isError && <ErrorAlert error={signIn.error} title="Sign-in failed" />}

            <Button
              type="submit"
              disabled={!selected}
              loading={signIn.isPending}
              leftSection={<Icon icon={IconLogin2} />}
            >
              Sign in
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  )
}
