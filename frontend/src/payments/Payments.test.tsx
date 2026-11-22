import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Payment, PaymentDashboard, PaymentDetail } from '../api/types'
import { envelope, installFakeApi, type FakeRoute } from '../test/fakeApi'
import { billDetail, billScreenRoutes, billSummary, billsPage, vendorDetail } from '../test/fixtures'
import { currentLocation, renderApp } from '../test/renderApp'

export const CLERK = { role: 'ap_clerk', user_id: 'U005' } as const
export const FINANCE = { role: 'finance_manager', user_id: 'U003', release_limit_cad: '100000.00' } as const
export const CONTROLLER = { role: 'controller_admin', user_id: 'U002', release_limit_cad: null } as const

export const DASHBOARD: PaymentDashboard = {
  as_of: '2026-11-02',
  by_status: [
    { status: 'scheduled', count: 21, total_cad: '96457.18' },
    { status: 'settled', count: 377, total_cad: '1740825.21' },
  ],
  due_next_7_days_count: 9, due_next_7_days_cad: '24818.43', overdue_count: 1, overdue_cad: '483.00',
}

/** A scheduled payment, as GET /payments lists it (the demo's delegated Lakeshore Hydro payment). */
export function payment(overrides: Partial<Payment> = {}): Payment {
  return {
    payment_id: 'PAY-00416', bill_id: 'AP-00436', vendor_id: 'V040', vendor_name: 'Lakeshore Hydro Services',
    method: 'EFT', currency: 'CAD', amount: '1604.60', amount_cad: '1604.60', scheduled_date: '2026-11-02',
    paid_date: null, status: 'scheduled', reference: null, prepared_by: 'U005', released_by: null, released_at: null,
    ...overrides,
  }
}

/** GET /payments/{id}: the payment with its bill and empty history, and the given allowed_actions. */
export function paymentDetail(overrides: Partial<PaymentDetail> = {}): PaymentDetail {
  return {
    ...payment(), fx_rate_to_cad: '1', fx_rate_date: null, discount_taken: '0.00',
    bank_account: { id: 7, institution: '004', transit: '55123', account: '0094410', account_last4: '4410', masked: false,
      valid_from: '2026-01-01', valid_to: null },
    bill: billSummary({ bill_id: 'AP-00436', status: 'scheduled', vendor_id: 'V040', vendor_name: 'Lakeshore Hydro Services',
      vendor_invoice_number: 'DM-1010', total: '1604.60', total_cad: '1604.60', current_step: null }),
    lines: [], decisions: [], audit: [], allowed_actions: {},
    ...overrides,
  } as PaymentDetail
}

/** An approved bill with no payment yet (AP-00426, Cascadia, held by its pending bank change). */
export const APPROVED = billSummary({
  bill_id: 'AP-00426', status: 'approved', vendor_id: 'V004', vendor_name: 'Cascadia Cartage Ltd.',
  vendor_invoice_number: '1622', due_date: '2026-11-23', total: '2563.92', total_cad: '2563.92',
  open_flags: { block: 0, warn: 0, info: 0 }, top_flag_code: null,
})

/** Every route the payments screen reads, signed in as `role`, plus any overrides. */
export function paymentsRoutes(role: Parameters<typeof billScreenRoutes>[0], extra: Record<string, FakeRoute> = {}) {
  return {
    ...billScreenRoutes(role),
    'GET /payments/summary': { body: DASHBOARD },
    'GET /payments': { body: { items: [payment()], total: 1, limit: 50, offset: 0 } },
    'GET /bills': { body: billsPage([APPROVED]) },
    ...extra,
  }
}

describe('payments dashboard', () => {
  it('shows the totals, the approved bills and the scheduled payments', async () => {
    const fake = installFakeApi(paymentsRoutes(FINANCE))
    renderApp('/payments')

    expect(await screen.findByRole('heading', { level: 1, name: 'Payments' })).toBeInTheDocument()
    expect(screen.getByText('$100,000.00')).toBeInTheDocument() // the release limit line

    const overview = await screen.findByRole('region', { name: 'Overview' })
    expect(await within(overview).findByText('9 payments,', { exact: false })).toBeInTheDocument()
    expect(within(overview).getByText('$24,818.43')).toBeInTheDocument()
    expect(within(overview).getByText('$483.00')).toBeInTheDocument()
    const byStatus = within(overview).getByRole('table', { name: 'Payments by status' })
    const settled = within(byStatus).getByText('Settled').closest('tr')!
    expect(within(settled).getByText('377')).toBeInTheDocument()
    expect(within(settled).getByText('$1,740,825.21')).toBeInTheDocument()

    const approved = await screen.findByRole('table', { name: 'Approved bills' })
    const bill = (await within(approved).findByText('AP-00426')).closest('tr')!
    expect(within(bill).getByRole('link', { name: 'AP-00426' })).toHaveAttribute('href', '/bills/AP-00426')
    expect(within(bill).getByText('Cascadia Cartage Ltd.')).toBeInTheDocument()
    expect(fake.urls.find((u) => u.pathname === '/api/bills')!.searchParams.get('status')).toBe('approved')

    const list = await screen.findByRole('table', { name: 'Payments' })
    const row = (await within(list).findByText('PAY-00416')).closest('tr')!
    expect(within(row).getByRole('link', { name: 'AP-00436' })).toHaveAttribute('href', '/bills/AP-00436')
    expect(within(row).getByText('Lakeshore Hydro Services')).toBeInTheDocument()
    expect(within(row).getByText('$1,604.60')).toBeInTheDocument()
    expect(await within(row).findByText('Jordan Okafor')).toBeInTheDocument() // prepared by
    expect(within(row).getByText('Not released')).toBeInTheDocument()
    expect(fake.urls.find((u) => u.pathname === '/api/payments')!.searchParams.get('status')).toBe('scheduled')
  })

  it('switches status through the URL and pages through the list', async () => {
    const fake = installFakeApi(paymentsRoutes(CLERK, {
      'GET /payments': (request) => {
        const status = new URL(request.url).searchParams.get('status')
        return status === 'released'
          ? { body: { items: [], total: 0, limit: 50, offset: 0 } }
          : { body: { items: [payment({ status: 'settled', paid_date: '2026-10-30' })], total: 120, limit: 50, offset: 0 } }
      },
    }))
    const user = userEvent.setup()
    renderApp('/payments')
    expect(screen.queryByText(/You can release payments/)).not.toBeInTheDocument() // AP can't release

    await user.click(await screen.findByText('Released'))
    await waitFor(() => expect(currentLocation()).toBe('/payments?status=released'))
    expect(await screen.findByText('No released payments.')).toBeInTheDocument()

    await user.click(screen.getByText('All'))
    expect(await screen.findByText('120 payments')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '2' }))
    await waitFor(() => expect(currentLocation()).toBe('/payments?status=all&page=2'))
    const last = fake.urls.filter((u) => u.pathname === '/api/payments').at(-1)!
    expect(last.searchParams.has('status')).toBe(false)
    expect(last.searchParams.get('offset')).toBe('50')
  })

  it('says when nothing is approved or scheduled, and shows load errors with the request id', async () => {
    installFakeApi(paymentsRoutes(CONTROLLER, {
      'GET /bills': { body: billsPage([]) },
      'GET /payments': { body: { items: [], total: 0, limit: 50, offset: 0 } },
      'GET /payments/summary': { status: 403, body: envelope('auth.forbidden_role', 'The totals are unavailable.', 'rid-sum-1') },
    }))
    renderApp('/payments')
    expect(await screen.findByText('You can release payments of any amount.')).toBeInTheDocument()
    expect(await screen.findByText('No approved bill is waiting for a payment.')).toBeInTheDocument()
    expect(await screen.findByText('No scheduled payments.')).toBeInTheDocument()
    expect(await screen.findByText('The totals are unavailable.')).toBeInTheDocument()
    expect(screen.getByText('Request id: rid-sum-1')).toBeInTheDocument()
  })
})

/** GET /bills/{id} for an approved bill, with the given schedule_payment answer. */
function approvedDetail(schedule: { allowed: boolean; reason?: string | null }) {
  return billDetail({ ...APPROVED, payments: [], allowed_actions: { schedule_payment: { allowed: schedule.allowed, reason: schedule.reason ?? null } } })
}

describe('schedule a payment', () => {
  it('schedules with the vendor\'s method and the chosen date', async () => {
    let sent: unknown = null
    const fake = installFakeApi(paymentsRoutes(CLERK, {
      'GET /bills/AP-00426': { body: approvedDetail({ allowed: true }) },
      'GET /vendors/V004': { body: vendorDetail({ vendor_id: 'V004', legal_name: 'Cascadia Cartage Ltd.', preferred_payment_method: 'CHEQUE' }) },
      'POST /bills/AP-00426/payments': async (request) => {
        sent = await request.json()
        return { status: 201, body: paymentDetail({ payment_id: 'PAY-00419', bill_id: 'AP-00426' }) }
      },
    }))
    const user = userEvent.setup()
    renderApp('/payments')

    const approved = await screen.findByRole('table', { name: 'Approved bills' })
    await user.click(await within(approved).findByRole('button', { name: 'Schedule' }))
    const dialog = await screen.findByRole('dialog', { name: 'Schedule payment' })
    expect(within(dialog).getByText(/you can't release a payment you prepared/)).toBeInTheDocument()
    await waitFor(() => expect(within(dialog).getByRole('combobox', { name: 'Method' })).toHaveValue('Cheque'))
    const date = within(dialog).getByLabelText(/Payment date/)
    expect(date).toHaveValue('2026-11-23') // the due date, still ahead of the business date
    await user.clear(date)
    await user.type(date, '2026-11-20')
    await user.click(within(dialog).getByRole('button', { name: 'Schedule payment' }))

    await waitFor(() => expect(sent).toEqual({ scheduled_date: '2026-11-20', method: 'CHEQUE' }))
    expect(await screen.findByText('Payment scheduled')).toBeInTheDocument()
    // The payments and bills lists are read again.
    await waitFor(() => expect(fake.calls.filter((c) => c === 'GET /payments').length).toBeGreaterThan(1))
  })

  it('shows why AP can\'t schedule a bill instead of the button', async () => {
    installFakeApi(paymentsRoutes(CLERK, {
      'GET /bills/AP-00426': { body: approvedDetail({ allowed: false, reason: "Bank change BC-009 for this vendor isn't verified yet." }) },
    }))
    renderApp('/payments')
    const approved = await screen.findByRole('table', { name: 'Approved bills' })
    expect(await within(approved).findByText("Bank change BC-009 for this vendor isn't verified yet.")).toBeInTheDocument()
    expect(within(approved).queryByRole('button', { name: 'Schedule' })).not.toBeInTheDocument()
  })

  it('shows a refusal from the server in the dialog', async () => {
    installFakeApi(paymentsRoutes(CLERK, {
      'GET /bills/AP-00426': { body: approvedDetail({ allowed: true }) },
      'POST /bills/AP-00426/payments': {
        status: 409, body: envelope('payment.already_exists', 'Payment PAY-00419 already covers this bill.', 'rid-sch-1'),
      },
    }))
    const user = userEvent.setup()
    renderApp('/payments')
    await user.click(await screen.findByRole('button', { name: 'Schedule' }))
    const dialog = await screen.findByRole('dialog', { name: 'Schedule payment' })
    await user.click(within(dialog).getByRole('button', { name: 'Schedule payment' }))
    expect(await within(dialog).findByText('Payment PAY-00419 already covers this bill.')).toBeInTheDocument()
    expect(within(dialog).getByText('Request id: rid-sch-1')).toBeInTheDocument()
  })

  it('has no Actions column for roles that don\'t schedule', async () => {
    installFakeApi(paymentsRoutes(FINANCE))
    renderApp('/payments')
    const approved = await screen.findByRole('table', { name: 'Approved bills' })
    await within(approved).findByText('AP-00426')
    expect(within(approved).queryByText('Actions')).not.toBeInTheDocument()
  })
})
