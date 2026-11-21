/**
 * Error notifications. notifyError(error) shows the server's message, with the request id in small text so a user
 * can quote it when reporting a problem (the same id is in the server log and the audit event).
 */
import { Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'

import { ApiError } from './errors'

/** A short title for the kind of failure, chosen from the status (and code for conflicts). */
export function errorTitle(error: ApiError): string {
  if (error.status === 0) return 'Server unreachable'
  if (error.status === 401) return 'Signed out'
  if (error.status === 403) return 'Not allowed'
  if (error.status === 404) return 'Not found'
  if (error.status === 409) return error.code === 'conflict.stale' ? 'Changed by someone else' : 'Not possible right now'
  if (error.status === 422) return 'Check the highlighted fields'
  if (error.status === 501) return 'Not available yet'
  return 'Something went wrong'
}

/**
 * Shows `error` as a notification: white, with a thin red bar on its left edge (Mantine's `color`), the title and
 * message in ink and the request id in small mono text. It floats, so it carries the theme's one shadow.
 * Non-ApiError values get a generic message and are logged to the console.
 */
export function notifyError(error: unknown, title?: string): void {
  if (!(error instanceof ApiError)) {
    console.error(error)
  }
  const apiError = error instanceof ApiError ? error : null
  notifications.show({
    color: 'red',
    title: title ?? (apiError ? errorTitle(apiError) : 'Something went wrong'),
    message: (
      <Stack gap={2}>
        <Text size="sm" c="var(--app-ink)">{apiError?.message ?? 'An unexpected error occurred.'}</Text>
        {apiError?.request_id && (
          <Text size="xs" c="dimmed" ff="monospace">
            Request id: {apiError.request_id}
          </Text>
        )}
      </Stack>
    ),
    autoClose: 10_000,
  })
}
