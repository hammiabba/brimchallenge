import { Box, Button, Group, Stack, Text } from '@mantine/core'
import { IconAlertCircle } from '@tabler/icons-react'

import { ERROR_SURFACE } from '../theme'
import { Icon } from '../ui/Icon'
import { ApiError } from './errors'
import { errorTitle } from './notify'

interface ErrorAlertProps {
  error: unknown
  title?: string
  onRetry?: () => void
}

/**
 * An inline error box for a screen or form: a red title, the server's message in ink, the request id in small mono
 * text, and an optional retry button. For transient feedback after an action, use notifyError instead.
 */
export function ErrorAlert({ error, title, onRetry }: ErrorAlertProps) {
  const apiError = error instanceof ApiError ? error : null
  return (
    <Box
      role="alert"
      px="md"
      py="sm"
      bg={ERROR_SURFACE.background}
      bd={`1px solid ${ERROR_SURFACE.border}`}
      style={{ borderRadius: 4 }}
    >
      <Group gap="sm" align="flex-start" wrap="nowrap">
        <Text component="span" c={ERROR_SURFACE.title} pt={2}>
          <Icon icon={IconAlertCircle} size={18} />
        </Text>
        <Stack gap={4}>
          <Text size="sm" fw={600} c={ERROR_SURFACE.title}>
            {title ?? (apiError ? errorTitle(apiError) : 'Something went wrong')}
          </Text>
          <Text size="sm">{apiError?.message ?? 'An unexpected error occurred.'}</Text>
          {apiError?.request_id && (
            <Text size="xs" c="dimmed" ff="monospace">
              Request id: {apiError.request_id}
            </Text>
          )}
          {onRetry && (
            <Button size="xs" variant="default" onClick={onRetry} w="fit-content" mt={4}>
              Try again
            </Button>
          )}
        </Stack>
      </Group>
    </Box>
  )
}
