import { ActionIcon, Group, Text, Tooltip } from '@mantine/core'
import { IconInfoCircle, IconUserShare } from '@tabler/icons-react'

import type { ActingFor } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { formatDate } from '../lib/dates'
import { Icon } from '../ui/Icon'

/** "since Oct 20, 2026" for an open-ended absence, "from Oct 20, 2026 to Nov 30, 2026" otherwise. */
function period(delegation: ActingFor): string {
  return delegation.ends_on
    ? `from ${formatDate(delegation.starts_on)} to ${formatDate(delegation.ends_on)}`
    : `since ${formatDate(delegation.starts_on)}`
}

/** "Liam O'Connor (U012) since Oct 20, 2026, Avery Chen (U013) from ...": everyone on one line. */
function delegationLine(delegations: readonly ActingFor[]): string {
  return delegations.map((d) => `${d.full_name} (${d.user_id}) ${period(d)}`).join(', ')
}

/**
 * One slim line above every page while the signed-in user is the named delegate of someone who is away
 * (GET /auth/me `acting_for`, policy P08), on the lighter Sand tint with ink text. The longer explanation is in a
 * tooltip on the info icon.
 */
export function ActingForBanner() {
  const user = useCurrentUser()
  const delegations = user.acting_for ?? []
  if (delegations.length === 0) return null

  return (
    <Group
      component="section"
      aria-label="Delegation"
      gap="xs"
      wrap="nowrap"
      mb="md"
      px="sm"
      py={4}
      bg="var(--app-sand-tint)"
      c="var(--app-ink)"
      bd="1px solid var(--app-sand-tint-border)"
      style={{ borderRadius: 4 }}
    >
      <Icon icon={IconUserShare} />
      <Text size="sm">{`Acting as delegate for ${delegationLine(delegations)}`}</Text>
      <Tooltip
        label="Approvals you sign for them are recorded as yours, on their behalf (policy P08)."
        multiline
        w={300}
      >
        <ActionIcon variant="subtle" size="sm" c="var(--app-ink)" aria-label="About acting as a delegate">
          <Icon icon={IconInfoCircle} />
        </ActionIcon>
      </Tooltip>
    </Group>
  )
}
