import { MantineProvider } from '@mantine/core'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Role } from '../api/types'
import { AuthContext, type AuthState } from '../auth/context'
import { makeMe } from '../test/fakeApi'
import { cssVariablesResolver, theme } from '../theme'
import { NAV_ITEMS } from './navigation'
import { PlaceholderPage } from './PlaceholderPage'

/** Renders the placeholder for `item` signed in as `role`. Every screen is built now, so it's tested on its own. */
function renderPlaceholder(role: Role) {
  const auth: AuthState = {
    user: makeMe({ role }), isLoading: false, error: null, retry: () => {},
    login: () => Promise.reject(new Error('not used')), logout: () => Promise.resolve(),
  }
  render(
    <MantineProvider theme={theme} cssVariablesResolver={cssVariablesResolver} env="test">
      <AuthContext.Provider value={auth}>
        <PlaceholderPage item={NAV_ITEMS.payments} />
      </AuthContext.Provider>
    </MantineProvider>,
  )
}

describe('placeholder page', () => {
  it('shows the screen\'s title and its one line', () => {
    renderPlaceholder('ap_clerk')
    expect(screen.getByRole('heading', { name: 'Payments' })).toBeInTheDocument()
    expect(screen.getByText(NAV_ITEMS.payments.placeholder)).toBeInTheDocument()
    expect(screen.queryByText(/isn't in the/)).not.toBeInTheDocument()
  })

  it('notes when the screen is not in the role\'s sidebar', () => {
    renderPlaceholder('employee')
    expect(screen.getByText(/isn't in the Employee navigation/)).toBeInTheDocument()
  })
})
