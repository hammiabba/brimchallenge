import { Anchor, Stack, Text, Title } from '@mantine/core'
import { Link, useLocation } from 'react-router'

/** Shown for any path that isn't a route, inside the signed-in layout. */
export function NotFoundPage() {
  const location = useLocation()
  return (
    <Stack maw={560} gap="sm">
      <Title order={2}>Page not found</Title>
      <Text size="sm">
        There is no page at <code>{location.pathname}</code>.
      </Text>
      <Anchor component={Link} to="/" size="sm">
        Go to your home page
      </Anchor>
    </Stack>
  )
}
