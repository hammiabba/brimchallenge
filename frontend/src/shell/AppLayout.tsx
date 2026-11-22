import { AppShell, Burger, Button, Group, NavLink, ScrollArea, Stack, Text } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconLogout } from '@tabler/icons-react'
import { useState } from 'react'
import { Link, Outlet, matchPath, useLocation } from 'react-router'

import { notifyError } from '../api/notify'
import { useDepartments } from '../api/reference'
import { useAuth, useCurrentUser } from '../auth/context'
import { APP_NAME } from '../config'
import { RoleBadge } from '../ui/Badges'
import { Icon } from '../ui/Icon'
import { ActingForBanner } from './ActingForBanner'
import { navItemsFor } from './navigation'

/** The right side of the header: who is signed in (name; title and department name), their role, and sign out. */
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
    <Group gap="md" wrap="nowrap">
      <Stack gap={0} align="flex-end" visibleFrom="xs">
        <Text size="sm" fw={500} lh={1.3}>
          {user.full_name}
        </Text>
        {/* "Title, department name": the department's name, not its code (the code until the list has loaded). */}
        <Text size="xs" c="dimmed" lh={1.3}>
          {user.title}, {departments.data?.find((d) => d.department_id === user.department_id)?.name ?? user.department_id}
        </Text>
      </Stack>
      <RoleBadge role={user.role} />
      <Button
        variant="default"
        size="xs"
        leftSection={<Icon icon={IconLogout} size={14} />}
        onClick={() => void signOut()}
        loading={signingOut}
      >
        Sign out
      </Button>
    </Group>
  )
}

/** The sidebar: the signed-in role's items from navigation.ts; the current page is marked (see global.css). */
function Navigation({ onNavigate }: { onNavigate: () => void }) {
  const user = useCurrentUser()
  const location = useLocation()
  return (
    <nav aria-label="Main">
      <Stack gap={2}>
        {navItemsFor(user.role).map((item) => {
          const active = matchPath({ path: item.path, end: false }, location.pathname) !== null
          return (
            <NavLink
              key={item.key}
              component={Link}
              to={item.path}
              label={item.label}
              leftSection={<Icon icon={item.icon} size={18} />}
              className="app-nav-link"
              active={active}
              aria-current={active ? 'page' : undefined}
              onClick={onNavigate}
            />
          )
        })}
      </Stack>
    </nav>
  )
}

/**
 * The signed-in layout: a white header with the Robin's Egg top bar (app name, user, role, sign out), the role's
 * sidebar (a burger menu on narrow screens), the delegate banner when it applies, and the current page on the page
 * background.
 */
export function AppLayout() {
  const [navOpen, { toggle, close }] = useDisclosure(false)

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 232, breakpoint: 'sm', collapsed: { mobile: !navOpen } }}
      padding="lg"
    >
      <AppShell.Header className="app-header">
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={navOpen} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Toggle navigation" />
            <Text component={Link} to="/" fw={600} size="lg" c="var(--app-ink)" td="none">
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

      <AppShell.Main bg="var(--app-page)">
        <ActingForBanner />
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}
