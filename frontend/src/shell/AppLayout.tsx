import { AppShell, Box, Burger, Button, Group, NavLink, ScrollArea, Stack, Text } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconLogout } from '@tabler/icons-react'
import { useState } from 'react'
import { Link, Outlet, matchPath, useLocation } from 'react-router'

import { notifyError } from '../api/notify'
// The Robin's Egg wordmark on a transparent background (177 x 59), as supplied; see DESIGN.md "Logo".
import brimLogo from '../assets/brand/brim_clear.png'
import { useDepartments } from '../api/reference'
import { useAuth, useCurrentUser } from '../auth/context'
import { titleRepeatsRole } from '../auth/roles'
import { APP_NAME } from '../config'
import { RoleBadge } from '../ui/Badges'
import { Icon } from '../ui/Icon'
import { ActingForBanner } from './ActingForBanner'
import { homePathFor, navItemsFor } from './navigation'

/**
 * The right side of the header: who is signed in (name; title and department name), their role, and sign out. The
 * role is shown once, as the badge.
 */
function UserSummary() {
  const user = useCurrentUser()
  const { logout } = useAuth()
  const departments = useDepartments()
  const [signingOut, setSigningOut] = useState(false)
  const departmentName =
    departments.data?.find((d) => d.department_id === user.department_id)?.name ?? user.department_id

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
        {/* "Title, department name": the department's name, not its code (the code until the list has loaded). A title
            that only repeats the role ("Finance Manager" next to the "Finance manager" badge) is left out, so the
            role shows once. */}
        <Text size="xs" c="dimmed" lh={1.3}>
          {titleRepeatsRole(user.title, user.role) ? '' : `${user.title}, `}
          {departmentName}
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
 * The logo's size in the header: 24 CSS px tall. The file is exactly 3:1, so it is 72 px wide (the width follows from
 * the file; nothing is stretched), and 59 file pixels over 24 CSS px keeps it sharp on 2x screens.
 */
const LOGO_HEIGHT = 24
const LOGO_WIDTH = 72
/**
 * The logo's clear space (DESIGN.md "Logo"): at least the height of the wordmark's letters. The "b" runs nearly the
 * full height of the file, about 23.6 px at this size, so the clear space is the logo's height, 24 px.
 */
const LOGO_CLEAR_SPACE = LOGO_HEIGHT
/** From the divider to the product name. The divider sits outside the logo's clear space. */
const DIVIDER_TO_NAME = 12

/**
 * The left of the header: the Brim logo, its clear space, a 1 px divider in the border colour, then the product name
 * in smaller secondary text; together one link to the signed-in user's home page. On phones (below the xs breakpoint)
 * the divider and the name are left out: beside the burger and the user summary there is room for the logo only.
 * The spacing is inline, in px, so the clear space is exact and a test can check it.
 */
function HeaderBrand() {
  const user = useCurrentUser()
  return (
    <Link to={homePathFor(user.role)} className="app-header-brand">
      <img src={brimLogo} alt="Brim" width={LOGO_WIDTH} height={LOGO_HEIGHT}
        style={{ display: 'block', height: LOGO_HEIGHT, width: 'auto' }} />
      <Box component="span" visibleFrom="xs" aria-hidden="true" data-testid="header-brand-divider" style={{
        display: 'block', flex: 'none', width: 1, height: LOGO_HEIGHT, backgroundColor: 'var(--app-border)',
        marginLeft: LOGO_CLEAR_SPACE, marginRight: DIVIDER_TO_NAME,
      }} />
      <Text span size="sm" c="dimmed" visibleFrom="xs">{APP_NAME}</Text>
    </Link>
  )
}

/**
 * The signed-in layout: a white header with the Robin's Egg top bar (logo and app name, user, role, sign out), the
 * role's sidebar (a burger menu on narrow screens), the delegate banner when it applies, and the current page on the
 * page background.
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
            <HeaderBrand />
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
