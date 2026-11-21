import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import { App } from '../App'
import { createQueryClient } from '../api/queryClient'
import { AppProviders } from '../AppProviders'

/** Renders the whole app at `path` with a fresh QueryClient, as main.tsx does but with an in-memory router. */
export function renderApp(path = '/') {
  const queryClient = createQueryClient()
  const result = render(
    <MemoryRouter initialEntries={[path]}>
      <AppProviders queryClient={queryClient} env="test">
        <App />
      </AppProviders>
    </MemoryRouter>,
  )
  return { ...result, queryClient }
}
