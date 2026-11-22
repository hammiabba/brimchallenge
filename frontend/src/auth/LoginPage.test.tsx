import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { PickerUser } from '../api/types'
import { APP_NAME, DEMO_PERSONAS } from '../config'
import { navItemsFor } from '../shell/navigation'
import { DEPARTMENTS, envelope, installFakeApi, makeMe } from '../test/fakeApi'
import { renderApp } from '../test/renderApp'
import { ROLE_LABELS } from './roles'

const SIGNED_OUT = { status: 401, body: envelope('auth.required', 'Sign in to continue.') }

/** One person per demo persona id (in DEMO_PERSONAS order), plus someone who isn't a persona. */
const USERS: PickerUser[] = [
  { user_id: 'U013', full_name: 'Avery Chen', title: 'Operations Analyst', role: 'employee', department_id: 'D01', status: 'active' },
  { user_id: 'U004', full_name: 'Nadia Haddad', title: 'AP Clerk', role: 'ap_clerk', department_id: 'D02', status: 'active' },
  { user_id: 'U007', full_name: 'Dev Malhotra', title: 'Operations Manager', role: 'approver', department_id: 'D01', status: 'active' },
  { user_id: 'U003', full_name: 'Priya Natarajan', title: 'Finance Manager', role: 'finance_manager', department_id: 'D02', status: 'active' },
  { user_id: 'U001', full_name: 'Morgan Lee', title: 'Chief Financial Officer', role: 'controller_admin', department_id: 'D08', status: 'active' },
  { user_id: 'U006', full_name: 'Kai Thompson', title: 'Audit Lead', role: 'auditor', department_id: 'D04', status: 'active' },
  { user_id: 'U020', full_name: 'Robin Okoye', title: 'Fleet Coordinator', role: 'employee', department_id: 'D03', status: 'active' },
]

/** The fake API for the sign-in page; POST /auth/login answers as whoever was asked for and records the ids. */
function installSignIn(users: PickerUser[] = USERS) {
  const loginIds: string[] = []
  const fake = installFakeApi({
    'GET /auth/me': SIGNED_OUT,
    'GET /auth/users': { body: users },
    'GET /reference/departments': { body: DEPARTMENTS },
    'POST /auth/login': async (request) => {
      const { user_id: userId } = (await request.clone().json()) as { user_id: string }
      loginIds.push(userId)
      const person = users.find((u) => u.user_id === userId)!
      return { body: makeMe({ ...person, acting_for: [] }) }
    },
  })
  return { ...fake, loginIds }
}

/** The persona list's rows (buttons), in order. */
async function personaRows(): Promise<HTMLElement[]> {
  const section = await screen.findByRole('region', { name: 'Choose a role to try' })
  return within(section).getAllByRole('button')
}

describe('sign-in page', () => {
  it('shows the brand panel with the Brim logo, the app name and the demo note', async () => {
    installSignIn()
    renderApp('/')

    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
    const brand = screen.getByRole('region', { name: `About ${APP_NAME}` })
    expect(within(brand).getByRole('img', { name: 'Brim' })).toBeInTheDocument()
    expect(within(brand).getByText(APP_NAME)).toBeInTheDocument()
    expect(within(brand).getByText(/Accounts payable for Harborline Logistics/)).toBeInTheDocument()
    expect(within(brand).getByText('Demo environment. All data is synthetic and no real payments are made.'))
      .toBeInTheDocument()
    for (const image of screen.getAllByRole('img')) expect(image).toHaveAccessibleName()
  })

  it('lists one persona per role, in role order, with name, title and department from /auth/users', async () => {
    installSignIn()
    renderApp('/')

    const rows = await personaRows()
    expect(rows).toHaveLength(DEMO_PERSONAS.length)
    expect(rows.map((row) => within(row).getByText(/^(Employee|AP clerk|Approver|Finance manager|Controller \/ admin|Auditor)$/).textContent))
      .toEqual(['Employee', 'AP clerk', 'Approver', 'Finance manager', 'Controller / admin', 'Auditor'])
    expect(rows[0]).toHaveAccessibleName('Sign in as Avery Chen, Operations Analyst, D01, Employee')
    expect(within(rows[4]!).getByText('Chief Financial Officer, D08')).toBeInTheDocument()
    // Someone who isn't a persona is only in the picker.
    expect(screen.queryByRole('button', { name: /Robin Okoye/ })).not.toBeInTheDocument()
  })

  it.each(DEMO_PERSONAS)('signs in as persona %s and lands on that role\'s first page', async (userId) => {
    const fake = installSignIn()
    const user = userEvent.setup()
    renderApp('/')
    const person = USERS.find((u) => u.user_id === userId)!

    await user.click(await screen.findByRole('button', { name: new RegExp(`Sign in as ${person.full_name}`) }))

    await waitFor(() => expect(fake.loginIds).toEqual([userId]))
    expect(await screen.findByRole('heading', { level: 1, name: navItemsFor(person.role)[0]!.label })).toBeInTheDocument()
    expect(screen.getByText(ROLE_LABELS[person.role], { selector: '.mantine-Badge-label' })).toBeInTheDocument()
  })

  it('returns to the page first asked for after a persona sign-in', async () => {
    installSignIn()
    const user = userEvent.setup()
    renderApp('/bills')

    await user.click(await screen.findByRole('button', { name: /Sign in as Nadia Haddad/ }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Bills' })).toBeInTheDocument()
  })

  it('skips a persona that /auth/users does not include', async () => {
    installSignIn(USERS.filter((u) => u.user_id !== 'U007'))
    renderApp('/')

    const rows = await personaRows()
    expect(rows).toHaveLength(DEMO_PERSONAS.length - 1)
    expect(screen.queryByRole('button', { name: /Dev Malhotra/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('still signs in anyone through the search picker', async () => {
    const fake = installSignIn()
    const user = userEvent.setup()
    renderApp('/')

    await user.type(await screen.findByRole('combobox', { name: 'Sign in as' }), 'fleet')
    await user.click(await screen.findByRole('option', { name: /Robin Okoye/ }))
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(fake.loginIds).toEqual(['U020']))
    expect(await screen.findByRole('heading', { level: 1, name: navItemsFor('employee')[0]!.label })).toBeInTheDocument()
  })

  it('shows a refused persona sign-in with the request id, and stays on the page', async () => {
    installFakeApi({
      'GET /auth/me': SIGNED_OUT,
      'GET /auth/users': { body: USERS },
      'POST /auth/login': { status: 401, body: envelope('auth.invalid_user', "This account can't sign in.", 'rid-login-02') },
    })
    const user = userEvent.setup()
    renderApp('/')

    await user.click(await screen.findByRole('button', { name: /Sign in as Avery Chen/ }))
    expect(await screen.findByText("This account can't sign in.")).toBeInTheDocument()
    expect(screen.getByText('Request id: rid-login-02')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument()
  })

  it('reaches every persona with the keyboard and signs in with Enter', async () => {
    const fake = installSignIn()
    const user = userEvent.setup()
    renderApp('/')

    const rows = await personaRows()
    rows[2]!.focus()
    expect(rows[2]).toHaveFocus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(fake.loginIds).toEqual(['U007']))
  })
})
