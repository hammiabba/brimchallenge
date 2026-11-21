import { AppShell, Badge, Burger, Button, Group, NavLink, ScrollArea, Stack, Text } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { useState } from 'react'
import { Link, Outlet, matchPath, useLocation } from 'react-router'

import { notifyError } from '../api/notify'
import { departmentLabel, useDepartments } from '../api/reference'
import { useAuth, useCurrentUser } from '../auth/context'
import { ROLE_LABELS } from '../auth/roles'
import { APP_NAME } from '../config'
import { ActingForBanner } from './ActingForBanner'
import { navItemsFor } from './navigation'

/** The right side of the header: who is signed in, their role, and the sign-out button. */
function UserSummary() {
  const user = useCurrentUser()
  const { logout } = useAuth()
  const departments = useDepartments()
  const [signingOut, setSigningOut] = useState(false)

  /** Signs out; RequireAuth then shows the login page. A failure is shown as a notification. */
  const signOut = async () => {
    setSigningOut(true)
    try {
      await logout()
    } catch (error) {
      notifyError(error, 'Sign-out failed')
      setSigningOut(false)
    }
  }

  return (
    <Group gap="sm" wrap="nowrap">
      <Stack gap={0} align="flex-end" visibleFrom="xs">
        <Text size="sm" fw={500} lh={1.2}>
          {user.full_name}
        </Text>
        <Text size="xs" c="dimmed" lh={1.2}>
          {user.title}, {departmentLabel(user.department_id, departments.data)}
        </Text>
      </Stack>
      <Badge>{ROLE_LABELS[user.role]}</Badge>
      <Button variant="default" size="xs" onClick={() => void signOut()} loading={signingOut}>
        Sign out
      </Button>
    </Group>
  )
}

/** The sidebar: the signed-in role's items from navigation.ts, with the current page highlighted. */
function Navigation({ onNavigate }: { onNavigate: () => void }) {
  const user = useCurrentUser()
  const location = useLocation()
  return (
    <nav aria-label="Main">
      {navItemsFor(user.role).map((item) => (
        <NavLink
          key={item.key}
          component={Link}
          to={item.path}
          label={item.label}
          active={matchPath({ path: item.path, end: false }, location.pathname) !== null}
          onClick={onNavigate}
        />
      ))}
    </nav>
  )
}

/**
 * The signed-in layout: header (app name, user, role, sign out), the role's sidebar (a burger menu on narrow
 * screens), the delegate banner when it applies, and the current page.
 */
export function AppLayout() {
  const [navOpen, { toggle, close }] = useDisclosure(false)

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !navOpen } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={navOpen} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Toggle navigation" />
            <Text component={Link} to="/" fw={600} size="lg">
              {APP_NAME}
            </Text>
          </Group>
          <UserSummary />
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        <ScrollArea>
          <Navigation onNavigate={close} />
        </ScrollArea>
      </AppShell.Navbar>

      <AppShell.Main bg="gray.0">
        <ActingForBanner />
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}
