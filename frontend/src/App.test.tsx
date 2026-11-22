import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { api, unwrap } from './api/client'
import { ROLES } from './auth/roles'
import { APP_NAME } from './config'
import { homePathFor, navItemsFor } from './shell/navigation'
import { DEPARTMENTS, PICKER_USERS, envelope, installFakeApi, makeMe, type FakeReply } from './test/fakeApi'
import { renderApp } from './test/renderApp'

/** What GET /auth/me?optional=true answers when nobody is signed in: 204, no body (not a 401). */
const SIGNED_OUT = { status: 204 }

/** A fake reply that arrives after `ms` milliseconds, like a slow server, so tests can't rely on timing. */
function later(reply: FakeReply, ms = 40): Promise<FakeReply> {
  return new Promise((resolve) => setTimeout(() => resolve(reply), ms))
}

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
  it('asks for the session with optional=true, so a signed-out visit is not a failed request', async () => {
    const fake = installFakeApi({ 'GET /auth/me': SIGNED_OUT, 'GET /auth/users': { body: PICKER_USERS } })
    renderApp('/')
    expect(await findPicker()).toBeInTheDocument()
    const me = fake.urls.filter((url) => url.pathname.endsWith('/auth/me'))
    expect(me.length).toBeGreaterThan(0)
    expect(me.every((url) => url.searchParams.get('optional') === 'true')).toBe(true)
  })

  it('still treats a 401 from /auth/me as signed out', async () => {
    installFakeApi({
      'GET /auth/me': { status: 401, body: envelope('auth.required', 'Sign in to continue.') },
      'GET /auth/users': { body: PICKER_USERS },
    })
    renderApp('/bills')
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
  })

  it('redirects to the login page and lists people grouped by role', async () => {
    installFakeApi({ 'GET /auth/me': SIGNED_OUT, 'GET /auth/users': { body: PICKER_USERS } })
    const user = userEvent.setup()
    renderApp('/bills')

    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
    const picker = await findPicker()
    await user.click(picker)

    // The group labels are inside the picker's list (the persona rows above also show role badges).
    const list = await screen.findByRole('listbox')
    for (const group of ['Employee', 'AP clerk', 'Approver', 'Finance manager', 'Controller / admin', 'Auditor']) {
      expect(await within(list).findByText(group)).toBeInTheDocument()
    }
    // Each option shows the name, then "title, department" (the id here: these test users have no department name);
    // on-leave users are marked.
    expect(within(list).getByText('Facilities Manager, D04')).toBeInTheDocument()
    expect(within(list).getByText('On leave')).toBeInTheDocument()
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
    // What happens after "Sign in", in order: POST /auth/login answers with the user (no /auth/me refetch: the
    // response is written straight into the cache), the router goes back to /bills inside the shell, and only then
    // do the header and the bills page ask for their data (GET /reference/departments for the department name, once
    // for both). Each step is awaited on its own signal. The login and departments answers are deliberately late, as
    // on a loaded machine: the header first shows the bare department id, so a check that doesn't wait for the
    // department name fails here every time.
    const fake = installFakeApi({
      'GET /auth/me': SIGNED_OUT,
      'GET /auth/users': { body: PICKER_USERS },
      'POST /auth/login': () => later({ body: makeMe() }),
      'GET /reference/departments': () => later({ body: DEPARTMENTS }),
    })
    const user = userEvent.setup()
    renderApp('/bills')

    // 1. The picker appears once /auth/me (signed out) and /auth/users have answered.
    await user.click(await findPicker())
    await user.click(await screen.findByRole('option', { name: /Jordan Okafor/ }))
    // 2. The choice is applied before submitting.
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Sign in as' })).toHaveValue('Jordan Okafor'))
    const signIn = screen.getByRole('button', { name: 'Sign in' })
    expect(signIn).toBeEnabled()
    await user.click(signIn)

    // 3. The login request goes out.
    await waitFor(() => expect(fake.calls).toContain('POST /auth/login'))
    // 4. Its answer signs the user in and the route changes back to the page first asked for.
    expect(await screen.findByRole('heading', { name: 'Bills' })).toBeInTheDocument()
    expect(sidebarLabels()).toEqual(navItemsFor('ap_clerk').map((item) => item.label))
    // 5. The header shows the department name once /reference/departments answers.
    expect(await screen.findByText('AP Specialist, Finance')).toBeInTheDocument()
    expect(fake.calls.filter((call) => call.includes('/auth/'))).toEqual(['GET /auth/me', 'GET /auth/users', 'POST /auth/login'])
    expect(fake.calls.filter((call) => call === 'GET /reference/departments')).toHaveLength(1)
    expect(fake.calls.indexOf('GET /reference/departments')).toBeGreaterThan(fake.calls.indexOf('POST /auth/login'))
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

  it('shows the Brim logo and the product name in the header, as one link to the home page', async () => {
    installFakeApi({ 'GET /auth/me': { body: makeMe({ role: 'approver' }) }, 'GET /reference/departments': { body: DEPARTMENTS } })
    renderApp('/bills')
    const header = await screen.findByRole('banner')
    const logo = within(header).getByRole('img', { name: 'Brim' })
    // 24 px tall, width from the file (3:1), never stretched.
    expect(logo).toHaveAttribute('height', '24')
    expect(logo).toHaveStyle({ height: '24px', width: 'auto' })
    const name = within(header).getByText(APP_NAME)
    expect(name.tagName).toBe('SPAN') // real text, not part of the image
    const link = logo.closest('a')!
    expect(link).toBe(name.closest('a'))
    expect(link).toHaveAttribute('href', homePathFor('approver'))
    expect(link).toHaveAccessibleName(`Brim ${APP_NAME}`)
    // Between the logo and the name: the logo's clear space (24 px, DESIGN.md "Logo"), then a 1 px divider in the
    // border colour, hidden from screen readers. In document order: logo, divider, name.
    const divider = within(header).getByTestId('header-brand-divider')
    expect(divider).toHaveAttribute('aria-hidden', 'true')
    // Read from the inline style: jsdom's computed style drops CSS variables.
    const { marginLeft, width, height, backgroundColor } = divider.style
    expect({ marginLeft, width, height, backgroundColor }).toEqual(
      { marginLeft: '24px', width: '1px', height: '24px', backgroundColor: 'var(--app-border)' })
    expect(logo.compareDocumentPosition(divider) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(divider.compareDocumentPosition(name) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows the role once in the header: a title that repeats it is left out', async () => {
    installFakeApi({
      'GET /auth/me': { body: makeMe({ title: 'Finance Manager', role: 'finance_manager' }) },
      'GET /reference/departments': { body: DEPARTMENTS },
    })
    renderApp('/')
    const header = await screen.findByRole('banner')
    expect(await within(header).findByText('Finance')).toBeInTheDocument()
    expect(within(header).queryByText(/Finance Manager/)).not.toBeInTheDocument()
    expect(within(header).getByText('Finance manager')).toBeInTheDocument()
  })

  it('keeps a title that says something the role badge does not', async () => {
    installFakeApi({
      'GET /auth/me': { body: makeMe({ title: 'Operations Manager', role: 'approver', department_id: 'D01' }) },
      'GET /reference/departments': { body: DEPARTMENTS },
    })
    renderApp('/')
    const header = await screen.findByRole('banner')
    expect(await within(header).findByText('Operations Manager, Operations')).toBeInTheDocument()
    expect(within(header).getByText('Approver')).toBeInTheDocument()
  })

  it('shows the delegate banner when /auth/me reports acting_for', async () => {
    installFakeApi({
      'GET /auth/me': { body: makeMe({
        user_id: 'U003', full_name: 'Priya Natarajan', role: 'finance_manager',
        acting_for: [{ user_id: 'U012', full_name: 'Sam Rivera', starts_on: '2026-10-20', ends_on: null }],
      }) },
    })
    renderApp('/')

    expect(await screen.findByText('Acting as delegate for Sam Rivera (U012) since Oct 20, 2026')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'About acting as a delegate' })).toBeInTheDocument()
  })

  it('lists several delegations on the same line', async () => {
    installFakeApi({
      'GET /auth/me': { body: makeMe({
        user_id: 'U003', full_name: 'Priya Natarajan', role: 'finance_manager',
        acting_for: [
          { user_id: 'U012', full_name: 'Sam Rivera', starts_on: '2026-10-20', ends_on: null },
          { user_id: 'U001', full_name: 'Morgan Lee', starts_on: '2026-11-01', ends_on: '2026-11-15' },
        ],
      }) },
    })
    renderApp('/')

    expect(await screen.findByText('Acting as delegate for Sam Rivera (U012) since Oct 20, 2026, '
      + 'Morgan Lee (U001) from Nov 1, 2026 to Nov 15, 2026')).toBeInTheDocument()
  })

  it('has no delegate banner otherwise', async () => {
    installFakeApi({ 'GET /auth/me': { body: makeMe() } })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Inbox' })
    expect(screen.queryByRole('region', { name: 'Delegation' })).not.toBeInTheDocument()
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
