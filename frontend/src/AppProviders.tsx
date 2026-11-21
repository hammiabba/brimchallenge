import { MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { AuthProvider } from './auth/AuthProvider'
import { theme } from './theme'

/**
 * Everything the app runs inside except the router: the Mantine theme and notifications, TanStack Query, and auth.
 * main.tsx wraps it in a BrowserRouter; tests wrap it in a MemoryRouter with a fresh QueryClient and env="test"
 * (Mantine then skips transitions and portals, so dropdowns render in place at once).
 */
export function AppProviders({ queryClient, env = 'default', children }: {
  queryClient: QueryClient
  env?: 'default' | 'test'
  children: ReactNode
}) {
  return (
    <MantineProvider theme={theme} defaultColorScheme="light" env={env}>
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    </MantineProvider>
  )
}
