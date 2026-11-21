import { Alert, Badge, Code, Group, List, Paper, Stack, Text, Title } from '@mantine/core'

import { useCurrentUser } from '../auth/context'
import { ROLE_LABELS } from '../auth/roles'
import { isInNavigation, type NavItem } from './navigation'

/**
 * Stands in for a screen that isn't built yet: its name, what will be built there and the API behind it. When the
 * signed-in role doesn't have this screen in its sidebar, it says so; the server still decides what they may do.
 */
export function PlaceholderPage({ item }: { item: NavItem }) {
  const user = useCurrentUser()
  const inNav = isInNavigation(user.role, item.key)

  return (
    <Stack maw={760} gap="md">
      <Group gap="sm">
        <Title order={2}>{item.label}</Title>
        <Badge color="gray" variant="outline">
          Not built yet
        </Badge>
      </Group>

      {!inNav && (
        <Alert color="gray" variant="light">
          This screen isn't in the {ROLE_LABELS[user.role]} navigation. When it is built, the server decides what you
          can see and do here.
        </Alert>
      )}

      <Paper withBorder p="md">
        <Stack gap="sm">
          <Text fw={600} size="sm">
            What will be built here
          </Text>
          <Text size="sm">{item.description}</Text>
          <Text fw={600} size="sm" mt="xs">
            API
          </Text>
          <List size="sm" spacing={2}>
            {item.endpoints.map((endpoint) => (
              <List.Item key={endpoint}>
                <Code>{endpoint}</Code>
              </List.Item>
            ))}
          </List>
        </Stack>
      </Paper>
    </Stack>
  )
}
