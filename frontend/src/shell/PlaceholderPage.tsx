import { Group, Stack, Text, Title } from '@mantine/core'
import { IconInfoCircle } from '@tabler/icons-react'

import { useCurrentUser } from '../auth/context'
import { ROLE_LABELS } from '../auth/roles'
import { Icon } from '../ui/Icon'
import { isInNavigation, type NavItem } from './navigation'

/**
 * Stands in for a screen that isn't built yet: its title and one line saying what is missing and what comes next.
 * When the signed-in role doesn't have this screen in its sidebar, a second line says so; the server still decides
 * what they may do.
 */
export function PlaceholderPage({ item }: { item: NavItem }) {
  const user = useCurrentUser()
  const inNav = isInNavigation(user.role, item.key)

  return (
    <Stack maw={720} gap="sm">
      <Title order={1}>{item.label}</Title>
      <Text>{item.placeholder}</Text>
      {!inNav && (
        <Group gap={6} wrap="nowrap" align="flex-start">
          <Text c="dimmed" component="span" mt={2}>
            <Icon icon={IconInfoCircle} />
          </Text>
          <Text size="sm" c="dimmed">
            This screen isn't in the {ROLE_LABELS[user.role]} navigation. When it is built, the server decides what you
            can see and do here.
          </Text>
        </Group>
      )}
    </Stack>
  )
}
