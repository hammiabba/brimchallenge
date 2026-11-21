import { Alert, Button, Stack, Text } from '@mantine/core'

import { ApiError } from './errors'
import { errorTitle } from './notify'

interface ErrorAlertProps {
  error: unknown
  title?: string
  onRetry?: () => void
}

/**
 * An inline error box for a screen or form: the server's message, the request id in small text, and an optional
 * retry button. For transient feedback after an action, use notifyError instead.
 */
export function ErrorAlert({ error, title, onRetry }: ErrorAlertProps) {
  const apiError = error instanceof ApiError ? error : null
  return (
    <Alert color="red" variant="light" title={title ?? (apiError ? errorTitle(apiError) : 'Something went wrong')}>
      <Stack gap={6}>
        <Text size="sm">{apiError?.message ?? 'An unexpected error occurred.'}</Text>
        {apiError?.request_id && (
          <Text size="xs" c="dimmed">
            Request id: {apiError.request_id}
          </Text>
        )}
        {onRetry && (
          <Button size="xs" variant="default" onClick={onRetry} w="fit-content">
            Try again
          </Button>
        )}
      </Stack>
    </Alert>
  )
}
