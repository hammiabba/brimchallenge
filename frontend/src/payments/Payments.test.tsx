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

/** Two scheduled payments: PAY-00416 (U003 approved its bill as a delegate) and PAY-00417 (U003 didn't). */
const SCHEDULED = [payment(), payment({ payment_id: 'PAY-00417', bill_id: 'AP-00437', vendor_name: 'Brightmore Consulting Group' })]
const P11 = 'U003 approved this bill, so they can\'t release its payment (P11).'

function releaseRoutes(extra: Record<string, FakeRoute> = {}) {
  return paymentsRoutes(FINANCE, {
    'GET /payments': { body: { items: SCHEDULED, total: 2, limit: 50, offset: 0 } },
    'GET /payments/PAY-00416': { body: paymentDetail({ allowed_actions: { release: { allowed: false, reason: P11 } } }) },
    'GET /payments/PAY-00417': { body: paymentDetail({
      payment_id: 'PAY-00417', bill_id: 'AP-00437', vendor_name: 'Brightmore Consulting Group', amount: '4407.00',
      allowed_actions: { release: { allowed: true, reason: 'Finance manager may release up to $100,000 (P09).' } },
    }) },
    ...extra,
  })
}

describe('release a payment', () => {
  it('offers Release only where the server allows it, and says why not elsewhere', async () => {
    installFakeApi(releaseRoutes())
    renderApp('/payments')
    const list = await screen.findByRole('table', { name: 'Payments' })
    const blocked = (await within(list).findByText('PAY-00416')).closest('tr')!
    expect(await within(blocked).findByText(P11)).toBeInTheDocument()
    expect(within(blocked).queryByRole('button', { name: 'Release' })).not.toBeInTheDocument()
    const open = within(list).getByText('PAY-00417').closest('tr')!
    expect(await within(open).findByRole('button', { name: 'Release' })).toBeInTheDocument()
  })

  it('releases with an Idempotency-Key, keeps the key when retrying the same attempt, and refreshes', async () => {
    const keys: (string | null)[] = []
    let fail = true
    const fake = installFakeApi(releaseRoutes({
      'POST /payments/PAY-00417/release': (request) => {
        keys.push(request.headers.get('Idempotency-Key'))
        if (fail) {
          fail = false
          return { status: 409, body: envelope('payment.bank_account_changed',
            'The vendor\'s bank account changed after this payment was scheduled. Cancel and reschedule.', 'rid-rel-1') }
        }
        return { body: paymentDetail({ payment_id: 'PAY-00417', status: 'released', released_by: 'U003' }) }
      },
    }))
    const user = userEvent.setup()
    renderApp('/payments')

    await user.click(await screen.findByRole('button', { name: 'Release' }))
    const dialog = await screen.findByRole('dialog', { name: 'Release payment' })
    expect(within(dialog).getByText(/to the account ending 4410/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Release payment' }))
    expect(await within(dialog).findByText(/bank account changed after this payment was scheduled/)).toBeInTheDocument()
    expect(within(dialog).getByText('Request id: rid-rel-1')).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Release payment' }))
    expect(await screen.findByText('Payment released')).toBeInTheDocument()
    expect(keys).toHaveLength(2)
    expect(keys[0]).toMatch(/^release-[0-9a-f-]{36}$/)
    expect(keys[1]).toBe(keys[0])
    await waitFor(() => expect(fake.calls.filter((c) => c === 'GET /payments/summary').length).toBeGreaterThan(1))
  })

  it('uses a new key for a new attempt after the dialog was closed', async () => {
    const keys: (string | null)[] = []
    installFakeApi(releaseRoutes({
      'POST /payments/PAY-00417/release': (request) => {
        keys.push(request.headers.get('Idempotency-Key'))
        return { status: 403, body: envelope('payment.release_refused', 'Payment of $150,000.00 is over your release limit (P09).') }
      },
    }))
    const user = userEvent.setup()
    renderApp('/payments')

    await user.click(await screen.findByRole('button', { name: 'Release' }))
    let dialog = await screen.findByRole('dialog', { name: 'Release payment' })
    await user.click(within(dialog).getByRole('button', { name: 'Release payment' }))
    expect(await within(dialog).findByText(/over your release limit/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    await user.click(screen.getByRole('button', { name: 'Release' }))
    dialog = await screen.findByRole('dialog', { name: 'Release payment' })
    await user.click(within(dialog).getByRole('button', { name: 'Release payment' }))
    await waitFor(() => expect(keys).toHaveLength(2))
    expect(keys[1]).not.toBe(keys[0])
  })

  it('has no Actions column for an auditor', async () => {
    installFakeApi(paymentsRoutes({ role: 'auditor', user_id: 'U015' }))
    renderApp('/payments')
    const list = await screen.findByRole('table', { name: 'Payments' })
    await within(list).findByText('PAY-00416')
    expect(within(list).queryByText('Actions')).not.toBeInTheDocument()
  })
})

describe('cancel a payment', () => {
  it('cancels with a comment and refreshes the lists', async () => {
    let sent: unknown = null
    const fake = installFakeApi(paymentsRoutes(CLERK, {
      'GET /payments/PAY-00416': { body: paymentDetail({ allowed_actions: {
        release: { allowed: false, reason: "Your role (ap_clerk) can't release payments." },
        cancel: { allowed: true, reason: null },
      } }) },
      'POST /payments/PAY-00416/cancel': async (request) => {
        sent = await request.json()
        return { body: paymentDetail({ status: 'cancelled', allowed_actions: {} }) }
      },
    }))
    const user = userEvent.setup()
    renderApp('/payments')

    const list = await screen.findByRole('table', { name: 'Payments' })
    const row = (await within(list).findByText('PAY-00416')).closest('tr')!
    // AP isn't a releaser, so the release refusal isn't shown to them; only what they can do.
    expect(within(row).queryByText(/can't release/)).not.toBeInTheDocument()
    await user.click(await within(row).findByRole('button', { name: 'Cancel payment' }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel payment' })
    expect(within(dialog).getByText(/AP-00436 goes back to approved/)).toBeInTheDocument()
    await user.type(within(dialog).getByRole('textbox', { name: 'Comment' }), 'Vendor asked for a cheque instead')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel payment' }))

    await waitFor(() => expect(sent).toEqual({ comment: 'Vendor asked for a cheque instead' }))
    expect(await screen.findByText('Payment cancelled')).toBeInTheDocument()
    await waitFor(() => expect(fake.calls.filter((c) => c === 'GET /bills').length).toBeGreaterThan(1))
  })

  it('shows a refusal in the dialog', async () => {
    installFakeApi(paymentsRoutes(FINANCE, {
      'GET /payments/PAY-00416': { body: paymentDetail({ allowed_actions: { cancel: { allowed: true, reason: null } } }) },
      'POST /payments/PAY-00416/cancel': {
        status: 409, body: envelope('payment.invalid_state', 'The payment is released; it must be scheduled.', 'rid-cx-1'),
      },
    }))
    const user = userEvent.setup()
    renderApp('/payments')
    await user.click(await screen.findByRole('button', { name: 'Cancel payment' }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel payment' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel payment' }))
    expect(await within(dialog).findByText('The payment is released; it must be scheduled.')).toBeInTheDocument()
  })

  it('has no Cancel button when the server doesn\'t allow it', async () => {
    installFakeApi(paymentsRoutes(CLERK, {
      'GET /payments/PAY-00416': { body: paymentDetail({ allowed_actions: {
        cancel: { allowed: false, reason: 'The payment is released; only a scheduled payment can be cancelled.' },
      } }) },
    }))
    renderApp('/payments')
    const list = await screen.findByRole('table', { name: 'Payments' })
    await within(list).findByText('PAY-00416')
    await waitFor(() => expect(within(list).queryByRole('button', { name: 'Cancel payment' })).not.toBeInTheDocument())
  })
})

/** PAY-00416 as the server returns it after U003 approved its bill as U012's delegate, scheduled by AP. */
const DETAIL = paymentDetail({
  bill: billSummary({ bill_id: 'AP-00436', status: 'scheduled', vendor_id: 'V040', vendor_name: 'Lakeshore Hydro Services',
    vendor_invoice_number: 'DM-1010', total: '1604.60', total_cad: '1604.60', current_step: null }),
  lines: [{
    line_no: 1, description: 'Lighting retrofit, loading bays 3-4', quantity: '1', unit_price: '1420.00', amount: '1420.00',
    line_type: 'services', gst_hst_code: 'HST13', pst_qst_code: null, gl_account: '5030', department_id: 'D01',
    suggested_gl_account: null, suggested_department_id: null, suggestion_confidence: null, suggestion_reason: null,
    coding_status: 'accepted', coded_by: null, coded_at: null,
  }],
  decisions: [{
    decision_id: 'AP-A-00478', step_no: 1, actor_user_id: 'U003', actor_role: 'finance_manager', step_role: 'dept_manager',
    on_behalf_of: 'U012', decision: 'approved', comment: 'Approved for the demo.', acted_at: '2026-11-02T15:00:00Z', origin: 'app',
  }],
  audit: [{
    seq: 70, event_id: 'ev-70', at: '2026-11-02T16:00:00Z', actor_user_id: 'U005', actor_role: 'ap_clerk', on_behalf_of: null,
    action: 'payment.scheduled', entity_type: 'payment', entity_id: 'PAY-00416', before: null,
    after: { bill_id: 'AP-00436', method: 'EFT' }, comment: null, request_id: 'r70',
  }],
  allowed_actions: { release: { allowed: false, reason: P11 }, cancel: { allowed: true, reason: null } },
})

describe('payment detail', () => {
  it('opens from the list and links back to the bill, the vendor and the audit log', async () => {
    installFakeApi(paymentsRoutes(FINANCE, { 'GET /payments/PAY-00416': { body: DETAIL } }))
    const user = userEvent.setup()
    renderApp('/payments')

    const list = await screen.findByRole('table', { name: 'Payments' })
    await user.click(await within(list).findByRole('link', { name: 'PAY-00416' }))
    await waitFor(() => expect(currentLocation()).toBe('/payments/PAY-00416'))

    expect(await screen.findByRole('heading', { level: 1, name: 'Payment PAY-00416' })).toBeInTheDocument()
    const summary = screen.getByRole('region', { name: 'Payment summary' })
    expect(within(summary).getByRole('link', { name: 'AP-00436' })).toHaveAttribute('href', '/bills/AP-00436')
    expect(within(summary).getByRole('link', { name: 'V040' })).toHaveAttribute('href', '/vendors/V040')
    expect(within(summary).getByText('$1,604.60')).toBeInTheDocument()
    expect(within(summary).getByText('0094410')).toBeInTheDocument()
    expect(within(summary).getByText('Institution 004, transit 55123')).toBeInTheDocument()
    expect(await within(summary).findByText('Jordan Okafor')).toBeInTheDocument() // prepared by
    // Finance sees why they can't release (P11) and may still cancel.
    expect(await within(summary).findByText(P11)).toBeInTheDocument()
    expect(within(summary).getByRole('button', { name: 'Cancel payment' })).toBeInTheDocument()

    const chain = screen.getByRole('table', { name: 'Approval chain' })
    expect(within(chain).getByText('Step 1, Department manager')).toBeInTheDocument()
    expect(await within(chain).findByText('on behalf of Sam Rivera')).toBeInTheDocument()
    expect(within(chain).getByText('Approved for the demo.')).toBeInTheDocument()

    const codes = screen.getByRole('table', { name: 'Accounting codes' })
    expect(await within(codes).findByText(/Warehouse supplies/)).toBeInTheDocument()
    expect(await within(codes).findByText('Operations (D01)')).toBeInTheDocument()

    expect(screen.getByRole('button', { name: 'Show 1 event' })).toBeInTheDocument()
    // Finance doesn't have the audit log in its sidebar, so no link to it.
    expect(screen.queryByRole('link', { name: 'Open this payment in the audit log' })).not.toBeInTheDocument()
  })

  it('links to the audit log for the controller, and releases from the detail view', async () => {
    let released = false
    installFakeApi(paymentsRoutes(CONTROLLER, {
      'GET /payments/PAY-00416': () => ({ body: released
        ? { ...DETAIL, status: 'released', released_by: 'U002', allowed_actions: {} }
        : { ...DETAIL, allowed_actions: { release: { allowed: true, reason: 'The controller may release any payment.' } } } }),
      'POST /payments/PAY-00416/release': () => {
        released = true
        return { body: { ...DETAIL, status: 'released', released_by: 'U002', allowed_actions: {} } }
      },
    }))
    const user = userEvent.setup()
    renderApp('/payments/PAY-00416')

    expect(await screen.findByRole('link', { name: 'Open this payment in the audit log' }))
      .toHaveAttribute('href', '/audit?entity_type=payment&entity_id=PAY-00416')
    await user.click(await screen.findByRole('button', { name: 'Release' }))
    const dialog = await screen.findByRole('dialog', { name: 'Release payment' })
    await user.click(within(dialog).getByRole('button', { name: 'Release payment' }))
    // Notifications live in one store for the whole file, so an earlier test's may still be on screen.
    expect((await screen.findAllByText('Payment released')).length).toBeGreaterThan(0)
    const summary = screen.getByRole('region', { name: 'Payment summary' })
    expect(await within(summary).findByText('Released')).toBeInTheDocument()
    expect(within(summary).queryByRole('button', { name: 'Release' })).not.toBeInTheDocument()
  })

  it('says when the payment can\'t be found', async () => {
    installFakeApi(paymentsRoutes(FINANCE, {
      'GET /payments/PAY-99999': { status: 404, body: envelope('payment.not_found', 'Payment PAY-99999 not found.') },
    }))
    renderApp('/payments/PAY-99999')
    expect(await screen.findByRole('heading', { level: 1, name: 'Payment not found' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to payments' })).toHaveAttribute('href', '/payments')
  })
})
