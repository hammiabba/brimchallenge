import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { envelope, installFakeApi, makeMe } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

const APPROVER = { role: 'approver' as const, user_id: 'U001', full_name: 'Morgan Lee', department_id: 'D01' }

describe('out of office', () => {
  it('saves a delegate with dates, offering only other active signers', async () => {
    let sent: unknown = null
    installFakeApi({
      ...billScreenRoutes(APPROVER),
      'PUT /me/delegation': async (request) => {
        sent = await request.json()
        return { body: makeMe(APPROVER) }
      },
    })
    const user = userEvent.setup()
    renderApp('/out-of-office')

    expect(await screen.findByRole('heading', { name: 'Out of office' })).toBeInTheDocument()
    expect(screen.getByText('You are not signing for anyone right now.')).toBeInTheDocument()
    await user.click(screen.getByRole('combobox', { name: 'Delegate' }))
    const listbox = await screen.findByRole('listbox')
    // Not yourself, nobody on leave, nobody outside the signer roles.
    expect(within(listbox).queryByText(/Morgan Lee/)).not.toBeInTheDocument()
    expect(within(listbox).queryByText(/Sam Rivera/)).not.toBeInTheDocument()
    expect(within(listbox).queryByText(/Jordan Okafor/)).not.toBeInTheDocument()
    await user.click(within(listbox).getByRole('option', { name: 'Priya Natarajan, Finance Manager (U003)' }))
    fireEvent.change(screen.getByLabelText(/^From/), { target: { value: '2026-11-10' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-11-14' } })
    await user.click(screen.getByRole('button', { name: 'Save out of office' }))

    await waitFor(() => expect(sent).toEqual({ delegate_user_id: 'U003', starts_on: '2026-11-10', ends_on: '2026-11-14' }))
  })

  it('lists who you sign for, and shows a refusal', async () => {
    installFakeApi({
      ...billScreenRoutes({
        ...APPROVER,
        acting_for: [{ user_id: 'U012', full_name: 'Sam Rivera', starts_on: '2026-10-20', ends_on: null }],
      }),
      'PUT /me/delegation': { status: 422, body: envelope('absence.bad_delegate', 'U003 must be an active approver.') },
    })
    const user = userEvent.setup()
    renderApp('/out-of-office')

    expect(await screen.findByText(/Sam Rivera, from/)).toBeInTheDocument()
    expect(screen.getByText(/until further notice/)).toBeInTheDocument()
    await user.click(screen.getByRole('combobox', { name: 'Delegate' }))
    await user.click(await screen.findByRole('option', { name: 'Priya Natarajan, Finance Manager (U003)' }))
    fireEvent.change(screen.getByLabelText(/^From/), { target: { value: '2026-11-10' } })
    await user.click(screen.getByRole('button', { name: 'Save out of office' }))
    expect(await screen.findByText('U003 must be an active approver.')).toBeInTheDocument()
  })

  it('refuses an end date before the start date', async () => {
    installFakeApi(billScreenRoutes(APPROVER))
    renderApp('/out-of-office')
    await screen.findByRole('heading', { name: 'Out of office' })
    fireEvent.change(screen.getByLabelText(/^From/), { target: { value: '2026-11-10' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-11-01' } })
    expect(screen.getByText('The end date is before the start date')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save out of office' })).toBeDisabled()
  })
})

describe('out of office for roles without approvals', () => {
  it('shows one line instead of a form the server would refuse', async () => {
    installFakeApi(billScreenRoutes({ role: 'auditor', user_id: 'U015' }))
    renderApp('/out-of-office')
    expect(await screen.findByText(/your role has no approvals to hand over/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save out of office' })).not.toBeInTheDocument()
  })
})
