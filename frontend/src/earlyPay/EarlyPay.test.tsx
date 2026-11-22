import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { EarlyPayReport, EarlyPaySuggestion } from '../api/types'
import { navItemsFor } from '../shell/navigation'
import { envelope, installFakeApi } from '../test/fakeApi'
import { billScreenRoutes } from '../test/fixtures'
import { currentLocation, renderApp } from '../test/renderApp'

const CLERK = { role: 'ap_clerk', user_id: 'U005' } as const

function suggestion(overrides: Partial<EarlyPaySuggestion> = {}): EarlyPaySuggestion {
  return {
    bill_id: 'AP-00418', vendor_id: 'V040', vendor_name: 'Lakeshore Hydro Services', status: 'scheduled', terms: 'net 21',
    method: 'EFT', invoice_date: '2026-10-14', due_date: '2026-11-04', discount_deadline: null, pay_on: '2026-11-04',
    scheduled_date: '2026-11-04', currency: 'CAD', total: '2011.13', saving: '0.00', saving_cad: '0.00',
    pay_amount: '2011.13', action: 'pay_on_due_date', reason: 'Due 2026-11-04. Paying earlier saves nothing.', notes: [],
    ...overrides,
  }
}

/** Paper Trail with its 2/10 discount open, an overdue Quillpad bill, and a bill paid on its due date. */
const REPORT: EarlyPayReport = {
  as_of: '2026-11-02',
  summary: { bills: 3, with_discount_open: 1, saving_cad: '10.84', to_reschedule: 1, pay_now: 1 },
  suggestions: [
    suggestion({
      bill_id: 'AP-00427', vendor_id: 'V024', vendor_name: 'Paper Trail Office Supply', terms: '2% off if paid within 10 days, net 30',
      invoice_date: '2026-10-26', due_date: '2026-11-25', discount_deadline: '2026-11-05', pay_on: '2026-11-04',
      scheduled_date: '2026-11-25', total: '612.64', saving: '10.84', saving_cad: '10.84', pay_amount: '601.80',
      action: 'reschedule', reason: 'Scheduled for 2026-11-25, after the discount ends. Move it to 2026-11-04 to save $10.84.',
      notes: ['Invoice due date 2026-11-27 isn\'t 2% off if paid within 10 days, net 30 from the invoice date.'],
    }),
    suggestion({ bill_id: 'AP-00399', vendor_id: 'V020', vendor_name: 'Quillpad Documents Ltd.', terms: 'net 30',
      due_date: '2026-11-01', pay_on: '2026-11-02', scheduled_date: '2026-11-01', action: 'pay_now',
      reason: 'Due 2026-11-01, already due: pay now.' }),
    suggestion(),
  ],
  history: {
    taken: 9, taken_cad: '296.18', missed: 10, missed_cad: '827.77',
    missed_payments: [{ payment_id: 'PAY-00175', bill_id: 'AP-00180', vendor_id: 'V010', invoice_date: '2026-05-01',
      paid_date: '2026-06-02', days_to_pay: 32, discount_cad: '201.93' }],
  },
}

describe('early payment', () => {
  it('shows the saving, what to reschedule, every bill\'s best pay date and the history', async () => {
    const fake = installFakeApi({ ...billScreenRoutes(CLERK), 'GET /early-pay': { body: REPORT } })
    renderApp('/early-pay')

    expect(await screen.findByRole('heading', { level: 1, name: 'Early payment' })).toBeInTheDocument()
    const summary = await screen.findByLabelText('Summary')
    expect(within(summary).getByText('$10.84')).toBeInTheDocument()
    expect(within(summary).getByText('1 bill with a discount still open')).toBeInTheDocument()
    expect(fake.urls.find((u) => u.pathname === '/api/early-pay')!.searchParams.get('include_pending')).toBe('false')

    const urgent = screen.getByRole('table', { name: 'To reschedule or pay now' })
    expect(within(urgent).getByText('Reschedule')).toBeInTheDocument()
    expect(within(urgent).getByText('Pay now')).toBeInTheDocument()
    expect(within(urgent).queryByText('AP-00418')).not.toBeInTheDocument() // on its due date: nothing to do

    const all = screen.getByRole('table', { name: 'Best pay dates' })
    const paper = within(all).getByRole('link', { name: 'AP-00427' }).closest('tr')!
    expect(within(paper).getByText('2% off if paid within 10 days, net 30')).toBeInTheDocument()
    expect(within(paper).getByText('Nov 4, 2026')).toBeInTheDocument() // best pay date
    expect(within(paper).getByText('Nov 5, 2026')).toBeInTheDocument() // the discount deadline
    expect(within(paper).getByText('$10.84')).toBeInTheDocument()
    expect(within(paper).getByText(/Move it to 2026-11-04 to save \$10.84/)).toBeInTheDocument()
    expect(within(paper).getByText(/isn't 2% off/)).toBeInTheDocument() // the note
    expect(within(all).getByText('Pay on the due date')).toBeInTheDocument()

    const history = screen.getByRole('region', { name: 'Discounts in the history' })
    expect(within(history).getByText('$827.77', { exact: false })).toBeInTheDocument()
    const missed = within(history).getByRole('table', { name: 'Missed discounts' })
    expect(within(missed).getByRole('link', { name: 'PAY-00175' })).toHaveAttribute('href', '/payments/PAY-00175')
    expect(within(missed).getByText('$201.93')).toBeInTheDocument()
  })

  it('includes bills in review through the URL', async () => {
    const fake = installFakeApi({ ...billScreenRoutes(CLERK), 'GET /early-pay': { body: REPORT } })
    const user = userEvent.setup()
    renderApp('/early-pay')
    await screen.findByRole('table', { name: 'Best pay dates' })

    await user.click(screen.getByText('Include bills in review'))
    await waitFor(() => expect(currentLocation()).toBe('/early-pay?include=pending'))
    await waitFor(() => expect(fake.urls.filter((u) => u.pathname === '/api/early-pay').at(-1)!.searchParams.get('include_pending')).toBe('true'))
    expect(await screen.findByText('3 approved, scheduled or in review')).toBeInTheDocument()
  })

  it('says when nothing needs to move', async () => {
    installFakeApi({
      ...billScreenRoutes(CLERK),
      'GET /early-pay': { body: { ...REPORT, suggestions: [suggestion()], summary: { ...REPORT.summary, to_reschedule: 0, pay_now: 0 } } },
    })
    renderApp('/early-pay')
    expect(await screen.findByText('Every payment is on its best date.')).toBeInTheDocument()
  })

  it('shows the server\'s refusal', async () => {
    installFakeApi({
      ...billScreenRoutes({ role: 'approver', user_id: 'U001' }),
      'GET /early-pay': { status: 403, body: envelope('auth.forbidden_role', "Your role (approver) can't do this.", 'rid-ep-1') },
    })
    renderApp('/early-pay')
    expect(await screen.findByText("Your role (approver) can't do this.")).toBeInTheDocument()
  })

  it('is in the AP, finance, controller and auditor menus only', () => {
    const has = (role: Parameters<typeof navItemsFor>[0]) => navItemsFor(role).some((item) => item.key === 'earlyPay')
    for (const role of ['ap_clerk', 'finance_manager', 'controller_admin', 'auditor'] as const) expect(has(role), role).toBe(true)
    for (const role of ['employee', 'approver'] as const) expect(has(role), role).toBe(false)
  })
})
