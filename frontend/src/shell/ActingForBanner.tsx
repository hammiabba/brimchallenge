import { Alert, List, Text } from '@mantine/core'

import type { ActingFor } from '../api/types'
import { useCurrentUser } from '../auth/context'
import { formatDate } from '../lib/dates'

/** "from Nov 1, 2026 to Nov 30, 2026", or "from Nov 1, 2026, no end date" for an open-ended absence. */
function period(delegation: ActingFor): string {
  const start = `from ${formatDate(delegation.starts_on)}`
  return delegation.ends_on ? `${start} to ${formatDate(delegation.ends_on)}` : `${start}, no end date`
}

/**
 * Shown above every page while the signed-in user is the named delegate of someone who is away (GET /auth/me
 * `acting_for`, policy P08). Their approvals are recorded as on behalf of that person.
 */
export function ActingForBanner() {
  const user = useCurrentUser()
  const delegations = user.acting_for ?? []
  if (delegations.length === 0) return null

  return (
    <Alert color="blue" variant="light" title="You are acting as a delegate" mb="md">
      <Text size="sm">
        You may approve on behalf of the people below while they are away. Each decision is recorded as yours, on
        their behalf.
      </Text>
      <List size="sm" mt={4}>
        {delegations.map((d) => (
          <List.Item key={d.user_id}>
            {d.full_name} ({d.user_id}), {period(d)}
          </List.Item>
        ))}
      </List>
    </Alert>
  )
}
