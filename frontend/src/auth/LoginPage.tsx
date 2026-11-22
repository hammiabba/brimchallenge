import { Button, Group, Loader, Select, Stack, Text, Title, UnstyledButton, rem } from '@mantine/core'
import { useMutation, useQuery } from '@tanstack/react-query'
import { IconLogin2, IconSearch } from '@tabler/icons-react'
import { useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router'

import { api, unwrap } from '../api/client'
import { ErrorAlert } from '../api/ErrorAlert'
import type { PickerUser } from '../api/types'
// The Robin's Egg wordmark on a transparent background: the logo file with the most contrast on Blumine (DESIGN.md).
import brimLogo from '../assets/brand/brim_clear.png'
import { APP_NAME, DEMO_PERSONAS } from '../config'
import { RoleBadge, StatusBadge } from '../ui/Badges'
import { Icon } from '../ui/Icon'
import { useAuth } from './context'
import { groupUsersByRole, makeUserFilter } from './pickerOptions'
import type { LoginRedirectState } from './RequireAuth'
import { ROLE_LABELS } from './roles'

/** The logo's display size: 88 x 29 CSS px, half the file's 177 x 59, so it stays sharp on 2x screens. */
const LOGO_WIDTH = 88
const LOGO_HEIGHT = 29

/** GET /auth/users: the people who may sign in (the server leaves out terminated users). */
function usePickerUsers() {
  return useQuery({
    queryKey: ['auth', 'users'],
    queryFn: () => unwrap(api.GET('/auth/users')),
    staleTime: 5 * 60_000,
  })
}

/** "Dispatcher, Operations": the title and the department's name, or its id when the name is missing. */
function titleAndDepartment(user: PickerUser): string {
  return `${user.title}, ${user.department_name ?? user.department_id}`
}

/** One option in the picker: name (with an "On leave" badge when it applies), then "title, department". */
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
        {titleAndDepartment(user)}
      </Text>
    </Stack>
  )
}

/**
 * The left panel: solid Blumine with the Brim logo, the app name in the serif title style and one line about the
 * app, centred as a group (app-signin-brand-main), and the demo note at the bottom. All text is white or the muted
 * panel colour (both pass 4.5:1 on Blumine).
 */
function BrandPanel() {
  return (
    <section className="app-signin-brand" aria-label={`About ${APP_NAME}`}>
      <Stack gap={32} justify="center" className="app-signin-brand-main">
        <img src={brimLogo} alt="Brim" width={LOGO_WIDTH} height={LOGO_HEIGHT} style={{ display: 'block' }} />
        <Stack gap="sm">
          <Text component="p" ff="var(--app-font-serif)" fz={rem(28)} fw={600} lh={1.25} c="white" m={0}>
            {APP_NAME}
          </Text>
          <Text c="white" maw={440}>
            Accounts payable for Harborline Logistics: invoices from inbox to payment, with approvals and a full audit
            trail.
          </Text>
        </Stack>
      </Stack>
      <Text size="sm" c="var(--app-on-primary-muted)">
        Demo environment. All data is synthetic and no real payments are made.
      </Text>
    </section>
  )
}

interface PersonaRowProps {
  person: PickerUser
  /** What this role comes to do, from DEMO_PERSONAS. */
  hint: string
  /** True while this person's sign-in is in flight. */
  pending: boolean
  /** True while any sign-in is in flight. */
  disabled: boolean
  onPick: (userId: string) => void
}

/**
 * One demo persona as a full-width button: the name (bold), what the role is for, then "title, department" in
 * smaller secondary text, with the role badge on the right. Clicking it (or Enter / Space on it) signs in as that
 * person straight away.
 */
function PersonaRow({ person, hint, pending, disabled, onPick }: PersonaRowProps) {
  return (
    <UnstyledButton
      className="app-persona"
      onClick={() => onPick(person.user_id)}
      disabled={disabled}
      aria-busy={pending || undefined}
      // The visible text, in reading order, after "Sign in as" (so the accessible name contains the visible label).
      aria-label={`Sign in as ${person.full_name}, ${hint}, ${titleAndDepartment(person)}, ${ROLE_LABELS[person.role]}`}
    >
      {/* Spans only: a button may hold phrasing content. */}
      <Stack component="span" gap={0} style={{ minWidth: 0 }}>
        <Text component="span" display="block" size="sm" fw={600}>{person.full_name}</Text>
        <Text component="span" display="block" size="sm" c="dimmed">{hint}</Text>
        <Text component="span" display="block" size="xs" c="dimmed">{titleAndDepartment(person)}</Text>
      </Stack>
      <Group component="span" gap="xs" wrap="nowrap">
        {pending && <Loader size="xs" component="span" />}
        <RoleBadge role={person.role} />
      </Group>
    </UnstyledButton>
  )
}

/**
 * The demo sign-in. Left: the brand panel. Right: one-click personas (one per role, from DEMO_PERSONAS; names,
 * titles and departments from GET /auth/users, and a persona that list doesn't include is skipped), then the
 * searchable picker for anyone else. Both sign in through login(user_id), POST /auth/login; there is no password,
 * the server sets the session cookie. After signing in the user goes back to the page they first asked for, or to
 * their role's home.
 */
export function LoginPage() {
  const { user, login } = useAuth()
  const location = useLocation()
  const users = usePickerUsers()
  const [selected, setSelected] = useState<string | null>(null)

  const from = (location.state as LoginRedirectState | null)?.from ?? '/'
  const byId = useMemo(() => new Map((users.data ?? []).map((u) => [u.user_id, u])), [users.data])
  const options = useMemo(() => groupUsersByRole(users.data ?? []), [users.data])
  // The picker's search matches department_id; give it the id and the name, so typing "Operations" finds the
  // people in that department as the placeholder promises.
  const filter = useMemo(() => makeUserFilter(new Map([...byId].map(([id, u]) => [
    id, { ...u, department_id: `${u.department_id} ${u.department_name ?? ''}` },
  ]))), [byId])
  // The personas that /auth/users includes, in DEMO_PERSONAS order, each with its hint; missing ones are skipped.
  const personas = useMemo(
    () => DEMO_PERSONAS.flatMap(({ userId, hint }) => {
      const person = byId.get(userId)
      return person ? [{ person, hint }] : []
    }),
    [byId],
  )

  const signIn = useMutation({ mutationFn: (userId: string) => login(userId) })

  // Leave the login page only once the auth context has the user (login() writes it into the cache). Navigating
  // from the mutation's onSuccess instead would run before AuthProvider re-renders: RequireAuth would still see
  // nobody signed in, bounce back to /login, and the shell would mount twice.
  if (user !== null) {
    return <Navigate to={from} replace />
  }

  const selectedUser = selected ? byId.get(selected) : undefined

  return (
    <div className="app-signin">
      <div className="app-signin-bar" aria-hidden />
      <div className="app-signin-columns">
        <BrandPanel />

        <main className="app-signin-main">
          <Stack w="100%" maw={460} gap="lg">
            <Title order={1}>Sign in</Title>

            {users.isPending && (
              <Group gap="xs">
                <Loader size="xs" />
                <Text size="sm">Loading people</Text>
              </Group>
            )}
            {users.isError && (
              <ErrorAlert error={users.error} title="Can't load the people list" onRetry={() => void users.refetch()} />
            )}

            {users.isSuccess && personas.length > 0 && (
              <Stack component="section" aria-labelledby="signin-personas" gap="xs">
                <Title order={2} id="signin-personas">Choose a role to try</Title>
                <Stack component="ul" gap="xs" m={0} p={0} style={{ listStyle: 'none' }}>
                  {personas.map(({ person, hint }) => (
                    <li key={person.user_id}>
                      <PersonaRow
                        person={person}
                        hint={hint}
                        pending={signIn.isPending && signIn.variables === person.user_id}
                        disabled={signIn.isPending}
                        onPick={(userId) => signIn.mutate(userId)}
                      />
                    </li>
                  ))}
                </Stack>
              </Stack>
            )}

            {users.isSuccess && (
              <Stack component="section" aria-labelledby="signin-picker" gap="xs">
                <Title order={2} id="signin-picker">Or sign in as someone else</Title>
                <form
                  onSubmit={(event) => {
                    event.preventDefault()
                    if (selected) signIn.mutate(selected)
                  }}
                >
                  <Stack gap="sm">
                    <Select
                      aria-label="Sign in as"
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
                    {selectedUser && (
                      <Text size="sm" c="dimmed">
                        {ROLE_LABELS[selectedUser.role]}: {titleAndDepartment(selectedUser)}
                      </Text>
                    )}
                    <Button
                      type="submit"
                      disabled={!selected || signIn.isPending}
                      loading={signIn.isPending && signIn.variables === selected}
                      leftSection={<Icon icon={IconLogin2} />}
                    >
                      Sign in
                    </Button>
                  </Stack>
                </form>
              </Stack>
            )}

            {signIn.isError && <ErrorAlert error={signIn.error} title="Sign-in failed" />}
          </Stack>
        </main>
      </div>
    </div>
  )
}
