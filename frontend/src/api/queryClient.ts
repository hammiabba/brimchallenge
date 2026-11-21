import { QueryClient } from '@tanstack/react-query'

import { ApiError } from './errors'

/**
 * Whether a failed query should be tried again: only when the server couldn't be reached or failed (status 0 or
 * 5xx), at most twice. A 4xx answer (401, 403, 404, 409, 422) won't change on a retry.
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status > 0 && error.status < 500) return false
  return failureCount < 2
}

/** A QueryClient with the app's defaults. One per app (main.tsx), and a fresh one per test. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  })
}
