import { Anchor, Group, Stack, Text, Title } from '@mantine/core'
import { IconArrowLeft } from '@tabler/icons-react'
import { Link, useLocation } from 'react-router'

import { Icon } from '../ui/Icon'
import { Id } from '../ui/DataText'

/** Shown for any path that isn't a route, inside the signed-in layout. */
export function NotFoundPage() {
  const location = useLocation()
  return (
    <Stack maw={720} gap="sm">
      <Title order={1}>Page not found</Title>
      <Text>
        There is no page at <Id>{location.pathname}</Id>.
      </Text>
      <Anchor component={Link} to="/" size="sm" w="fit-content">
        <Group gap={6} component="span">
          <Icon icon={IconArrowLeft} size={14} />
          Go to your home page
        </Group>
      </Anchor>
    </Stack>
  )
}
