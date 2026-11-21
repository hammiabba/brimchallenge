import { Box, Group, List, Stack, Text } from '@mantine/core'
import { IconUserShare } from '@tabler/icons-react'

import type { ActingFor } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { formatDate } from '../lib/dates'
import { Icon } from '../ui/Icon'

/** "from Nov 1, 2026 to Nov 30, 2026", or "from Nov 1, 2026, no end date" for an open-ended absence. */
function period(delegation: ActingFor): string {
  const start = `from ${formatDate(delegation.starts_on)}`
  return delegation.ends_on ? `${start} to ${formatDate(delegation.ends_on)}` : `${start}, no end date`
}

/**
 * Shown above every page while the signed-in user is the named delegate of someone who is away (GET /auth/me
 * `acting_for`, policy P08). A Sand highlight surface with ink text; their approvals are recorded as on behalf of
 * that person.
 */
export function ActingForBanner() {
  const user = useCurrentUser()
  const delegations = user.acting_for ?? []
  if (delegations.length === 0) return null

  return (
    <Box
      component="section"
      aria-label="Delegation"
      mb="lg"
      px="md"
      py="sm"
      bg="var(--app-sand)"
      c="var(--app-ink)"
      bd="1px solid var(--app-sand-border)"
      style={{ borderRadius: 4 }}
    >
      <Group gap="sm" align="flex-start" wrap="nowrap">
        <Box pt={2}>
          <Icon icon={IconUserShare} size={18} />
        </Box>
        <Stack gap={2}>
          <Text size="sm" fw={600}>
            You are acting as a delegate
          </Text>
          <Text size="sm">Approvals you sign for these people are recorded as yours, on their behalf.</Text>
          <List size="sm" mt={2}>
            {delegations.map((d) => (
              <List.Item key={d.user_id}>
                {d.full_name} ({d.user_id}), {period(d)}
              </List.Item>
            ))}
          </List>
        </Stack>
      </Group>
    </Box>
  )
}
