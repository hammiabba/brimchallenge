import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { api, unwrap } from './api/client'
import { ROLES } from './auth/roles'
import { navItemsFor } from './shell/navigation'
import { DEPARTMENTS, PICKER_USERS, envelope, installFakeApi, makeMe } from './test/fakeApi'
import { renderApp } from './test/renderApp'

const SIGNED_OUT = { status: 401, body: envelope('auth.required', 'Sign in to continue.') }

/** The sign-in picker's input (the label also names its dropdown list, so query by role). */
function findPicker() {
  return screen.findByRole('combobox', { name: 'Sign in as' })
}

/** The labels of the sidebar links, in order. */
function sidebarLabels(): string[] {
  const nav = screen.getByRole('navigation', { name: 'Main' })
  return within(nav).getAllByRole('link').map((link) => link.textContent ?? '')
}

describe('signed out', () => {
  it('redirects to the login page and lists people grouped by role', async () => {
    installFakeApi({ 'GET /auth/me': SIGNED_OUT, 'GET /auth/users': { body: PICKER_USERS } })
    const user = userEvent.setup()
    renderApp('/bills')

    const picker = await findPicker()
    await user.click(picker)

    for (const group of ['Employee', 'AP clerk', 'Approver', 'Finance manager', 'Controller / admin', 'Auditor']) {
      expect(await screen.findByText(group)).toBeInTheDocument()
    }
    // Each option shows the name, then title, department and id; on-leave users are marked.
    expect(screen.getByText('Facilities Manager, D04 (U012)')).toBeInTheDocument()
    expect(screen.getByText('On leave')).toBeInTheDocument()
  })

  it('searches by title or department as well as name', async () => {
    installFakeApi({ 'GET /auth/me': SIGNED_OUT, 'GET /auth/users': { body: PICKER_USERS } })
    const user = userEvent.setup()
    renderApp('/')

    await user.type(await findPicker(), 'auditor')
    expect(await screen.findByRole('option', { name: /Kai Thompson/ })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Jordan Okafor/ })).not.toBeInTheDocument()
  })

  it('signs in and returns to the page first asked for, with that role\'s sidebar', async () => {
    const fake = installFakeApi({
      'GET /auth/me': SIGNED_OUT,
      'GET /auth/users': { body: PICKER_USERS },
      'POST /auth/login': { body: makeMe() },
      'GET /reference/departments': { body: DEPARTMENTS },
    })
    const user = userEvent.setup()
    renderApp('/bills')

    await user.click(await findPicker())
    await user.click(await screen.findByRole('option', { name: /Jordan Okafor/ }))
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'Bills' })).toBeInTheDocument()
    expect(sidebarLabels()).toEqual(navItemsFor('ap_clerk').map((item) => item.label))
    expect(screen.getByText('AP Specialist, Finance (D02)')).toBeInTheDocument()
    expect(fake.calls).toContain('POST /auth/login')
  })

  it('shows a refused sign-in on the form, with the request id', async () => {
    installFakeApi({
      'GET /auth/me': SIGNED_OUT,
      'GET /auth/users': { body: PICKER_USERS },
      'POST /auth/login': { status: 401, body: envelope('auth.invalid_user', "This account can't sign in.", 'rid-login-01') },
    })
    const user = userEvent.setup()
    renderApp('/')

    await user.click(await findPicker())
    await user.click(await screen.findByRole('option', { name: /Avery Chen/ }))
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText("This account can't sign in.")).toBeInTheDocument()
    expect(screen.getByText('Request id: rid-login-01')).toBeInTheDocument()
    expect(await findPicker()).toBeInTheDocument()
  })
})

describe('signed in', () => {
  it.each(ROLES)('shows the %s sidebar and lands on its first item', async (role) => {
    installFakeApi({ 'GET /auth/me': { body: makeMe({ role }) }, 'GET /reference/departments': { body: DEPARTMENTS } })
    renderApp('/')

    const items = navItemsFor(role)
    expect(await screen.findByRole('heading', { name: items[0]!.label })).toBeInTheDocument()
    expect(sidebarLabels()).toEqual(items.map((item) => item.label))
  })

  it('shows the delegate banner when /auth/me reports acting_for', async () => {
    installFakeApi({
      'GET /auth/me': { body: makeMe({
        user_id: 'U003', full_name: 'Priya Natarajan', role: 'finance_manager',
        acting_for: [{ user_id: 'U012', full_name: 'Sam Rivera', starts_on: '2026-10-20', ends_on: null }],
      }) },
    })
    renderApp('/')

    expect(await screen.findByText('You are acting as a delegate')).toBeInTheDocument()
    expect(screen.getByText('Sam Rivera (U012), from Oct 20, 2026, no end date')).toBeInTheDocument()
  })

  it('has no delegate banner otherwise', async () => {
    installFakeApi({ 'GET /auth/me': { body: makeMe() } })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Inbox' })
    expect(screen.queryByText('You are acting as a delegate')).not.toBeInTheDocument()
  })

  it('notes when a screen is not in the role\'s sidebar', async () => {
    installFakeApi({ 'GET /auth/me': { body: makeMe({ role: 'employee' }) } })
    renderApp('/audit')
    expect(await screen.findByRole('heading', { name: 'Audit log' })).toBeInTheDocument()
    expect(screen.getByText(/isn't in the Employee navigation/)).toBeInTheDocument()
  })

  it('shows a 404 page for an unknown path', async () => {
    installFakeApi({ 'GET /auth/me': { body: makeMe() } })
    renderApp('/no-such-page')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('returns to the login page when any call gets a 401', async () => {
    const fake = installFakeApi({ 'GET /auth/me': { body: makeMe() }, 'GET /auth/users': { body: PICKER_USERS } })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Inbox' })

    // The session expires: the next API call is refused.
    fake.routes['GET /bills'] = { status: 401, body: envelope('auth.invalid_session', 'Your session has expired.') }
    await act(async () => {
      await unwrap(api.GET('/bills')).catch(() => undefined)
    })

    expect(await findPicker()).toBeInTheDocument()
  })

  it('signs out', async () => {
    const fake = installFakeApi({
      'GET /auth/me': { body: makeMe() },
      'GET /auth/users': { body: PICKER_USERS },
      'POST /auth/logout': { status: 204 },
    })
    const user = userEvent.setup()
    renderApp('/')
    await screen.findByRole('heading', { name: 'Inbox' })

    await user.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(await findPicker()).toBeInTheDocument()
    await waitFor(() => expect(fake.calls).toContain('POST /auth/logout'))
  })
})
