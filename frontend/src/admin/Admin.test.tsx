import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Absence, AdminUser, Policy } from '../api/types'
import { envelope, installFakeApi } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

const CONTROLLER = { role: 'controller_admin' as const, user_id: 'U002', full_name: 'Elena Duarte' }
const AUDITOR = { role: 'auditor' as const, user_id: 'U015', full_name: 'Kai Thompson' }

const USERS: AdminUser[] = [
  {
    user_id: 'U001', full_name: 'Morgan Lee', title: 'Operations Director', role: 'approver', department_id: 'D01',
    status: 'active', approval_limit_cad: '10000.00', manager_id: 'U002', delegate_user_id: null,
    email: 'morgan@harborline.example', hire_date: '2019-04-01', status_since: null, work_province: 'ON',
  },
  {
    user_id: 'U002', full_name: 'Elena Duarte', title: 'Controller', role: 'controller_admin', department_id: 'D02',
    status: 'active', approval_limit_cad: '250000.00', manager_id: null, delegate_user_id: null,
    email: 'elena@harborline.example', hire_date: '2018-01-08', status_since: null, work_province: 'ON',
  },
]

const POLICY: Policy = {
  rule_id: 'P02', rule_type: 'approval', condition: 'Invoice total over $10,000 CAD',
  required: 'dept_manager > finance_manager', notes: 'Adds the finance manager', updated_at: '2026-11-02T00:00:00Z',
  updated_by: null,
}

const ABSENCE: Absence = { id: 1, user_id: 'U012', delegate_user_id: 'U003', starts_on: '2026-10-20', ends_on: null }

describe('admin pages for the auditor', () => {
  it('shows users with no Edit column and no Edit button', async () => {
    installFakeApi({ ...billScreenRoutes(AUDITOR), 'GET /admin/users': { body: USERS } })
    renderApp('/admin/users')
    const table = await screen.findByRole('table', { name: 'Users' })
    await within(table).findByText('Morgan Lee')
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
      'Name', 'Role', 'Department', 'Status', 'Approval limit (CAD)', 'Manager', 'Delegate',
    ])
    expect(within(table).queryByRole('button', { name: /^Edit/ })).not.toBeInTheDocument()
  })

  it('shows policies with no Edit column and no Edit button', async () => {
    installFakeApi({ ...billScreenRoutes(AUDITOR), 'GET /admin/policies': { body: [POLICY] } })
    renderApp('/admin/policies')
    const table = await screen.findByRole('table', { name: 'Policies' })
    await within(table).findByText('Invoice total over $10,000 CAD')
    expect(within(table).getAllByRole('columnheader').map((th) => th.textContent)).toEqual([
      'Rule', 'Type', 'Condition', 'Required', 'Notes', 'Last changed',
    ])
    expect(within(table).queryByRole('button', { name: /^Edit/ })).not.toBeInTheDocument()
  })
})

describe('users', () => {
  it('lists users and saves only what changed', async () => {
    let sent: unknown = null
    installFakeApi({
      ...billScreenRoutes(CONTROLLER),
      'GET /admin/users': { body: USERS },
      'PATCH /admin/users/U001': async (request) => {
        sent = await request.json()
        return { body: { ...USERS[0], approval_limit_cad: '15000.00' } }
      },
    })
    const user = userEvent.setup()
    renderApp('/admin/users')

    const table = await screen.findByRole('table', { name: 'Users' })
    const row = (await within(table).findByText('Morgan Lee')).closest('tr')!
    // Edit is the last cell for the controller; the user id sits under the name.
    expect(within(row).getAllByRole('cell').at(-1)).toContainElement(within(row).getByRole('button', { name: 'Edit Morgan Lee' }))
    expect(within(row).getAllByRole('cell')[0]).toHaveTextContent('U001')
    expect(within(row).getByText('$10,000.00')).toBeInTheDocument()
    expect(within(row).getByText('Operations (D01)')).toBeInTheDocument()
    expect(within(row).getByText('Elena Duarte (U002)')).toBeInTheDocument()

    await user.click(within(row).getByRole('button', { name: 'Edit Morgan Lee' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Morgan Lee' })
    const limit = within(dialog).getByRole('textbox', { name: 'Approval limit (CAD)' })
    await user.clear(limit)
    await user.type(limit, '15000')
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(sent).toEqual({ approval_limit_cad: '15000.00' }))
  })

  it('refuses a malformed limit before sending', async () => {
    installFakeApi({ ...billScreenRoutes(CONTROLLER), 'GET /admin/users': { body: USERS } })
    const user = userEvent.setup()
    renderApp('/admin/users')
    await user.click(await screen.findByRole('button', { name: 'Edit Morgan Lee' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Morgan Lee' })
    const limit = within(dialog).getByRole('textbox', { name: 'Approval limit (CAD)' })
    await user.clear(limit)
    await user.type(limit, '1,000')
    expect(within(dialog).getByText('Enter an amount like 10000 or 10000.00')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })
})

describe('policies', () => {
  it("edits a rule and shows the server's threshold message", async () => {
    installFakeApi({
      ...billScreenRoutes(CONTROLLER),
      'GET /admin/policies': { body: [POLICY] },
      'PATCH /admin/policies/P02': {
        status: 422,
        body: envelope('policy.threshold_required', 'This rule needs an amount in its condition, e.g. "Invoice total over $10,000 CAD".'),
      },
    })
    const user = userEvent.setup()
    renderApp('/admin/policies')

    const table = await screen.findByRole('table', { name: 'Policies' })
    expect(await within(table).findByText('Invoice total over $10,000 CAD')).toBeInTheDocument()
    // Edit last, as on Users; the approver chain in words, one step per line.
    const row = within(table).getByText('Invoice total over $10,000 CAD').closest('tr')!
    expect(within(row).getAllByRole('cell').at(-1)).toContainElement(within(row).getByRole('button', { name: 'Edit rule P02' }))
    expect(within(row).getByText('Department manager')).toBeInTheDocument()
    expect(within(row).getByText('then Finance manager')).toBeInTheDocument()
    // Never edited: the dataset's date, alone, not the evening before in local time.
    expect(within(row).getByText('Nov 2, 2026')).toBeInTheDocument()
    expect(within(row).getByText('From the dataset')).toBeInTheDocument()
    await user.click(within(table).getByRole('button', { name: 'Edit rule P02' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit rule P02' })
    const condition = within(dialog).getByRole('textbox', { name: 'Condition' })
    await user.clear(condition)
    await user.type(condition, 'Large invoices')
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    expect(await within(dialog).findByText(/This rule needs an amount in its condition/)).toBeInTheDocument()
  })
})

describe('users who don\'t approve', () => {
  it('say "Can\'t approve" instead of a $0.00 limit', async () => {
    const clerk: AdminUser = { ...USERS[0]!, user_id: 'U005', full_name: 'Jordan Okafor', role: 'ap_clerk', approval_limit_cad: '0.00' }
    installFakeApi({ ...billScreenRoutes(CONTROLLER), 'GET /admin/users': { body: [...USERS, clerk] } })
    renderApp('/admin/users')
    const table = await screen.findByRole('table', { name: 'Users' })
    const row = (await within(table).findByText('Jordan Okafor')).closest('tr')!
    expect(within(row).getByText("Can't approve")).toBeInTheDocument()
    expect(within(row).queryByText('$0.00')).not.toBeInTheDocument()
  })
})

describe('absences', () => {
  it('lists absences and records a new one', async () => {
    let sent: unknown = null
    installFakeApi({
      ...billScreenRoutes(CONTROLLER),
      'GET /admin/absences': { body: [ABSENCE] },
      'POST /admin/absences': async (request) => {
        sent = await request.json()
        return { status: 201, body: { ...ABSENCE, id: 2 } }
      },
    })
    const user = userEvent.setup()
    renderApp('/admin/absences')

    const table = await screen.findByRole('table', { name: 'Absences' })
    const row = (await within(table).findByText('Sam Rivera')).closest('tr')!
    expect(within(row).getByText('Priya Natarajan')).toBeInTheDocument()
    expect(within(row).getByText('Open-ended')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Add absence' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add absence' })
    await user.click(within(dialog).getByRole('combobox', { name: 'Who is away' }))
    await user.click(await screen.findByRole('option', { name: 'Morgan Lee (U001)' }))
    await user.click(within(dialog).getByRole('combobox', { name: 'Delegate' }))
    // Sam Rivera is on leave, so can't be a delegate.
    expect(screen.queryByRole('option', { name: 'Sam Rivera (U012)' })).not.toBeInTheDocument()
    await user.click(await screen.findByRole('option', { name: 'Priya Natarajan (U003)' }))
    fireEvent.change(within(dialog).getByLabelText(/^From/), { target: { value: '2026-11-10' } })
    await user.click(within(dialog).getByRole('button', { name: 'Add absence' }))
    await waitFor(() => expect(sent).toEqual({ user_id: 'U001', delegate_user_id: 'U003', starts_on: '2026-11-10', ends_on: null }))
  })

  it('ends an absence that is under way, for the controller', async () => {
    let ended = false
    installFakeApi({
      ...billScreenRoutes(CONTROLLER),
      'GET /health': { body: { status: 'ok', as_of_date: '2026-11-02', llm_enabled: false } },
      'GET /admin/absences': () => ({ body: [ended ? { ...ABSENCE, ends_on: '2026-11-01' } : ABSENCE] }),
      'POST /admin/absences/1/end': () => {
        ended = true
        return { body: { ...ABSENCE, ends_on: '2026-11-01' } }
      },
    })
    const user = userEvent.setup()
    renderApp('/admin/absences')
    await user.click(await screen.findByRole('button', { name: 'End absence of Sam Rivera' }))
    const dialog = await screen.findByRole('dialog', { name: 'End absence' })
    expect(within(dialog).getByText('Sam Rivera is back: their approval steps go to them again, not to Priya Natarajan.'))
      .toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'End absence' }))
    expect(await screen.findByText('Absence ended')).toBeInTheDocument()
    // Over now, so no End button on it.
    await waitFor(() => expect(screen.queryByRole('button', { name: 'End absence of Sam Rivera' })).not.toBeInTheDocument())
  })

  it('shows the auditor the list without Add absence or End absence', async () => {
    installFakeApi({
      ...billScreenRoutes(AUDITOR),
      'GET /health': { body: { status: 'ok', as_of_date: '2026-11-02', llm_enabled: false } },
      'GET /admin/absences': { body: [ABSENCE] },
    })
    renderApp('/admin/absences')
    const table = await screen.findByRole('table', { name: 'Absences' })
    await within(table).findByText('Sam Rivera')
    expect(screen.queryByRole('button', { name: 'Add absence' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^End absence/ })).not.toBeInTheDocument()
  })
})
