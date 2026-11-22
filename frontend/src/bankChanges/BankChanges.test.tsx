import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { BankChange } from '../api/types'
import { envelope, installFakeApi } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { currentLocation, renderApp } from '../test/renderApp'

const PENDING: BankChange = {
  change_id: 'BCR-0007', vendor_id: 'V011', status: 'pending_verification', request_channel: 'email_request',
  requested_at: '2026-10-30T14:00:00Z', requested_by: 'U005', old_account_last4: '1111', new_account_last4: '4821',
  new_account: '0004821', new_institution: '010', new_transit: '54321', verified_at: null, verified_by: null,
  verified_by_callback: false, origin: 'app',
}

describe('bank changes', () => {
  it('opens on the pending requests with the full new account when the server sends it', async () => {
    const fake = installFakeApi({ ...billScreenRoutes({ role: 'finance_manager', user_id: 'U003' }), 'GET /bank-changes': { body: [PENDING] } })
    renderApp('/bank-changes')

    const table = await screen.findByRole('table', { name: 'Bank changes' })
    const row = (await within(table).findByText('BCR-0007')).closest('tr')!
    expect(within(row).getByRole('link', { name: 'V011' })).toHaveAttribute('href', '/vendors/V011')
    expect(within(row).getByText('0004821')).toBeInTheDocument()
    expect(within(row).getByText('Institution 010, transit 54321')).toBeInTheDocument()
    expect(await within(row).findByText('Jordan Okafor')).toBeInTheDocument()
    expect(fake.urls.find((u) => u.pathname === '/api/bank-changes')!.searchParams.get('status')).toBe('pending_verification')
  })

  it('switches status through the URL', async () => {
    const fake = installFakeApi({ ...billScreenRoutes(), 'GET /bank-changes': { body: [] } })
    const user = userEvent.setup()
    renderApp('/bank-changes')
    expect(await screen.findByText('No bank change is waiting for verification.')).toBeInTheDocument()

    await user.click(screen.getByText('All'))
    await waitFor(() => expect(currentLocation()).toBe('/bank-changes?status=all'))
    expect(await screen.findByText('No bank change has been requested.')).toBeInTheDocument()
    expect(fake.urls.filter((u) => u.pathname === '/api/bank-changes').at(-1)!.searchParams.has('status')).toBe(false)
  })

  it('verifies with a comment, and shows a refusal in the dialog', async () => {
    let sent: unknown = null
    const fake = installFakeApi({
      ...billScreenRoutes({ role: 'finance_manager', user_id: 'U003' }),
      'GET /bank-changes': { body: [PENDING] },
      'POST /bank-changes/BCR-0007/reject': {
        status: 403, body: envelope('bank_change.self_verify', "You can't decide on your own request.", 'rid-bc-1'),
      },
      'POST /bank-changes/BCR-0007/verify': async (request) => {
        sent = await request.json()
        return { body: { ...PENDING, status: 'verified', verified_by: 'U003', verified_at: '2026-11-02T15:00:00Z' } }
      },
    })
    const user = userEvent.setup()
    renderApp('/bank-changes')

    await user.click(await screen.findByRole('button', { name: 'Reject' }))
    let dialog = await screen.findByRole('dialog', { name: 'Reject bank change' })
    await user.click(within(dialog).getByRole('button', { name: 'Reject bank change' }))
    expect(await within(dialog).findByText("You can't decide on your own request.")).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    await user.click(screen.getByRole('button', { name: 'Verify' }))
    dialog = await screen.findByRole('dialog', { name: 'Verify bank change' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Comment' }), 'Called 905-555-0100')
    await user.click(within(dialog).getByRole('button', { name: 'Verify bank change' }))
    await waitFor(() => expect(sent).toEqual({ comment: 'Called 905-555-0100' }))
    // The list is fetched again after the decision.
    await waitFor(() => expect(fake.calls.filter((c) => c === 'GET /bank-changes').length).toBeGreaterThan(1))
  })
})
